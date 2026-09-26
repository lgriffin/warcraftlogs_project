"""
Raid use cases: analyse a report, store it, list and delete stored raids.

Every frontend (CLI, desktop, web API, bot) calls these instead of wiring
``analyze_raid`` and ``PerformanceDB`` by hand.
"""

from dataclasses import dataclass
from typing import Any

from ..analysis import analyze_raid
from ..models import RaidAnalysis
from .context import AppContext, ProgressCallback, validate_report_code


class ReferenceAuthRequired(Exception):
    """Raised when a reference analysis needs the user to sign in to Warcraft Logs first."""


@dataclass
class ReportRef:
    """A Warcraft Logs report and whether it is already stored locally."""

    code: str
    title: str
    start_time: int = 0
    zone_name: str = ""
    imported: bool = False


class RaidService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def analyze(
        self,
        report_id: str,
        *,
        reference: bool = False,
        progress: ProgressCallback | None = None,
    ) -> RaidAnalysis:
        """Fetch and analyse a report. ``reference`` uses the signed-in user's token."""
        report_id = validate_report_code(report_id)
        if reference:
            client = self.ctx.user_client()
            if client is None:
                raise ReferenceAuthRequired("Sign in to Warcraft Logs to analyse reference reports")
        else:
            client = self.ctx.wcl_client
        return analyze_raid(client, report_id, progress_callback=progress, **self.ctx.thresholds.as_kwargs())

    def save(self, analysis: RaidAnalysis, source: str = "guild") -> None:
        with self.ctx.db() as db:
            db.import_raid(analysis, source=source)

    def analyze_and_save(
        self,
        report_id: str,
        *,
        reference: bool = False,
        progress: ProgressCallback | None = None,
    ) -> RaidAnalysis:
        analysis = self.analyze(report_id, reference=reference, progress=progress)
        self.save(analysis, source="reference" if reference else "guild")
        return analysis

    def list_raids(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.ctx.db() as db:
            return db.get_raid_list(limit=limit)

    def get_raid(self, report_id: str) -> RaidAnalysis | None:
        with self.ctx.db() as db:
            return db.get_raid_analysis(report_id)

    def delete_raid(self, report_id: str) -> None:
        with self.ctx.db() as db:
            db.delete_raid(report_id)

    def guild_info(self, guild_id: int) -> dict[str, Any]:
        return self.ctx.wcl_client.get_guild_info(guild_id)

    def guild_reports(self, guild_id: int) -> list[dict[str, Any]]:
        """Raw guild report list from Warcraft Logs."""
        return self.ctx.wcl_client.get_guild_reports(guild_id)

    def imported_codes(self) -> set[str]:
        with self.ctx.db() as db:
            return set(db.get_imported_report_codes())

    def import_missing(
        self,
        codes: list[str],
        *,
        progress: ProgressCallback | None = None,
    ) -> list[str]:
        """Analyse and store every code not already in the database; return the codes imported."""
        already = self.imported_codes()
        normalized = list(dict.fromkeys(validate_report_code(c) for c in codes))
        todo = [c for c in normalized if c not in already]
        for i, code in enumerate(todo, 1):
            if progress:
                progress(f"Importing {code} ({i}/{len(todo)})...")
            self.analyze_and_save(code, progress=progress)
        return todo
