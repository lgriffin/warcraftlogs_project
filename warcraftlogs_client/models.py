"""Moved to `wcl_core.models`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import models as _module

sys.modules[__name__] = _module
