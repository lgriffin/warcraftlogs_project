"""Moved to `wcl_core.user_auth`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_core import user_auth as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_core.user_auth import UserTokenManager as UserTokenManager
    from wcl_core.user_auth import start_oauth_flow as start_oauth_flow

sys.modules[__name__] = _module
