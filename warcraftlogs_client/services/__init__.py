"""
Application services: the one API the CLI, desktop app and web API share.

Frontends call these use cases and never touch ``WarcraftLogsClient``,
``PerformanceDB`` or SQL directly. This package must stay free of Qt,
argparse and web-framework imports (enforced by ``tests/test_services.py``).
"""

from .context import AnalysisThresholds, AppContext, ProgressCallback, validate_report_code
from .lineage import CharacterLineage, Spread, character_lineage
from .player_page import AddResult, PlayerLog, PlayerPageData, PlayerPageService, PlayerRef, parse_report_code
from .players import PlayerService
from .raids import RaidService, ReferenceAuthRequired, ReportRef
from .roles import ReanalysisResult, RoleOverrideService

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
