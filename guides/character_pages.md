# Character pages payload

`wcl_app.character_pages.CharacterPageService` turns one character's stored guild raids into the desktop app's
character profile as JSON, read from storage alone (no Warcraft Logs call). The Toads Hub's worker publishes a page for
each member's claimed characters for the hub's Me page. `CHARACTER_PAGE_VERSION` (now 1) changes when a field changes
meaning.

`page(name)` returns `None` for a character with no guild raid inside the service's scope (`from_context` follows the
active raid profile; pages read guild raids only, whatever sources the scope names), or when storage cannot be read.
The name matches case-insensitively; the page carries the stored spelling. `pages(names)` builds a roster's pages in
one storage session, reading each raid's analysis once; each call reads raids afresh.

Storage keys characters by name, so two characters who shared a name (a classic priest and the TBC shaman who took the
name later) share their raids there. Each raid records the class played in it, and a page covers only the raids played
as the class of the character's newest raid. A raid stored before classes were recorded counts for every class until
`RaidService.backfill_classes()` (`warcraftlogs player classes`) reads the classes from Warcraft Logs.

## `CharacterPage.to_dict()`

| Field | Meaning |
| --- | --- |
| `version` | `CHARACTER_PAGE_VERSION` |
| `name`, `player_class` | the stored name; the class of the newest raid (the stored class when none is recorded) |
| `raids`, `first_raid`, `last_raid`, `role_counts` | every guild raid the character played as that class, with `{role: raids}` |
| `recent` | the newest `MAX_RAIDS` (40) raids, newest first (below) |
| `metrics` | `wcl_app.lineage` spreads (`name, role, min, mean, max, raids, total, raids_used`) of headline numbers |
| `casts`, `consumables` | the same spreads for the 10 most cast spells and the 10 most used consumables |
| `bests` | per role, the raid with the highest headline number (`metric, role, value, display, report_id, raid_date`) |
| `charts` | one [chart payload](charts.md) per role in `recent`, id `character_<role>` (below) |

Tanks have no best: the lowest damage taken is no achievement. Each chart draws the character against the raid's
median over their last 20 raids in that role, oldest first.

## One raid in `recent`

| Field | Meaning |
| --- | --- |
| `report_id`, `title`, `zone` | as stored |
| `raid_date` | `"YYYY-MM-DD HH:MM:SS"`, the raid's local start time |
| `weekday` | 0 for Monday to 6 for Sunday, or `null` |
| `role` | `healer`, `tank`, `melee` or `ranged` |
| `metric`, `value`, `display` | the role's headline number: healing, damage taken (tanks) or damage |
| `median`, `median_display` | the median of everyone in that role in the raid, the character included |
| `rank`, `of` | the character's place in the role (1 is the most) and how many played it |
| `percent` | overheal % for a healer, mitigation % for a tank, else `null` |

`display` is compact (`700.0K`). `median` is `null` and `median_display` `"-"` when the raid cannot be read back. `rank`
and `of` are `0` when unknown, and always for tanks, whose damage taken ranks nothing.
