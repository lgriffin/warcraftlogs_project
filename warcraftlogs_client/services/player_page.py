"""Moved to `wcl_app.player_page`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_app import player_page as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.player_page import ADDED as ADDED
    from wcl_app.player_page import ALREADY_ON_PAGE as ALREADY_ON_PAGE
    from wcl_app.player_page import API_ERRORS as API_ERRORS
    from wcl_app.player_page import DISMISSED as DISMISSED
    from wcl_app.player_page import FAILED as FAILED
    from wcl_app.player_page import INVALID as INVALID
    from wcl_app.player_page import NEW as NEW
    from wcl_app.player_page import NOT_IN_REPORT as NOT_IN_REPORT
    from wcl_app.player_page import ON_PAGE as ON_PAGE
    from wcl_app.player_page import AddResult as AddResult
    from wcl_app.player_page import PlayerLog as PlayerLog
    from wcl_app.player_page import PlayerPageData as PlayerPageData
    from wcl_app.player_page import PlayerPageService as PlayerPageService
    from wcl_app.player_page import PlayerRef as PlayerRef
    from wcl_app.player_page import parse_report_code as parse_report_code
    from wcl_app.player_page import server_slug as server_slug

sys.modules[__name__] = _module
