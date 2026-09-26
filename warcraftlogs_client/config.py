"""Moved to `wcl_core.config`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import config as _module

sys.modules[__name__] = _module
