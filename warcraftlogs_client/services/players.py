"""Moved to `wcl_app.players`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_app import players as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.players import PlayerService as PlayerService

sys.modules[__name__] = _module
