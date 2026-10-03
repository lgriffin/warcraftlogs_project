"""
Player page: one character's own collection of Warcraft Logs reports.

A player looks themselves up (name, server, region), discovers the reports
Warcraft Logs has them in plus any already imported locally, and adds the ones
they want to their page. Adding a report imports its analysis into the local
database (if it isn't there yet) so the existing history and trend queries
cover it, and links it to the page. Reports can also be added by URL or code,
in which case the player's presence in the report is checked first.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import requests
from wcl_core.common.errors import WarcraftLogsError
from wcl_store import RaidScope

from wcl_app.badges import BadgeRules, PlayerBadges, character_stats
from wcl_app.context import AnalysisThresholds, AppContext, ScopeSource, resolve_scope, validate_report_code
from wcl_app.lineage import CharacterLineage, character_lineage

if TYPE_CHECKING:
    from wcl_core.client import WarcraftLogsClient
    from wcl_core.models import CharacterHistory, RaidAnalysis
    from wcl_store import RaidRepository

logger = logging.getLogger(__name__)

_REPORT_URL_RE = re.compile(r"warcraftlogs\.com/reports/([A-Za-z0-9]{16})(?:[/?#]|$)")
# Realm names contain letters, spaces, apostrophes and hyphens; WCL slugs drop
# apostrophes and join words with hyphens ("Pyrewood Village" -> "pyrewood-village").
_SLUG_STRIP_RE = re.compile(r"['\u2019]")
_SLUG_SPACE_RE = re.compile(r"\s+")
_NAME_FORBIDDEN_RE = re.compile(r"[\s\"\\{}()\[\]<>:;,/]")

API_ERRORS = (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError)

# Outcomes of add_reports(), shared by every frontend.
ADDED = "added"
ALREADY_ON_PAGE = "already_on_page"
INVALID = "invalid"
NOT_IN_REPORT = "not_in_report"
FAILED = "failed"

# Discovery statuses.
NEW = "new"
ON_PAGE = "on_page"
DISMISSED = "dismissed"


def parse_report_code(text: str) -> str | None:
    """Pull a 16-character report code out of a bare code or a Warcraft Logs report URL."""
    text = (text or "").strip()
    try:
        return validate_report_code(text)
    except ValueError:
        pass
    match = _REPORT_URL_RE.search(text)
    return match.group(1) if match else None


def server_slug(server: str) -> str:
    return _SLUG_SPACE_RE.sub("-", _SLUG_STRIP_RE.sub("", server.strip())).lower()


@dataclass(frozen=True)
class PlayerRef:
    """Identifies one character. Build with ``PlayerRef.create`` to normalise input."""

    name: str
    server: str
    region: str

    @classmethod
    def create(cls, name: str, server: str, region: str) -> PlayerRef:
        name = (name or "").strip()
        server = server_slug(server or "")
        region = (region or "").strip().lower()
        if not name or _NAME_FORBIDDEN_RE.search(name) or len(name) > 24:
            raise ValueError(f"'{name}' is not a valid character name")
        if not server:
            raise ValueError("A server is required")
        if not region.isalpha() or len(region) > 4:
            raise ValueError(f"'{region}' is not a valid region (e.g. eu, us)")
        # WoW names are stored capitalised; match that so the page lines up with imported rows.
        return cls(name=name[0].upper() + name[1:].lower(), server=server, region=region)

    @property
    def label(self) -> str:
        return f"{self.name}-{self.server} ({self.region.upper()})"


@dataclass
class PlayerLog:
    """A report as shown on a player page or in discovery results."""

    code: str
    title: str
    start_time: int = 0
    zone: str = ""
    owner: str = ""
    guild: str = ""
    status: str = NEW
    imported: bool = False
    source: str = "wcl"  # where discovery found it: "wcl", "local" or "both"

    @property
    def date(self) -> datetime | None:
        return datetime.fromtimestamp(self.start_time / 1000) if self.start_time else None

    @property
    def date_formatted(self) -> str:
        return self.date.strftime("%Y-%m-%d") if self.date else ""

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "date": self.date_formatted}


@dataclass
class AddResult:
    code: str
    outcome: str
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in (ADDED, ALREADY_ON_PAGE)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlayerPageData:
    player: PlayerRef
    logs: list[PlayerLog] = field(default_factory=list)
    history: dict[str, Any] | None = None
    lineage: CharacterLineage | None = None
    role_overrides: list[dict] = field(default_factory=list)
    badges: PlayerBadges | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player": asdict(self.player),
            "logs": [log.to_dict() for log in self.logs],
            "history": self.history,
            "lineage": self.lineage.to_dict() if self.lineage else None,
            "role_overrides": self.role_overrides,
            "badges": self.badges.to_dict() if self.badges else None,
        }


AnalyzeFn = Callable[[str], "RaidAnalysis"]


class PlayerPageService:
    """Discover and collect the reports a player is in.

    ``client`` is only needed for discovery and for adding reports that are not
    yet imported. Frontends build it with ``from_context`` so ``analyze`` is
    ``RaidService.analyze`` with the configured role thresholds.
    """

    def __init__(
        self,
        db: RaidRepository,
        client: WarcraftLogsClient | None = None,
        analyze: AnalyzeFn | None = None,
        import_source: str = "guild",
        badge_rules: BadgeRules | None = None,
        scope: ScopeSource = None,
    ):
        self.db = db
        self.client = client
        self._analyze = analyze
        self.import_source = import_source
        self.badge_rules = badge_rules if badge_rules is not None else BadgeRules()
        # A scope, or a callable giving the active profile's at read time, for the page's badges and lineage;
        # None counts every guild raid.
        self._scope = scope

    @property
    def scope(self) -> RaidScope | None:
        return resolve_scope(self._scope)

    @classmethod
    def from_context(cls, ctx: AppContext, db: RaidRepository, *, with_api: bool = True) -> PlayerPageService:
        """Wire the service from the shared AppContext: its WCL client and RaidService's analyze.

        ``db`` is the handle from ``ctx.repository()``; the caller owns its lifetime. ``with_api=False``
        gives a local-only service that never builds a WCL client (no credentials needed).
        """
        rules = BadgeRules.from_config(ctx.config)
        if not with_api:
            return cls(db, badge_rules=rules, scope=lambda: ctx.scope)
        from wcl_app.raids import RaidService

        return cls(db, ctx.wcl_client, analyze=RaidService(ctx).analyze, badge_rules=rules, scope=lambda: ctx.scope)

    # ── Pages ──

    def open_page(self, player: PlayerRef) -> int:
        return self.db.get_or_create_player_page(player.name, player.server, player.region)

    def list_pages(self, name: str | None = None) -> list[dict]:
        return self.db.find_player_pages(name)

    def get_page(self, player: PlayerRef) -> PlayerPageData:
        page_id = self.open_page(player)
        logs = [self._row_to_log(r) for r in self.db.get_player_page_logs(page_id, status="added")]
        history = self.db.get_character_history(player.name, scope=self.scope)
        badges = self.badge_rules.award(character_stats(self.db, player.name, scope=self.scope))
        badges.player_class = history.player_class if history else ""
        return PlayerPageData(
            player=player,
            logs=logs,
            history=_history_summary(history) if history else None,
            lineage=character_lineage(self.db, player.name, scope=self.scope),
            role_overrides=self.db.get_role_overrides(player.name),
            badges=badges,
        )

    # ── Discovery ──

    def discover_reports(self, player: PlayerRef, limit: int = 50, include_local: bool = True) -> list[PlayerLog]:
        """Reports the player appears in, newest first, each tagged new / on_page / dismissed.

        Combines Warcraft Logs' record of the character's reports with raids already
        in the local database that have a row for this character.
        """
        page_id = self.open_page(player)
        linked = {r["report_id"]: r["status"] for r in self.db.get_player_page_logs(page_id)}
        imported = self.db.get_imported_report_codes()

        found: dict[str, PlayerLog] = {}
        if self.client is not None:
            for r in self._fetch_character_reports(player, limit):
                found[r["code"]] = PlayerLog(
                    code=r["code"],
                    title=r["title"],
                    start_time=r["start_time"],
                    zone=r["zone"],
                    owner=r["owner"],
                    guild=r["guild"],
                    source="wcl",
                )
        if include_local:
            for r in self.db.get_reports_for_character(player.name):
                code = r["report_id"]
                if code in found:
                    found[code].source = "both"
                    continue
                found[code] = PlayerLog(
                    code=code,
                    title=r["title"],
                    start_time=r["start_time"] or 0,
                    zone=r["zone"] or "",
                    owner=r["owner"] or "",
                    source="local",
                )

        for code, log in found.items():
            log.imported = code in imported
            log.status = {"added": ON_PAGE, "dismissed": DISMISSED}.get(linked.get(code, ""), NEW)

        return sorted(found.values(), key=lambda log: log.start_time, reverse=True)

    def _fetch_character_reports(self, player: PlayerRef, limit: int) -> list[dict]:
        assert self.client is not None
        reports: list[dict] = []
        page = 1
        per_page = max(1, min(limit, 100))
        while len(reports) < limit:
            batch, has_more = self.client.get_character_reports(
                player.name, player.server, player.region, limit=per_page, page=page
            )
            reports.extend(batch)
            if not has_more or not batch:
                break
            page += 1
        return reports[:limit]

    # ── Adding and removing ──

    def add_reports(
        self,
        player: PlayerRef,
        refs: list[str],
        verify: bool = True,
        known: dict[str, PlayerLog] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> list[AddResult]:
        """Add reports (codes or URLs) to the player's page, importing any not yet analysed.

        ``known`` passes discovery results through so their metadata is kept and
        the participation check is skipped (Warcraft Logs already listed the player).
        With ``verify`` on, other reports are checked for the player before import.
        """
        page_id = self.open_page(player)
        on_page = {r["report_id"] for r in self.db.get_player_page_logs(page_id, status="added")}
        known = known or {}
        results: list[AddResult] = []
        seen: set[str] = set()

        for ref in refs:
            code = parse_report_code(ref)
            if code is None:
                results.append(AddResult(ref, INVALID, "Not a Warcraft Logs report code or URL"))
                continue
            if code in seen:
                continue
            seen.add(code)
            if code in on_page:
                results.append(AddResult(code, ALREADY_ON_PAGE, "Already on the page"))
                continue
            if progress:
                progress(f"Adding {code}...")
            results.append(self._add_one(player, page_id, code, known.get(code), verify))
        return results

    def _add_one(self, player: PlayerRef, page_id: int, code: str, known: PlayerLog | None, verify: bool) -> AddResult:
        imported = self.db.is_raid_imported(code)
        try:
            if verify and known is None and not self._player_in_report(player, code, imported):
                return AddResult(code, NOT_IN_REPORT, f"{player.name} is not in this report")

            meta = known
            if not imported:
                analysis = self._run_analysis(code)
                self.db.import_raid(analysis, source=self.import_source)
                md = analysis.metadata
                meta = meta or PlayerLog(
                    code=code, title=md.title, start_time=md.start_time, zone=md.zone or "", owner=md.owner
                )
        except API_ERRORS as e:
            logger.warning("Failed to add %s to %s: %s", code, player.label, e)
            return AddResult(code, FAILED, str(e))

        if meta is None:
            meta = self._local_metadata(code)
        self.db.set_player_page_log(
            page_id,
            code,
            "added",
            title=meta.title if meta else "",
            zone=(meta.zone or None) if meta else None,
            owner=(meta.owner or None) if meta else None,
            start_time=meta.start_time if meta else 0,
        )
        return AddResult(code, ADDED, "Imported and added" if not imported else "Added")

    def _player_in_report(self, player: PlayerRef, code: str, imported: bool) -> bool:
        if imported and any(r["name"].lower() == player.name.lower() for r in self.db.get_raid_roster(code)):
            return True
        if self.client is None:
            # Without API access, an imported report's roster is the only evidence available.
            return False
        actors = self.client.get_all_actors(code)
        return any(a.get("type") == "Player" and (a.get("name") or "").lower() == player.name.lower() for a in actors)

    def _local_metadata(self, code: str) -> PlayerLog | None:
        analysis = self.db.get_raid_analysis(code)
        if analysis is None:
            return None
        md = analysis.metadata
        return PlayerLog(code=code, title=md.title, start_time=md.start_time, zone=md.zone or "", owner=md.owner)

    def _run_analysis(self, code: str) -> RaidAnalysis:
        if self._analyze is not None:
            return self._analyze(code)
        if self.client is None:
            raise WarcraftLogsError("Warcraft Logs API access is needed to import new reports")
        from wcl_core.analysis import analyze_raid

        overrides = self.db.get_role_overrides_for_report(code) or None
        return analyze_raid(self.client, code, role_overrides=overrides, **AnalysisThresholds().as_kwargs())

    def dismiss(self, player: PlayerRef, codes: list[str]) -> int:
        """Hide reports from future discovery results without importing them."""
        page_id = self.open_page(player)
        count = 0
        for ref in codes:
            code = parse_report_code(ref)
            if code:
                self.db.set_player_page_log(page_id, code, "dismissed")
                count += 1
        return count

    def remove(self, player: PlayerRef, codes: list[str]) -> int:
        """Unlink reports from the page. Imported raid data is kept; it is guild history."""
        page_id = self.open_page(player)
        return sum(self.db.remove_player_page_log(page_id, c) for c in (parse_report_code(r) for r in codes) if c)

    @staticmethod
    def _row_to_log(row: dict) -> PlayerLog:
        return PlayerLog(
            code=row["report_id"],
            title=row["title"],
            start_time=row["start_time"] or 0,
            zone=row["zone"] or "",
            owner=row["owner"] or "",
            status=ON_PAGE if row["status"] == "added" else DISMISSED,
            imported=row["imported"],
            source="page",
        )


def _history_summary(history: CharacterHistory) -> dict[str, Any]:
    return {
        "player_class": history.player_class,
        "total_raids": history.total_raids,
        "first_seen": history.first_seen.strftime("%Y-%m-%d") if history.first_seen else None,
        "last_seen": history.last_seen.strftime("%Y-%m-%d") if history.last_seen else None,
        "avg_healing": history.avg_healing,
        "avg_damage": history.avg_damage,
        "avg_mitigation_percent": history.avg_mitigation_percent,
    }
