"""Moved to `wcl_core.common.errors`; this alias keeps existing imports and patches working."""

import sys

from wcl_core.common import errors as _module

sys.modules[__name__] = _module
