"""Moved to `wcl_app.context`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_app import context as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.context import AnalysisThresholds as AnalysisThresholds
    from wcl_app.context import AppContext as AppContext
    from wcl_app.context import ProgressCallback as ProgressCallback
    from wcl_app.context import StorageFactory as StorageFactory
    from wcl_app.context import validate_report_code as validate_report_code

sys.modules[__name__] = _module
