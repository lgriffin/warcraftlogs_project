"""Moved to `wcl_core.spell_manager`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import spell_manager as _module

sys.modules[__name__] = _module
