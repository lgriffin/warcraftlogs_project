"""Moved to `wcl_core.client`; this alias keeps existing imports and patches working."""

import sys

from wcl_core import client as _module

sys.modules[__name__] = _module
