"""Moved to `wcl_core.auth`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import auth as _module

sys.modules[__name__] = _module
