"""Moved to `wcl_core.analysis`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import analysis as _module

sys.modules[__name__] = _module
