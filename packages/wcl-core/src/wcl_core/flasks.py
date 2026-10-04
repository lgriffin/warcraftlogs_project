"""
Flasks and elixirs: which consumable is which, and whether a player came prepared.

In TBC a flask counts as both a battle and a guardian elixir, so a player is *prepared* with a flask, or with one
battle elixir and one guardian elixir together. The aura ids and names are the ``flasks``, ``battle_elixirs`` and
``guardian_elixirs`` sections of ``data/consumes_config.json``.

Flasks and elixirs are drunk before the pull and last one to two hours, so they never show in cast events and are read
from the buffs table instead: each aura there has ``bands`` (``startTime``/``endTime``, report-relative ms), and WCL
opens a band at the start of a fight for an aura the player already had when it began. A boss pull is covered when a
band is up within ``PULL_GRACE_MS`` of the pull starting. Each player is scored only on the pulls they were in, from the
fight's ``friendlyPlayers`` (actor ids); a fight without that list counts for everyone.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any

from .common.log import get_logger
from .models import FlaskCoverage, PlayerIdentity

logger = get_logger(__name__)

FLASK = "flask"
BATTLE_ELIXIR = "battle_elixir"
GUARDIAN_ELIXIR = "guardian_elixir"

# Config section -> kind.
SECTIONS = {"flasks": FLASK, "battle_elixirs": BATTLE_ELIXIR, "guardian_elixirs": GUARDIAN_ELIXIR}

# How a player was prepared: a flask, a battle and a guardian elixir, or neither.
PREPARED_FLASK = "flask"
PREPARED_ELIXIRS = "elixirs"
NOT_PREPARED = ""

# An aura that comes up this soon after the pull still counts: elixirs are often drunk on the pull.
PULL_GRACE_MS = 5_000


@dataclass(frozen=True)
class FlaskCatalog:
    """Every tracked flask and elixir: aura id to (name, kind)."""

    auras: Mapping[int, tuple[str, str]] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> FlaskCatalog:
        """From a consumes config; missing or malformed sections are skipped."""
        auras: dict[int, tuple[str, str]] = {}
        for section, kind in SECTIONS.items():
            entries = config.get(section)
            if not isinstance(entries, Mapping):
                continue
            for spell_id, name in entries.items():
                try:
                    auras[int(spell_id)] = (str(name), kind)
                except (TypeError, ValueError):
                    logger.warning("Ignoring %s entry %r", section, spell_id)
        return cls(auras)

    @property
    def names(self) -> tuple[str, ...]:
        """Every tracked name, in config order, as storage records it."""
        return tuple(dict.fromkeys(name for name, _ in self.auras.values()))

    def kind_of(self, name: str) -> str:
        """``FLASK``, ``BATTLE_ELIXIR``, ``GUARDIAN_ELIXIR`` or "" for anything else, ignoring case."""
        return self._kinds.get(name.lower(), "")

    @cached_property
    def _kinds(self) -> dict[str, str]:
        return {name.lower(): kind for name, kind in self.auras.values()}


@lru_cache(maxsize=1)
def load_catalog() -> FlaskCatalog:
    """The catalogue from the bundled ``consumes_config.json``; empty if it is missing or unreadable."""
    from . import paths

    path = Path(paths.get_consumes_config_path())
    try:
        with path.open(encoding="utf-8") as f:
            return FlaskCatalog.from_config(json.load(f))
    except (OSError, ValueError) as e:
        logger.warning("Could not read flasks and elixirs from %s: %s", path, e)
        return FlaskCatalog()


def preparation(names: Iterable[str], catalog: FlaskCatalog) -> str:
    """``PREPARED_FLASK``, ``PREPARED_ELIXIRS`` or ``NOT_PREPARED`` for the consumables one player had."""
    return preparation_of_kinds({catalog.kind_of(n) for n in names})


@dataclass(frozen=True)
class BossPull:
    """One boss pull: when it began and the actor ids in it (None when the fight did not say)."""

    start: int
    players: frozenset[int] | None = None

    def includes(self, source_id: int) -> bool:
        return self.players is None or source_id in self.players


def boss_pulls(fights: Iterable[Mapping[str, Any]]) -> list[BossPull]:
    """Every boss pull (a fight with an encounter id, killed or not), in start order."""
    pulls = []
    for f in fights:
        if not f.get("encounterID"):
            continue
        friendly = f.get("friendlyPlayers")
        players = frozenset(int(p) for p in friendly) if isinstance(friendly, list) else None
        pulls.append(BossPull(int(f.get("startTime") or 0), players))
    return sorted(pulls, key=lambda p: p.start)


def pull_starts_for(pulls: Iterable[BossPull], source_id: int) -> list[int]:
    """Start times of the pulls the actor ``source_id`` was in."""
    return [p.start for p in pulls if p.includes(source_id)]


def _up_at(band: Mapping[str, Any], start: int) -> bool:
    return int(band.get("startTime") or 0) <= start + PULL_GRACE_MS and int(band.get("endTime") or 0) > start


def flask_coverage(
    player: PlayerIdentity,
    report_id: str,
    auras: Iterable[Mapping[str, Any]],
    pulls: list[int],
    catalog: FlaskCatalog,
) -> FlaskCoverage:
    """Which of ``pulls`` (start times of the pulls ``player`` was in) they had a flask or an elixir pair up for, from
    their buffs-table ``auras``."""
    tracked = [(catalog.auras[a["guid"]], a.get("bands") or []) for a in auras if a.get("guid") in catalog.auras]
    coverage = FlaskCoverage(player.name, player.role, report_id, boss_pulls=len(pulls))
    by_kind: dict[str, list[str]] = {FLASK: [], BATTLE_ELIXIR: [], GUARDIAN_ELIXIR: []}
    for (name, kind), _bands in tracked:
        if name not in by_kind[kind]:
            by_kind[kind].append(name)
    coverage.flasks = sorted(by_kind[FLASK])
    coverage.battle_elixirs = sorted(by_kind[BATTLE_ELIXIR])
    coverage.guardian_elixirs = sorted(by_kind[GUARDIAN_ELIXIR])
    for start in pulls:
        up = {kind for (_name, kind), bands in tracked if any(_up_at(b, start) for b in bands)}
        prepared = preparation_of_kinds(up)
        if prepared == PREPARED_FLASK:
            coverage.flask_pulls += 1
        elif prepared == PREPARED_ELIXIRS:
            coverage.elixir_pair_pulls += 1
    return coverage


def preparation_of_kinds(kinds: set[str]) -> str:
    """``preparation`` for a set of kinds already looked up."""
    if FLASK in kinds:
        return PREPARED_FLASK
    if BATTLE_ELIXIR in kinds and GUARDIAN_ELIXIR in kinds:
        return PREPARED_ELIXIRS
    return NOT_PREPARED
