"""Moved to `wcl_store.sqlite`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_store import sqlite as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_store.sqlite import PerformanceDB as PerformanceDB
    from wcl_store.sqlite import SQLiteStorageError as SQLiteStorageError

sys.modules[__name__] = _module
