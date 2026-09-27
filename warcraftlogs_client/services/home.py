"""Alias of `wcl_app.home`, matching the other moved service modules so imports and patches reach it."""

import sys
from typing import TYPE_CHECKING

from wcl_app import home as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.home import HomeLayout as HomeLayout
    from wcl_app.home import HomeService as HomeService
    from wcl_app.home import JsonLayoutStore as JsonLayoutStore

sys.modules[__name__] = _module
