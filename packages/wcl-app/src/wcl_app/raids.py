"""
Raid use cases: analyse a report, store it, list and delete stored raids.

Every frontend (CLI, desktop, web API, bot) calls these instead of wiring
``analyze_raid`` and ``PerformanceDB`` by hand.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from wcl_core.analysis import analyze_raid
from wcl_core.models import RaidAnalysis

from wcl_app.context import AppContext, ProgressCallback, validate_report_code


class ReferenceAuthRequired(Exception):
    """Raised when a reference analysis needs the user to sign in to Warcraft Logs first."""


class ProfileSiteUnknown(ValueError):
    """Raised when the active profile's game version is not the site the client imports from.

    Each imported raid is tagged with the client's site, so importing a Forever profile through the Anniversary
    host would file its raids under ``fresh``, outside the profile. The profile needs its own API URL first.
    """


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
        """Fetch and analyse a report. ``reference`` uses the signed-in user's token.

        A guild report under a profile needs the client on the profile's site (``check_profile_site``), so the
        raid it stores is tagged into the profile.
        """
        report_id = validate_report_code(report_id)
        if reference:
            client = self.ctx.user_client()
            if client is None:
                raise ReferenceAuthRequired("Sign in to Warcraft Logs to analyse reference reports")
        else:
            self.check_profile_site()
            client = self.ctx.wcl_client
        with self.ctx.repository() as db:
            overrides = db.get_role_overrides_for_report(report_id)
        return analyze_raid(
            client,
            report_id,
            progress_callback=progress,
            role_overrides=overrides or None,
            **self.ctx.thresholds.as_kwargs(),
        )

    def save(self, analysis: RaidAnalysis, source: str = "guild") -> None:
        with self.ctx.repository() as db:
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
        """Guild raids within the active profile, newest first."""
        with self.ctx.repository() as db:
            return db.get_raid_list(limit=limit, scope=self.ctx.scope)

    def count_raids(self) -> int:
        with self.ctx.repository() as db:
            return db.count_raids("guild", scope=self.ctx.scope)

    def get_raid(self, report_id: str) -> RaidAnalysis | None:
        with self.ctx.repository() as db:
            return db.get_raid_analysis(report_id)

    def delete_raid(self, report_id: str) -> None:
        with self.ctx.repository() as db:
            db.delete_raid(report_id)

    def guild_info(self, guild_id: int | None = None) -> dict[str, Any]:
        return self.ctx.wcl_client.get_guild_info(self._guild(guild_id))

    def guild_reports(self, guild_id: int | None = None) -> list[dict[str, Any]]:
        """The guild's reports on Warcraft Logs, for the active profile's guild unless one is given.

        Under a profile only the reports of its era come back (``RaidScope.admits``, the rule its raid list
        uses), so importing them all imports nothing the profile would not show. The client pages past newer
        reports from other eras to find them.
        """
        guild = self._guild(guild_id)
        scope = self.ctx.scope
        if scope is None:
            return self.ctx.wcl_client.get_guild_reports(guild)
        self.check_profile_site()

        def inside(r: dict[str, Any]) -> bool:
            return scope.admits(
                game_version=r.get("game_version"),
                expansion=r.get("expansion"),
                zone=r.get("zone"),
                raid_date=_raid_date(r.get("start_time")),
            )

        return self.ctx.wcl_client.get_guild_reports(guild, keep=inside)

    def new_guild_reports(self, guild_id: int | None = None) -> list[dict[str, Any]]:
        """``guild_reports`` not stored yet, newest first as Warcraft Logs lists them."""
        already = self.imported_codes()
        return [r for r in self.guild_reports(guild_id) if r["code"] not in already]

    def import_new(self, guild_id: int | None = None, *, progress: ProgressCallback | None = None) -> list[str]:
        """Import the guild's reports that are not stored yet, only the active profile's era; return the codes."""
        return self.import_missing([r["code"] for r in self.new_guild_reports(guild_id)], progress=progress)

    def check_profile_site(self) -> None:
        """Raise ``ProfileSiteUnknown`` when the active profile names a game version the client is not on."""
        profile = self.ctx.profile
        if profile is None or profile.game_version is None:
            return
        site = self.ctx.wcl_client.game_version
        if site != profile.game_version:
            raise ProfileSiteUnknown(
                f"The {profile.name} profile is {profile.game_version}, but imports would come from the {site} "
                f"site. Give the profile the API URL of the {profile.game_version} site first."
            )

    def _guild(self, guild_id: int | None) -> int:
        resolved = guild_id if guild_id is not None else self.ctx.guild_id
        if resolved is None:
            raise ValueError("No guild: set guild_id in config.json or on the active profile")
        return resolved

    def imported_codes(self) -> set[str]:
        with self.ctx.repository() as db:
            return set(db.get_imported_report_codes())

    def import_missing(
        self,
        codes: list[str],
        *,
        progress: ProgressCallback | None = None,
    ) -> list[str]:
        """Analyse and store every code not already in the database; return the codes imported.

        Under a profile the client must be on the profile's site (``check_profile_site``), so every raid imported
        is tagged into the profile and listed by it without a backfill.
        """
        self.check_profile_site()
        already = self.imported_codes()
        normalized = list(dict.fromkeys(validate_report_code(c) for c in codes))
        todo = [c for c in normalized if c not in already]
        for i, code in enumerate(todo, 1):
            if progress:
                progress(f"Importing {code} ({i}/{len(todo)})...")
            self.analyze_and_save(code, progress=progress)
        return todo


def _raid_date(start_ms: Any) -> str | None:
    """A report's start time in milliseconds as the stored ``raid_date`` string, like ``RaidMetadata.date``."""
    if not start_ms:
        return None
    return datetime.fromtimestamp(int(start_ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
