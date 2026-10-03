"""The storage contract the application services are written against.

``RaidRepository`` holds exactly the operations ``warcraftlogs_client/services/`` calls. Both backends
implement it: ``wcl_store.sqlite.PerformanceDB`` (the desktop database) and
``wcl_store.postgres.PostgresRaidRepository`` (the Toads Hub). ``tests/test_store_contract.py`` runs the
same checks against each, so a method's behaviour, not just its signature, is the contract.

Every method commits its own work, and a failed write leaves nothing half-stored. Backends raise
``wcl_store.StorageError`` (never a driver exception) when the database itself fails. Character names are
matched case-insensitively. Dates are ``"YYYY-MM-DD HH:MM:SS"`` strings: ``raid_date`` is the report start in
the importing machine's local time (as the desktop app has always stored it); ``imported_at``,
``created_at`` and ``updated_at`` are UTC.

Reads that list or aggregate raids take ``scope`` (``wcl_store.RaidScope``): which sources, game versions,
expansions, zones and date window to see. ``None`` keeps the method's historic behaviour (its ``source`` or
``sources`` argument alone); a scope's ``sources`` replaces that argument.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .scope import RaidScope

if TYPE_CHECKING:
    from wcl_core.models import CharacterHistory, RaidAnalysis


@runtime_checkable
class RaidRepository(Protocol):
    # ── Raids ──

    def import_raid(self, analysis: RaidAnalysis, source: str = "guild") -> None:
        """Store a raid analysis, merging into the raid if it is already stored (its source is kept)."""
        ...

    def replace_raid_analysis(self, analysis: RaidAnalysis, source: str = "guild") -> None:
        """Swap a stored raid's per-player rows for ``analysis`` atomically, keeping its label and source."""
        ...

    def delete_raid(self, report_id: str) -> None:
        """Delete a raid and everything stored for it. Unknown codes are ignored."""
        ...

    def is_raid_imported(self, report_id: str) -> bool: ...

    def get_imported_report_codes(self) -> dict[str, str]:
        """``{report_id: imported_at}`` for every stored raid, of any source."""
        ...

    def count_raids(self, source: str = "guild", scope: RaidScope | None = None) -> int:
        """How many raids of ``source`` (``"guild"`` or ``"reference"``), or of ``scope``, are stored."""
        ...

    def get_raid_list(self, limit: int = 50, scope: RaidScope | None = None) -> list[dict[str, Any]]:
        """Guild raids (or ``scope``'s), newest ``raid_date`` first: report_id, title, owner, raid_date,
        imported_at, zone, game_version, expansion."""
        ...

    def get_raids_by_source(
        self, source: str = "guild", limit: int = 50, scope: RaidScope | None = None
    ) -> list[dict[str, Any]]:
        """Raids of ``source`` (or ``scope``), newest ``raid_date`` first: report_id, title, owner, raid_date,
        imported_at, zone, raid_size, label (None when unset), game_version and expansion."""
        ...

    def set_raid_era(self, report_id: str, game_version: str | None, expansion: str | None) -> None:
        """Record which site a stored raid is on and which expansion its zone belongs to. Unknown codes are
        ignored; None clears a value."""
        ...

    def get_raids_without_era(self) -> list[dict[str, Any]]:
        """Raids of any source missing ``game_version`` or ``expansion``, oldest first: report_id, zone,
        game_version, expansion."""
        ...

    def set_raid_label(self, report_id: str, label: str | None) -> None:
        """Label a stored raid, or clear its label with None or ``""``. Unknown codes are ignored."""

        ...

    def get_healing_by_raid(self, since: str, scope: RaidScope | None = None) -> list[dict[str, Any]]:
        """One row per healer per guild raid (or ``scope``'s) with ``raid_date >= since``, oldest raid first, then
        by name: report_id, raid_date, name, player_class, healing, overhealing. Raids without healers are not
        listed."""
        ...

    def get_raid_analysis(self, report_id: str) -> RaidAnalysis | None:
        """Rebuild the stored analysis (source ids are not stored and come back as 0)."""
        ...

    def get_raid_roster(self, report_id: str) -> list[dict[str, Any]]:
        """Players with a role row in the raid, by role then name: name, player_class, role."""
        ...

    def get_raid_source(self, report_id: str) -> str | None:
        """``"guild"`` or ``"reference"``, or None if the raid is not stored."""
        ...

    # ── Characters ──

    def get_character_history(
        self, character_name: str, source: str = "guild", scope: RaidScope | None = None
    ) -> CharacterHistory | None: ...

    def get_reports_for_character(self, character_name: str) -> list[dict[str, Any]]:
        """Raids of any source with a role row for the character, newest first:
        report_id, title, owner, zone, start_time, end_time, source."""
        ...

    def get_character_raid_roles(
        self, character_name: str, sources: tuple[str, ...] = ("guild",), scope: RaidScope | None = None
    ) -> list[dict[str, Any]]:
        """One row per raid and role, oldest first: raid_id, report_id, title, raid_date, zone, role, healing,
        overheal_percent, damage, damage_taken, mitigation_percent (None where the role has no such number)."""
        ...

    def get_character_spell_casts(
        self, character_name: str, sources: tuple[str, ...] = ("guild",), scope: RaidScope | None = None
    ) -> list[dict[str, Any]]:
        """Casts per spell per raid, in no set order: raid_id, role, spell_id, spell_name, casts."""
        ...

    def get_character_consumable_counts(
        self, character_name: str, sources: tuple[str, ...] = ("guild",), scope: RaidScope | None = None
    ) -> list[dict[str, Any]]:
        """Consumables per raid, in no set order: raid_id, consumable_name, count."""
        ...

    # ── Guild totals ──

    def get_raid_attendance(
        self, sources: tuple[str, ...] = ("guild",), scope: RaidScope | None = None
    ) -> list[dict[str, Any]]:
        """Raids each character has a role row in, by name: name, player_class, raids."""
        ...

    def get_consumable_totals(
        self, sources: tuple[str, ...] = ("guild",), scope: RaidScope | None = None
    ) -> list[dict[str, Any]]:
        """Consumables each character used across raids, by name then consumable: name, consumable_name,
        count (the sum) and raids (raids it was used in). Consumables never used are left out."""
        ...

    def get_consumable_raids(
        self, consumable_names: tuple[str, ...], sources: tuple[str, ...] = ("guild",), scope: RaidScope | None = None
    ) -> list[dict[str, Any]]:
        """Which raids each character used any of ``consumable_names`` in, in no set order: name, raid_id and
        consumable_name as stored. Names match ignoring ASCII case, like character names. Rows with a count of 0 are
        left out; no names means no rows."""
        ...

    # ── Player pages ──

    def get_or_create_player_page(self, name: str, server: str, region: str) -> int:
        """Id of the page for this character, created if needed. Matching ignores case."""
        ...

    def find_player_pages(self, name: str | None = None) -> list[dict[str, Any]]:
        """Pages by name then server: id, name, server, region, created_at, log_count (reports added)."""
        ...

    def set_player_page_log(
        self,
        page_id: int,
        report_id: str,
        status: str,
        title: str = "",
        zone: str | None = None,
        owner: str | None = None,
        start_time: int = 0,
    ) -> None:
        """Link a report to a page as ``"added"`` or ``"dismissed"``. Empty metadata keeps what is stored."""
        ...

    def remove_player_page_log(self, page_id: int, report_id: str) -> bool:
        """Unlink a report; True if it was linked."""
        ...

    def get_player_page_logs(self, page_id: int, status: str | None = None) -> list[dict[str, Any]]:
        """Linked reports, newest first: report_id, status, title, zone, owner, start_time, updated_at and
        imported (bool, whether the raid is stored)."""
        ...

    # ── Role overrides ──

    def set_role_override(self, character_name: str, role: str, report_id: str = "") -> None:
        """Pin a role for every raid (``report_id=""``) or one raid, replacing any existing override."""
        ...

    def clear_role_override(self, character_name: str, report_id: str = "") -> bool:
        """Remove an override; True if there was one."""
        ...

    def get_role_overrides(self, character_name: str | None = None) -> list[dict[str, Any]]:
        """Overrides by character then report: character_name, report_id, role, updated_at."""
        ...

    def get_role_overrides_for_report(self, report_id: str) -> dict[str, str]:
        """Effective ``{character_name: role}`` for one report; a raid-specific override wins."""
        ...

    def get_role_override_raids(self, character_name: str) -> set[str]:
        """Report codes of stored raids where an override moved the character off the detected role."""
        ...
