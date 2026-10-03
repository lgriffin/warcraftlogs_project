"""
Character drill-downs for the desktop: the roster, one character's dossier and the numbers the compare view sets
side by side, all read under the active raid profile.

These reads are desktop-only queries on ``PerformanceDB`` (``AppContext.db()``), not part of ``RaidRepository``:
the Toads Hub builds its player pages from ``PlayerPageService`` instead. Every read follows the context's profile
at the moment it runs, so a view built before a profile switch picks the new profile up on its next load.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from wcl_core.models import CharacterHistory
from wcl_store import RaidScope

from wcl_app.context import AppContext

if TYPE_CHECKING:
    from wcl_store.sqlite import PerformanceDB

CONSUMABLE_SUMMARY_RAIDS = 5


@dataclass
class CharacterTrends:
    """Per-raid rows for a character's charts, newest first."""

    healer: list[dict[str, Any]] = field(default_factory=list)
    healer_spells: list[dict[str, Any]] = field(default_factory=list)
    tank: list[dict[str, Any]] = field(default_factory=list)
    dps: list[dict[str, Any]] = field(default_factory=list)
    dps_abilities: list[dict[str, Any]] = field(default_factory=list)
    consumables: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CharacterDossier:
    """Everything the character history view shows for one character."""

    history: CharacterHistory
    trends: CharacterTrends
    consumable_summary: list[dict[str, Any]] = field(default_factory=list)
    consistency: dict[str, Any] = field(default_factory=dict)
    compliance: dict[str, Any] = field(default_factory=dict)
    personal_bests: list[dict[str, Any]] = field(default_factory=list)
    spider: dict[str, Any] = field(default_factory=dict)
    calendar: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CharacterComparison:
    """One character's numbers in the compare view."""

    history: CharacterHistory
    trends: CharacterTrends
    consistency: dict[str, Any] = field(default_factory=dict)
    spider: dict[str, Any] = field(default_factory=dict)


class CharacterService:
    """Roster, dossier and comparison reads over the desktop database, scoped to ``ctx``'s active profile."""

    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    @property
    def scope(self) -> RaidScope | None:
        return self.ctx.scope

    def roster(self) -> list[CharacterHistory]:
        """Every character with a raid inside the profile (guild raids with none), by name."""
        with self.ctx.db() as db:
            return db.get_all_characters(self.scope)

    def dossier(self, name: str) -> CharacterDossier | None:
        """The character's history view, or None when they have no raid inside the profile."""
        scope = self.scope
        with self.ctx.db() as db:
            history = db.get_character_history(name, scope=scope)
            if history is None:
                return None
            return CharacterDossier(
                history=history,
                trends=self._trends(db, name, scope),
                consumable_summary=db.get_consumable_summary(name, limit=CONSUMABLE_SUMMARY_RAIDS, scope=scope),
                consistency=db.get_character_consistency(name, scope),
                compliance=db.get_character_consumable_compliance(name, scope),
                personal_bests=db.get_character_personal_bests(name, scope),
                spider=db.get_character_spider_data(name, scope),
                calendar=db.get_character_raid_calendar(name, scope),
            )

    def comparison(self, name: str) -> CharacterComparison | None:
        """The character's numbers for the compare view, or None when they have no raid inside the profile."""
        scope = self.scope
        with self.ctx.db() as db:
            history = db.get_character_history(name, scope=scope)
            if history is None:
                return None
            return CharacterComparison(
                history=history,
                trends=self._trends(db, name, scope),
                consistency=db.get_character_consistency(name, scope),
                spider=db.get_character_spider_data(name, scope),
            )

    @staticmethod
    def _trends(db: PerformanceDB, name: str, scope: RaidScope | None) -> CharacterTrends:
        """The chart rows; spell and ability rows are only read for a role the character played."""
        healer = db.get_healer_trend(name, scope=scope)
        dps = db.get_dps_trend(name, scope=scope)
        return CharacterTrends(
            healer=healer,
            healer_spells=db.get_healer_spell_trend(name, scope=scope) if healer else [],
            tank=db.get_tank_trend(name, scope=scope),
            dps=dps,
            dps_abilities=db.get_dps_ability_trend(name, scope=scope) if dps else [],
            consumables=db.get_consumable_trend(name, scope=scope),
        )
