"""Moved to `wcl_app.raids`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_app import raids as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.raids import RaidService as RaidService
    from wcl_app.raids import ReferenceAuthRequired as ReferenceAuthRequired
    from wcl_app.raids import ReportRef as ReportRef

sys.modules[__name__] = _module
