"""Moved to `wcl_core.common.data`; this alias keeps existing imports and patches working."""

import sys

from wcl_core.common import data as _module

sys.modules[__name__] = _module
