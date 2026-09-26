"""
Application services: the one API the CLI, desktop app and web API share.

Frontends call these use cases and never touch ``WarcraftLogsClient``,
``PerformanceDB`` or SQL directly. This package must stay free of Qt,
argparse and web-framework imports (enforced by ``tests/test_services.py``).
"""

from .context import AnalysisThresholds, AppContext, ProgressCallback, validate_report_code
from .players import PlayerService
from .raids import RaidService, ReferenceAuthRequired, ReportRef

__all__ = [
    "AnalysisThresholds",
    "AppContext",
    "PlayerService",
    "ProgressCallback",
    "RaidService",
    "ReferenceAuthRequired",
    "ReportRef",
    "validate_report_code",
]
