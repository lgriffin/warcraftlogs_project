"""Moved to `wcl_core.cache`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import cache as _module

sys.modules[__name__] = _module
