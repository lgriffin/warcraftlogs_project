"""Moved to `wcl_app`; this alias keeps existing imports and patches working.

The submodules are aliased here as well, so ``warcraftlogs_client.services.raids`` is ``wcl_app.raids`` itself
rather than a second copy loaded through ``wcl_app.__path__``.
"""

import importlib
import sys
from typing import TYPE_CHECKING

import wcl_app as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app import AddResult as AddResult
    from wcl_app import AnalysisThresholds as AnalysisThresholds
    from wcl_app import AppContext as AppContext
    from wcl_app import BadgeRules as BadgeRules
    from wcl_app import BadgeService as BadgeService
    from wcl_app import CharacterLineage as CharacterLineage
    from wcl_app import HomeLayout as HomeLayout
    from wcl_app import HomePage as HomePage
    from wcl_app import HomeService as HomeService
    from wcl_app import HomeWidget as HomeWidget
    from wcl_app import JsonLayoutStore as JsonLayoutStore
    from wcl_app import PlayerBadges as PlayerBadges
    from wcl_app import PlayerLog as PlayerLog
    from wcl_app import PlayerPageData as PlayerPageData
    from wcl_app import PlayerPageService as PlayerPageService
    from wcl_app import PlayerRef as PlayerRef
    from wcl_app import PlayerService as PlayerService
    from wcl_app import ProgressCallback as ProgressCallback
    from wcl_app import RaidService as RaidService
    from wcl_app import ReanalysisResult as ReanalysisResult
    from wcl_app import ReferenceAuthRequired as ReferenceAuthRequired
    from wcl_app import ReportRef as ReportRef
    from wcl_app import RoleOverrideService as RoleOverrideService
    from wcl_app import Spread as Spread
    from wcl_app import WidgetSpec as WidgetSpec
    from wcl_app import character_lineage as character_lineage
    from wcl_app import parse_report_code as parse_report_code
    from wcl_app import validate_report_code as validate_report_code

for _name in ("badges", "context", "home", "lineage", "player_page", "players", "raids", "roles"):
    sys.modules[f"{__name__}.{_name}"] = importlib.import_module(f"wcl_app.{_name}")
sys.modules[__name__] = _module
