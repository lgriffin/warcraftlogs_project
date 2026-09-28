"""Moved to `wcl_app.reference`; this alias keeps existing imports and patches working."""

import sys
from typing import TYPE_CHECKING

from wcl_app import reference as _module

if TYPE_CHECKING:  # the names callers import through this alias
    from wcl_app.reference import ReferenceComparison as ReferenceComparison
    from wcl_app.reference import ReferenceRequestError as ReferenceRequestError
    from wcl_app.reference import ReferenceService as ReferenceService
    from wcl_app.reference import StoredRaid as StoredRaid
    from wcl_app.reference import class_performance as class_performance
    from wcl_app.reference import consumable_summary as consumable_summary
    from wcl_app.reference import match_encounters as match_encounters
    from wcl_app.reference import scope_to_window as scope_to_window
    from wcl_app.reference import shared_encounter_window as shared_encounter_window

sys.modules[__name__] = _module
