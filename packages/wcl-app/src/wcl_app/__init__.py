"""
Application services: the one API the CLI, desktop app and web API share.

Frontends call these use cases and never touch ``WarcraftLogsClient``,
``PerformanceDB`` or SQL directly. This package depends only on wcl-core and
wcl-store and must stay free of Qt, sqlite3, argparse, web-framework and desktop
imports (enforced by ``lint-imports`` and ``tests/test_wcl_app_package.py``).
``warcraftlogs_client.services`` is an alias of this package.
"""

from wcl_app.badges import Badge, BadgeRule, BadgeRules, BadgeService, PlayerBadges
from wcl_app.bridge import (
    BridgeService,
    HubLinkedNotPublished,
    HubMemberMismatch,
    HubNotLinked,
    ProfileDirectory,
    ProfileNotPublished,
    member_profile,
)
from wcl_app.characters import CharacterComparison, CharacterDossier, CharacterService, CharacterTrends
from wcl_app.charts import Chart, ChartError, Series
from wcl_app.context import AnalysisThresholds, AppContext, ProgressCallback, validate_report_code
from wcl_app.healing import HealingService, WeeklyHealing
from wcl_app.home import HomeLayout, HomePage, HomeService, HomeWidget, JsonLayoutStore, WidgetSpec
from wcl_app.identity import DiscordNotConfigured, IdentityService
from wcl_app.lineage import CharacterLineage, Spread, character_lineage
from wcl_app.my_characters import MyCharacters, MyCharactersService
from wcl_app.player_page import AddResult, PlayerLog, PlayerPageData, PlayerPageService, PlayerRef, parse_report_code
from wcl_app.players import PlayerService
from wcl_app.profiles import JsonProfileStore, Profile, ProfileService, ProfileSet
from wcl_app.raids import ProfileSiteUnknown, RaidService, ReferenceAuthRequired, ReportRef
from wcl_app.reference import ReferenceComparison, ReferenceRequestError, ReferenceService, StoredRaid
from wcl_app.roles import ReanalysisResult, RoleOverrideService

__all__ = [
    "AddResult",
    "AnalysisThresholds",
    "AppContext",
    "Badge",
    "BadgeRule",
    "BadgeRules",
    "BadgeService",
    "BridgeService",
    "CharacterComparison",
    "CharacterDossier",
    "CharacterLineage",
    "CharacterService",
    "CharacterTrends",
    "Chart",
    "ChartError",
    "DiscordNotConfigured",
    "HealingService",
    "HomeLayout",
    "HomePage",
    "HomeService",
    "HomeWidget",
    "HubLinkedNotPublished",
    "HubMemberMismatch",
    "HubNotLinked",
    "IdentityService",
    "JsonLayoutStore",
    "JsonProfileStore",
    "MyCharacters",
    "MyCharactersService",
    "PlayerBadges",
    "PlayerLog",
    "PlayerPageData",
    "PlayerPageService",
    "PlayerRef",
    "PlayerService",
    "Profile",
    "ProfileDirectory",
    "ProfileNotPublished",
    "ProfileService",
    "ProfileSet",
    "ProfileSiteUnknown",
    "ProgressCallback",
    "RaidService",
    "ReanalysisResult",
    "ReferenceAuthRequired",
    "ReferenceComparison",
    "ReferenceRequestError",
    "ReferenceService",
    "ReportRef",
    "RoleOverrideService",
    "Series",
    "Spread",
    "StoredRaid",
    "WeeklyHealing",
    "WidgetSpec",
    "character_lineage",
    "member_profile",
    "parse_report_code",
    "validate_report_code",
]
