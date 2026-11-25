"""Game rulesets: the per-expansion knowledge the analysis needs, kept out of the analysis code.

Classic, The Burning Crusade and Forever raids are analysed by the same code, but which classes can tank or heal,
which consumables, interrupts, debuffs, totems and cooldowns to look for, and which spell ids mean Heroism all
depend on the expansion. A ``GameRules`` holds that knowledge for one expansion. Its data lives in
``wcl_core/data/<ruleset>/``: ``rules.json`` for the class and spell tables, beside the ``*_config.json`` catalogs.

The ruleset is picked from a raid's **expansion** (``wcl_core.game_version``), not from the Warcraft Logs site,
because one site can host several eras: ``fresh`` went from Classic into The Burning Crusade, and a Karazhan log
needs TBC rules whichever site it came from.

Classic and The Burning Crusade have rulesets of their own. Forever's site has one too, picked before the expansion
because Forever reuses zone names from other eras; it extends Classic's until Forever logs show what differs.
Any other expansion (Wrath, say), or an unknown one, gets The Burning Crusade's, which is what the analysis always
did. Adding a ruleset is a new data folder plus an entry in ``RULESETS`` or ``GAME_VERSION_RULESETS``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from functools import cache
from pathlib import Path
from typing import Any

from . import paths
from .game_version import BURNING_CRUSADE, CLASSIC_ERA, FOREVER

TBC = "tbc"
CLASSIC = "classic"
FOREVER_RULES = "forever"

# Ruleset folder per expansion name (as ``wcl_core.game_version.EXPANSIONS`` spells it).
RULESETS: dict[str, str] = {
    CLASSIC_ERA: CLASSIC,
    BURNING_CRUSADE: TBC,
}

# Ruleset folder per game version whose site has rules of its own whatever its zones are called. Forever reuses
# zone names from other eras (its Hyjal Summit is a 20-player raid, not TBC's), so its site decides.
GAME_VERSION_RULESETS: dict[str, str] = {
    FOREVER: FOREVER_RULES,
}

# What an expansion without a ruleset of its own, or an unknown one, is analysed with.
DEFAULT_RULESET = paths.DEFAULT_RULESET


@dataclass(frozen=True)
class GameRules:
    """One ruleset, as read from ``data/<name>/rules.json``.

    Class names are as Warcraft Logs reports them (an actor's ``subType``); ids are spell or aura ids. A ruleset
    whose ``rules.json`` names another in ``extends`` starts from that one: it keeps every table it does not set,
    and a catalog missing from its folder is read from the one it extends.
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
    extends: GameRules | None = None

    def config_path(self, filename: str) -> Path:
        """A catalog of this ruleset, e.g. ``consumes_config.json``; the extended ruleset's when this one has none."""
        own = self.data_dir / filename
        if self.extends is not None and not own.exists():
            return self.extends.config_path(filename)
        return own

    @classmethod
    def from_dir(cls, data_dir: Path, name: str | None = None) -> GameRules:
        """Read the ruleset in ``data_dir`` (its ``rules.json``); ``name`` defaults to the folder's name."""
        with (data_dir / "rules.json").open(encoding="utf-8") as f:
            raw: dict[str, Any] = json.load(f)
        base = load_ruleset(raw["extends"]) if "extends" in raw else None
        values: dict[str, Any] = {f.name: getattr(base, f.name) for f in fields(cls)} if base else {}
        values.update(_tables(raw))
        values.update(name=name or data_dir.name, data_dir=data_dir, extends=base)
        return cls(**values)


_CLASS_ROLES = {
    "tank": "tank_classes",
    "healer": "healer_classes",
    "hybrid": "hybrid_classes",
    "always_ranged": "always_ranged",
    "always_melee": "always_melee",
}


def _tables(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The ``GameRules`` fields ``raw`` sets; a ruleset that extends none must set ``expansion``."""
    tables: dict[str, Any] = {}
    if "expansion" in raw:
        tables["expansion"] = raw["expansion"]
    for key, field_name in _CLASS_ROLES.items():
        if key in raw.get("classes", {}):
            tables[field_name] = frozenset(raw["classes"][key])
    if "resource_spells" in raw:
        tables["resource_spells"] = _by_id(raw["resource_spells"])
    if "class_resources" in raw:
        tables["class_resources"] = dict(raw["class_resources"])
    if "heroism_ids" in raw:
        tables["heroism_ids"] = frozenset(int(i) for i in raw["heroism_ids"])
    if "extends" not in raw:
        for field_name in (*_CLASS_ROLES.values(), "heroism_ids"):
            tables.setdefault(field_name, frozenset())
        tables.setdefault("resource_spells", {})
        tables.setdefault("class_resources", {})
    return tables


def _by_id(table: Mapping[str, str]) -> dict[int, str]:
    return {int(spell_id): name for spell_id, name in table.items()}


@cache
def load_ruleset(name: str = DEFAULT_RULESET) -> GameRules:
    """The bundled ruleset called ``name`` (a folder under ``wcl_core/data``)."""
    return GameRules.from_dir(paths.get_ruleset_dir(name), name)


def bundled_rulesets() -> tuple[str, ...]:
    """The name of every ruleset the expansions and sites map to, the default first."""
    return tuple(dict.fromkeys((DEFAULT_RULESET, *RULESETS.values(), *GAME_VERSION_RULESETS.values())))


def default_rules() -> GameRules:
    """The ruleset used when nothing says which expansion a raid belongs to."""
    return load_ruleset(DEFAULT_RULESET)


def rules_for(expansion: str | None, game_version: str | None = None) -> GameRules:
    """The ruleset for a raid of ``expansion`` on ``game_version``'s site.

    A site with rules of its own (``GAME_VERSION_RULESETS``) wins; otherwise the expansion picks, and one without
    a ruleset, or an unknown one, gets the default.
    """
    if game_version in GAME_VERSION_RULESETS:
        return load_ruleset(GAME_VERSION_RULESETS[game_version])
    return load_ruleset(RULESETS.get(expansion or "", DEFAULT_RULESET))
