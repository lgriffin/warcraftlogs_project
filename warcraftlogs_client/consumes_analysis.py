"""Moved to `wcl_core.consumes_analysis`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import consumes_analysis as _module

sys.modules[__name__] = _module
