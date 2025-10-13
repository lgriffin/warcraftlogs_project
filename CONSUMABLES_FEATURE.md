# Consumables Analysis Feature

## Overview
The consumables analysis feature tracks protection potion and personal buff usage across multiple raid reports, providing insights into player preparation and consumable optimization.

## Usage

```bash
# Analyze one or more raid reports
python -m warcraftlogs_client.cli consumes RAID_ID1 RAID_ID2 RAID_ID3

# Export to CSV
python -m warcraftlogs_client.cli consumes RAID_ID1 RAID_ID2 --csv output.csv
```

## Tracked Consumables

### Protection Potions (All Roles)
- **Shadow Protection** (ID: 17548)
- **Fire Protection** (ID: 17543)
- **Arcane Protection** (ID: 17549)
- **Nature Protection** (ID: 17546)
- **Frost Protection** (ID: 17544)

### Personal Buffs (Healers Only)
- **Major Mana Potion** (ID: 17531)
- **Dark Rune** (ID: 27869)

## Counting Logic

### Protection Potions
The system counts potion usage by tracking:
1. **`removebuff` events** - Each removal = 1 potion consumed
2. **`refreshbuff` events** - Each refresh = 1 new potion used while buff active
3. **Unpaired `applybuff`/`cast` events** - Potions used but buff still active at end

**Why this approach?**
- Protection potions can be used before combat starts (out of logging range)
- Only the `removebuff` event is logged for these pre-combat usages
- `refreshbuff` indicates drinking another potion while the first is still active
- Buffs lasting 1 hour may persist through entire raid segments

### Personal Buffs (Mana Potions, Dark Runes)
Simply counts `cast` events, as these are always logged during combat.

## Role Identification
- Uses existing dynamic role identification system
- Personal buffs are filtered to show only for players identified as healers
- Role thresholds can be configured in `config.json`

## Configuration

The consumables are defined in `consumes_config.json`:

```json
{
  "personal_buffs": {
    "17531": "Major Mana Potion",
    "27869": "Dark Rune"
  },
  "defensive_potions": {
    "17548": "Shadow Protection",
    "17543": "Fire Protection",
    "17549": "Arcane Protection",
    "17546": "Nature Protection",
    "17544": "Frost Protection"
  },
  "role_restrictions": {
    "personal_buffs": ["healer"],
    "defensive_potions": ["tank", "healer", "melee", "ranged"]
  }
}
```

## Output Format

### Console Output
Shows two tables per raid:
1. **Protection Potions Used** - All players, all 5 protection potion types
2. **Personal Buffs Usage (Healers Only)** - Healer players, mana potions and dark runes

### CSV Export
Includes columns:
- Player Name
- Raid ID
- Raid Title
- Role
- Each consumable type with usage count

## Technical Implementation

### Data Collection
1. **Buffs Query** (`dataType: Buffs`) - Gets `applybuff`, `removebuff`, `refreshbuff` events
2. **Casts Query** (`dataType: Casts`) - Gets `cast` events for mana potions
3. **Deduplication** - Uses `(ability_id, timestamp, event_type)` tuples to avoid double-counting

### Pairing Algorithm
For protection potions:
- Groups `applybuff` + `cast` events at same timestamp as one application
- Checks if each application has a `removebuff` event within 5 seconds
- If no near-immediate remove exists, counts the application separately
- Counts all `removebuff` events (represents actual consumption)
- Counts all `refreshbuff` events (represents re-application)

### Edge Cases Handled
- ✅ Potions used before combat logging starts
- ✅ Potions whose buffs persist through entire raid
- ✅ Multiple potions used in quick succession
- ✅ Refreshing buff by drinking another potion
- ✅ Simultaneous `applybuff` + `cast` events
- ✅ Buffs that expire naturally (1 hour duration)

## Known Limitations

1. **Pre-combat usage**: If a potion is used more than 1 hour before combat, the buff may have expired before logging started
2. **Website differences**: Warcraft Logs website may count events differently; our system focuses on logical potion usage
3. **Death handling**: Currently no special handling for buffs removed on death vs. normal consumption
4. **Fight boundaries**: Analyzes entire raid report, not individual fight segments

## Examples

```bash
# Analyze two Naxxramas raids
python -m warcraftlogs_client.cli consumes kbK1yFXBrTc84anf h82jKRpPCWF6TtQk

# Analyze with CSV export
python -m warcraftlogs_client.cli consumes kbK1yFXBrTc84anf --csv naxx_consumes.csv
```

## Troubleshooting

**Q: Numbers don't match Warcraft Logs website?**
A: The website may count individual events (applies, casts, removes) separately, while our system counts logical potion usage. Our approach focuses on "how many potions were actually consumed."

**Q: Personal buffs showing 0 for healers?**
A: Check role identification thresholds in `config.json`. The player may not meet the minimum healing threshold to be classified as a healer.

**Q: Protection potions seem low?**
A: Potions used significantly before combat starts (>1 hour) won't be logged. Also, buffs that persist through the entire raid without being removed won't have a `removebuff` event.

## Future Enhancements

Potential improvements:
- Death event correlation (track if `removebuff` coincides with death)
- Fight-by-fight breakdown instead of raid-wide
- Additional consumable types (flasks, elixirs, food buffs)
- Trend analysis across multiple raids
- Warning system for players with unusually low consumption

