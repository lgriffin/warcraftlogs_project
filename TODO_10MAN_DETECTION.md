# 10-Man Detection Follow-up

## Problem
Zone-based 10-man detection (`metadata.zone in {"Karazhan", "Zul'Aman"}`) is not working as expected — characters are still being classified as healers in Karazhan runs using 25-man thresholds.

## Investigation Needed
- Check what value `metadata.zone` actually contains at runtime (print/log it during a Kara analysis)
- The WCL GraphQL `zone { name }` field may return a different string than expected (e.g. "Karazhan (Raid)", an ID, or `None`)
- Verify `RaidMetadata.zone` is populated correctly from `client.get_report_metadata()`
- Check the GraphQL query in `client.py` to confirm zone name is being fetched

## Current Code
- `analysis.py` line 34: `_TEN_MAN_ZONES = {"Karazhan", "Zul'Aman"}`
- `analysis.py` line 47: `if metadata.zone in _TEN_MAN_ZONES:`
- Thresholds: 10-man uses `healer_threshold_10` (default 400,000) vs 25-man `healer_threshold` (default 40,000)

## Fix Options
1. Log `metadata.zone` value and adjust `_TEN_MAN_ZONES` set to match actual API output
2. Use substring/case-insensitive matching instead of exact set membership
3. Fall back to zone ID instead of zone name if the API provides that more reliably
