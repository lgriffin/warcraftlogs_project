# Character pages payload

`wcl_app.character_pages.CharacterPageService` turns one character's stored guild raids into the desktop app's
character profile as JSON, read from storage alone (no Warcraft Logs call). The Toads Hub's worker publishes a page for
each member's claimed characters for the hub's Me page. `CHARACTER_PAGE_VERSION` (now 1) changes when a field changes
meaning.

`page(name)` returns `None` for a character with no guild raid inside the service's scope (`from_context` follows the
active raid profile), or when storage cannot be read. The name matches case-insensitively; the page carries the stored
spelling. Raid analyses read for the medians are kept for the service's lifetime, so one service building a whole
roster's pages reads each raid once.

## `CharacterPage.to_dict()`

| Field | Meaning |
| --- | --- |
| `version` | `CHARACTER_PAGE_VERSION` |
| `name`, `player_class` | as stored |
| `raids`, `first_raid`, `last_raid`, `role_counts` | every guild raid the character is in, with `{role: raids}` |
| `recent` | the newest `MAX_RAIDS` (40) raids, newest first (below) |
| `metrics`, `casts`, `consumables` | `wcl_app.lineage` spreads (`name, role, min, mean, max, raids, total, raids_used`) over every raid: headline numbers, the 10 most cast spells, the 10 most used consumables |
| `bests` | per role, the raid with the highest headline number: `metric, role, value, display, report_id, raid_date`; tanks have none |
| `charts` | one [chart payload](charts.md) per role in `recent`, id `character_<role>`: the character against the raid's median over their last 20 raids in that role, oldest first |

## One raid in `recent`

| Field | Meaning |
| --- | --- |
| `report_id`, `title`, `zone` | as stored |
| `raid_date` | `"YYYY-MM-DD HH:MM:SS"`, the raid's local start time |
| `weekday` | 0 for Monday to 6 for Sunday, or `null` |
| `role` | `healer`, `tank`, `melee` or `ranged` |
| `metric`, `value`, `display` | the role's headline number: healing, damage taken (tanks) or damage; `display` is compact (`700.0K`) |
| `median`, `median_display` | the median of everyone in that role in the raid, the character included; `null` / `"-"` when the raid cannot be read back |
| `rank`, `of` | the character's place in the role (1 is the most) and how many played it; `0` for tanks, whose damage taken ranks nothing |
| `percent` | overheal % for a healer, mitigation % for a tank, else `null` |
