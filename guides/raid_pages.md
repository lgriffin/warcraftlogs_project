# Raid pages payload

`wcl_app.raid_pages.RaidPageService` turns stored guild raids into the desktop app's raid browser and raid analysis as
JSON, read from storage alone (no Warcraft Logs call). The Toads Hub's worker publishes them for the hub's Logs page;
the desktop app's raid view shares the same boss/trash and engineering helpers. `RAID_PAGE_VERSION` (now 1) changes
when a field changes meaning.

## `RaidSummary.to_dict()`: one raid in the list

| Field | Meaning |
| --- | --- |
| `report_id`, `title`, `zone` | as stored |
| `raid_date` | `"YYYY-MM-DD HH:MM:SS"`, the raid's local start time as stored |
| `weekday` | 0 for Monday to 6 for Sunday (`date.weekday()`), or `null` when the date cannot be read |
| `size` | players in the raid |
| `url` | the report on its Warcraft Logs site |

`index(limit=1000)` lists every stored guild raid, newest first, inside the service's scope (`from_context` follows
the active raid profile).

## `RaidPage.to_dict()`: one raid's analysis

`page(report_id, summary=None)` returns `None` for a raid that is not a stored guild raid (a reference report included)
or cannot be read back. Numbers are raw;
the frontend formats them. Each section matches a tab of the desktop raid view:

| Field | Desktop tab | Rows |
| --- | --- | --- |
| `summary` | header | the raid's `RaidSummary` |
| `duration_ms`, `version`, `warnings` | header | |
| `composition` | Composition | `tanks`, `healers`, `melee`, `ranged`: `{name, player_class}` |
| `healers` | Healers | `name, player_class, healing, overhealing, overheal_percent, dispels, active_percent`, most healing first |
| `tanks` | Tanks | `name, player_class, damage_taken, mitigated, mitigation_percent, active_percent` |
| `melee`, `ranged` | Melee DPS, Ranged DPS | `name, player_class, damage, active_percent`, most damage first |
| `consumable_names`, `consumables` | Consumables | names most used first; rows `{name, role, counts: {consumable: n}}` |
| `boss_vs_trash` | Boss vs Trash | `{name, boss, trash}`: uses inside a boss encounter's window, and outside |
| `interrupts` | Interrupts | `name, player_class, spell_name, count` |
| `cancelled_casts` | Cast Efficiency | `name, player_class, total_casts, cancelled_casts, cancel_rate, spells: [...]` |
| `debuff_uptimes`, `totem_uptimes` | Debuff Uptime, Totem Uptime | `spell_name, fight_name, uptime_percent` |
| `engineering` | Engineering | `name, total_casts, total_damage, users, min_avg, median_avg, max_avg` (damage per cast) |
| `encounters` | Encounters | `encounter_id, name, duration_ms, damage, healing, players: [{name, player_class, role, damage, healing, damage_taken, active_percent}]` |

The desktop deep dive (cast timelines, wasted resources, cooldown synergy) calls Warcraft Logs live, so it is not part
of the page.

## `boss_history(pages)`: each boss across raids, by weekday

The desktop Boss History filters by weekday; the payload keeps each weekday apart so a frontend adds the days it shows
and divides by the kills. Each player row is one character in one role, so a respec keeps its own row. Bosses come most
kills first.

```json
{"encounter_id": 623, "name": "Hydross the Unstable",
 "days": {"2": {"kills": 4, "duration_ms": 1200000, "damage": 9000000, "healing": 4000000,
                "players": [{"name": "...", "player_class": "Rogue", "role": "melee", "kills": 4,
                             "damage": 1200000, "healing": 0, "damage_taken": 50000}]}}}
```
