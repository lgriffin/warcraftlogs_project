"""Moved to `wcl_app.roles`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_app import roles as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.roles import ReanalysisResult as ReanalysisResult
    from wcl_app.roles import RoleOverrideService as RoleOverrideService
    from wcl_app.roles import role_matches as role_matches

sys.modules[__name__] = _module
