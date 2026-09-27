"""
Application services: the one API the CLI, desktop app and web API share.

Frontends call these use cases and never touch ``WarcraftLogsClient``,
``PerformanceDB`` or SQL directly. This package depends only on wcl-core and
wcl-store and must stay free of Qt, sqlite3, argparse, web-framework and desktop
imports (enforced by ``lint-imports`` and ``tests/test_wcl_app_package.py``).
``warcraftlogs_client.services`` is an alias of this package.
"""

from wcl_app.context import AnalysisThresholds, AppContext, ProgressCallback, validate_report_code
from wcl_app.lineage import CharacterLineage, Spread, character_lineage
from wcl_app.player_page import AddResult, PlayerLog, PlayerPageData, PlayerPageService, PlayerRef, parse_report_code
from wcl_app.players import PlayerService
from wcl_app.raids import RaidService, ReferenceAuthRequired, ReportRef
from wcl_app.roles import ReanalysisResult, RoleOverrideService

__all__ = [
    "AddResult",
    "AnalysisThresholds",
    "AppContext",
    "CharacterLineage",
    "PlayerLog",
    "PlayerPageData",
    "PlayerPageService",
    "PlayerRef",
    "PlayerService",
    "ProgressCallback",
    "RaidService",
    "ReanalysisResult",
    "ReferenceAuthRequired",
    "ReportRef",
    "RoleOverrideService",
    "Spread",
    "character_lineage",
    "parse_report_code",
    "validate_report_code",
]
