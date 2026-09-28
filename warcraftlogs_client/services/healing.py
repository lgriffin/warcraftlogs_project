"""Alias of `wcl_app.healing`, matching the other moved service modules so imports and patches reach it."""

import sys
from typing import TYPE_CHECKING

from wcl_app import healing as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.healing import HealingService as HealingService
    from wcl_app.healing import WeeklyHealing as WeeklyHealing

sys.modules[__name__] = _module
