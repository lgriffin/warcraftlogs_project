"""
Player use cases: find the logs a character appears in and add them to the database.

This is the contract the standalone player page builds on: discover a
character's reports on Warcraft Logs, mark which ones are already stored, and
import the rest so the character's history fills in.
"""

from ..models import CharacterHistory, CharacterProfile
from .context import AppContext, ProgressCallback
from .raids import RaidService, ReportRef


class PlayerService:
    def __init__(self, ctx: AppContext, raids: RaidService | None = None):
        self.ctx = ctx
        self.raids = raids or RaidService(ctx)

    def profile(self, name: str, server: str, region: str, api_url: str | None = None) -> CharacterProfile:
        """Character profile from Warcraft Logs, including recent reports and rankings."""
        return self.ctx.wcl_client.get_character_profile(name, server, region, api_url=api_url)

    def discover_reports(self, name: str, server: str, region: str, api_url: str | None = None) -> list[ReportRef]:
        """Reports the character appears in, each flagged with whether it is already imported."""
        profile = self.profile(name, server, region, api_url=api_url)
        imported = self.raids.imported_codes()
        return [
            ReportRef(
                code=r.code,
                title=r.title,
                start_time=r.start_time,
                zone_name=r.zone_name,
                imported=r.code in imported,
            )
            for r in profile.recent_reports
        ]

    def add_reports(self, codes: list[str], *, progress: ProgressCallback | None = None) -> list[str]:
        """Import the given reports (skipping ones already stored); return the codes imported."""
        return self.raids.import_missing(codes, progress=progress)

    def history(self, name: str) -> CharacterHistory | None:
        with self.ctx.db() as db:
            return db.get_character_history(name)
