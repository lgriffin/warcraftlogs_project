"""Game rulesets: the per-expansion knowledge the analysis needs, kept out of the analysis code.

Classic, The Burning Crusade and Forever raids are analysed by the same code, but which classes can tank or heal,
which consumables, interrupts, debuffs, totems and cooldowns to look for, and which spell ids mean Heroism all
depend on the expansion. A ``GameRules`` holds that knowledge for one expansion. Its data lives in
``wcl_core/data/<ruleset>/``: ``rules.json`` for the class and spell tables, beside the ``*_config.json`` catalogs.

The ruleset is picked from a raid's **expansion** (``wcl_core.game_version``), not from the Warcraft Logs site,
because one site can host several eras: ``fresh`` went from Classic into The Burning Crusade, and a Karazhan log
needs TBC rules whichever site it came from.

Only The Burning Crusade has a ruleset so far. Every other expansion, and an unknown one, gets it too, which is what
the analysis has always done; adding a ruleset is a new data folder plus an entry in ``RULESETS``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from . import paths
from .game_version import BURNING_CRUSADE

TBC = "tbc"

# Ruleset folder per expansion name (as ``wcl_core.game_version.EXPANSIONS`` spells it).
RULESETS: dict[str, str] = {
    BURNING_CRUSADE: TBC,
}

# What an expansion without a ruleset of its own, or an unknown one, is analysed with.
DEFAULT_RULESET = paths.DEFAULT_RULESET


@dataclass(frozen=True)
class GameRules:
    """One expansion's rules, as read from ``data/<name>/rules.json``.

    Class names are as Warcraft Logs reports them (an actor's ``subType``); ids are spell or aura ids.
    """

    name: str
    expansion: str
    data_dir: Path
    tank_classes: frozenset[str]
    healer_classes: frozenset[str]
    hybrid_classes: frozenset[str]
    always_ranged: frozenset[str]
    always_melee: frozenset[str]
    resource_spells: Mapping[int, str]
    class_resources: Mapping[str, int]
    heroism_ids: frozenset[int]

    def config_path(self, filename: str) -> Path:
        """A catalog of this ruleset, e.g. ``consumes_config.json``."""
        return self.data_dir / filename

    @classmethod
    def from_dir(cls, data_dir: Path, name: str | None = None) -> GameRules:
        """Read the ruleset in ``data_dir`` (its ``rules.json``); ``name`` defaults to the folder's name."""
        with (data_dir / "rules.json").open(encoding="utf-8") as f:
            raw: dict[str, Any] = json.load(f)
        classes: dict[str, list[str]] = raw.get("classes", {})
        return cls(
            name=name or data_dir.name,
            expansion=raw["expansion"],
            data_dir=data_dir,
            tank_classes=frozenset(classes.get("tank", ())),
            healer_classes=frozenset(classes.get("healer", ())),
            hybrid_classes=frozenset(classes.get("hybrid", ())),
            always_ranged=frozenset(classes.get("always_ranged", ())),
            always_melee=frozenset(classes.get("always_melee", ())),
            resource_spells=_by_id(raw.get("resource_spells", {})),
            class_resources=dict(raw.get("class_resources", {})),
            heroism_ids=frozenset(int(i) for i in raw.get("heroism_ids", ())),
        )


def _by_id(table: Mapping[str, str]) -> dict[int, str]:
    return {int(spell_id): name for spell_id, name in table.items()}


@cache
def load_ruleset(name: str = DEFAULT_RULESET) -> GameRules:
    """The bundled ruleset called ``name`` (a folder under ``wcl_core/data``)."""
    return GameRules.from_dir(paths.get_ruleset_dir(name), name)


def default_rules() -> GameRules:
    """The ruleset used when nothing says which expansion a raid belongs to."""
    return load_ruleset(DEFAULT_RULESET)


def rules_for(expansion: str | None) -> GameRules:
    """The ruleset for a raid of ``expansion``; the default one when it has none of its own or is unknown."""
    return load_ruleset(RULESETS.get(expansion or "", DEFAULT_RULESET))
