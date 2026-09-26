"""Moved to `wcl_core.paths`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import paths as _module

sys.modules[__name__] = _module
