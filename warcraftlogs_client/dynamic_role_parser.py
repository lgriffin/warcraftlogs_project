"""Moved to `wcl_core.dynamic_role_parser`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import dynamic_role_parser as _module

sys.modules[__name__] = _module
