"""Moved to `wcl_app.lineage`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_app import lineage as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.lineage import CharacterLineage as CharacterLineage
    from wcl_app.lineage import Spread as Spread
    from wcl_app.lineage import character_lineage as character_lineage

sys.modules[__name__] = _module
