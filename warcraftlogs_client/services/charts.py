"""Alias of `wcl_app.charts`, matching the other moved service modules so imports and patches reach it."""

import sys
from typing import TYPE_CHECKING

from wcl_app import charts as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.charts import Chart as Chart
    from wcl_app.charts import ChartError as ChartError

sys.modules[__name__] = _module
