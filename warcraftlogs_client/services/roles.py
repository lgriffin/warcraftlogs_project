"""
Role overrides: let a player correct the role the analyzer guessed for them.

Roles are guessed per raid from healing done and damage taken, which gets
off-spec nights and low-healing fights wrong. An override pins a character to
healer, tank, melee, ranged or dps, either for every raid or for one report.
Analysis reads overrides through ``RaidService.analyze``; setting one here can
also re-analyse the already-imported raids it changes, because role decides
which metrics are collected at all (a healer row has healing, a dps row has
damage), so relabelling stored rows would not be enough.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from ..analysis import OVERRIDE_ROLES
from .context import AppContext, ProgressCallback, validate_report_code
from .player_page import API_ERRORS

if TYPE_CHECKING:
    from ..database import PerformanceDB
    from ..models import RaidAnalysis

logger = logging.getLogger(__name__)

# Called as analyze(report_id, reference=...), matching RaidService.analyze.
AnalyzeFn = Callable[..., "RaidAnalysis"]


@dataclass
class ReanalysisResult:
    report_id: str
    old_role: str
    ok: bool
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def role_matches(stored: str, wanted: str) -> bool:
    return stored == wanted or (wanted == "dps" and stored in ("melee", "ranged"))


class RoleOverrideService:
    def __init__(self, db: PerformanceDB, analyze: AnalyzeFn | None = None):
        self.db = db
        self._analyze = analyze

    @classmethod
    def from_context(cls, ctx: AppContext, db: PerformanceDB, *, with_api: bool = True) -> RoleOverrideService:
        if not with_api:
            return cls(db)
        from .raids import RaidService

        return cls(db, analyze=RaidService(ctx).analyze)

    def list_overrides(self, character_name: str | None = None) -> list[dict]:
        return self.db.get_role_overrides(character_name)

    def set(
        self,
        character_name: str,
        role: str,
        report_id: str | None = None,
        *,
        reanalyze: bool = True,
        progress: ProgressCallback | None = None,
    ) -> list[ReanalysisResult]:
        """Pin a character's role, then re-analyse imported raids where the stored role disagrees."""
        role = role.strip().lower()
        if role not in OVERRIDE_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(OVERRIDE_ROLES)}")
        name = _clean_name(character_name)
        code = validate_report_code(report_id) if report_id else ""
        self.db.set_role_override(name, role, code)
        if not reanalyze:
            return []
        stale = [
            r
            for r in self._raids_in_scope(name, code)
            if not role_matches(r["role"], self._effective_role(name, r["report_id"]))
        ]
        return self._reanalyze(stale, progress)

    def clear(
        self,
        character_name: str,
        report_id: str | None = None,
        *,
        reanalyze: bool = True,
        progress: ProgressCallback | None = None,
    ) -> list[ReanalysisResult]:
        """Remove an override and let the analyzer guess again for the raids it covered."""
        name = _clean_name(character_name)
        code = validate_report_code(report_id) if report_id else ""
        old = {o["report_id"]: o["role"] for o in self.db.get_role_overrides(name)}.get(code)
        if old is None or not self.db.clear_role_override(name, code):
            return []
        if not reanalyze:
            return []
        # Re-guess raids this override actually moved the character in, plus any where a
        # remaining override (character-wide, after a raid-specific clear) now disagrees.
        moved = self.db.get_role_override_raids(name)
        affected = []
        for r in self._raids_in_scope(name, code):
            now = self._effective_role(name, r["report_id"])
            if r["report_id"] in moved or (now and not role_matches(r["role"], now)):
                affected.append(r)
        return self._reanalyze(affected, progress)

    def _effective_role(self, name: str, report_id: str) -> str:
        overrides = {k.lower(): v for k, v in self.db.get_role_overrides_for_report(report_id).items()}
        return overrides.get(name.lower(), "")

    def _raids_in_scope(self, name: str, code: str) -> list[dict]:
        rows = self.db.get_character_raid_roles(name, sources=("guild", "reference"))
        if code:
            rows = [r for r in rows if r["report_id"] == code]
        elif any(o["report_id"] for o in self.db.get_role_overrides(name)):
            # Raids with their own override keep it; the character-wide change doesn't touch them.
            own = {o["report_id"] for o in self.db.get_role_overrides(name) if o["report_id"]}
            rows = [r for r in rows if r["report_id"] not in own]
        return rows

    def _reanalyze(self, raids: list[dict], progress: ProgressCallback | None) -> list[ReanalysisResult]:
        results: list[ReanalysisResult] = []
        if raids and self._analyze is None:
            return [
                ReanalysisResult(r["report_id"], r["role"], False, "Needs Warcraft Logs access to re-analyse")
                for r in raids
            ]
        for i, raid in enumerate(raids, 1):
            code = raid["report_id"]
            if progress:
                progress(f"Re-analysing {code} ({i}/{len(raids)})...")
            source = self.db.get_raid_source(code) or "guild"
            try:
                assert self._analyze is not None
                analysis = self._analyze(code, reference=source == "reference")
                # Replace, don't merge: the character's old-role rows must go. Atomic, and
                # keeps the raid's label and source.
                self.db.replace_raid_analysis(analysis, source=source)
            except (*API_ERRORS, sqlite3.Error) as e:
                logger.warning("Re-analysis of %s failed: %s", code, e)
                results.append(ReanalysisResult(code, raid["role"], False, str(e)))
                continue
            results.append(ReanalysisResult(code, raid["role"], True, "Re-analysed"))
        return results


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("A character name is required")
    return name
