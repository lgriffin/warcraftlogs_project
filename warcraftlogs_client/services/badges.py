"""Alias of `wcl_app.badges`, matching the other moved service modules so imports and patches reach it."""

import sys
from typing import TYPE_CHECKING

from wcl_app import badges as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.badges import BadgeRules as BadgeRules
    from wcl_app.badges import BadgeService as BadgeService
    from wcl_app.badges import PlayerBadges as PlayerBadges

sys.modules[__name__] = _module
