# 🔮 Spell Configuration Management

This directory contains the spell configuration files that control how the Warcraft Logs analyzer handles spell IDs and names. **Non-developers can easily edit these files** to add missing spells or fix incorrect mappings.

## 📁 Files Overview

### `spell_aliases.json` - Spell ID Aliases
Maps different spell IDs that represent the same ability (e.g., different ranks of the same spell).

**When to edit**: When you see multiple entries for what should be the same spell (like "Flash Heal Rank 1", "Flash Heal Rank 7", etc.)

### `spell_names.json` - Spell ID to Name Mappings  
Maps spell IDs to their display names when the API doesn't provide them.

**When to edit**: When you see `(ID 12345)` instead of a proper spell name in reports.

## 🛠️ How to Add Missing Spells

### Adding a Missing Spell Name

If you see `(ID 12345)` in a report instead of the actual spell name:

1. Open `spell_names.json`
2. Find the appropriate category (e.g., `warrior_abilities`, `boss_abilities_mc`, etc.)
3. Add the mapping: `"12345": "Actual Spell Name"`

**Example**:
```json
"warrior_abilities": {
  "20647": "Execute",
  "11601": "Revenge",
  "12345": "New Warrior Ability"  ← Add this line
}
```

### Adding Spell Aliases (Merging Ranks)

If you see separate entries for different ranks of the same spell:

1. Open `spell_aliases.json`
2. Find or create an appropriate group (e.g., `flash_heal_variants`)
3. Map all variant IDs to one canonical ID

**Example**:
```json
"flash_heal_variants": {
  "2061": 2060,   ← All these IDs will be treated as spell 2060
  "9472": 2060,
  "9473": 2060,
  "25235": 2060
}
```

## 📋 Step-by-Step Guide

### 1. Finding Missing Spell Information

Run the analyzer and look for:
- `(ID 12345)` - Missing spell names
- Multiple similar spells - Candidates for aliasing
- Inconsistent spell groupings

### 2. Adding the Information

**For missing names**:
1. Note the spell ID number
2. Look up the spell name (use wowhead.com, classic.wowhead.com, or the game)
3. Add to appropriate category in `spell_names.json`

**For spell ranks**:
1. Identify all the different IDs for the same spell
2. Choose one as the "canonical" ID (usually the highest rank)
3. Add mappings in `spell_aliases.json`

### 3. Testing Your Changes

Run the analyzer again to verify:
- Spell names appear correctly
- Similar spells are grouped together
- No JSON syntax errors

## 🏷️ File Format Rules

### JSON Syntax Rules
- Use double quotes `"` around keys and string values
- Numbers don't need quotes: `"12345": 67890`
- Strings need quotes: `"12345": "Spell Name"`
- Add commas `,` between entries (but not after the last one)
- Use proper nesting with `{` and `}`

### Organization Guidelines

**spell_names.json categories**:
- `protection_spells` - Potions and protective abilities
- `priest_spells`, `paladin_spells`, etc. - Class-specific abilities
- `boss_abilities_mc`, `boss_abilities_bwl`, etc. - Raid boss abilities
- `consumables` - Potions, food, etc.

**spell_aliases.json groups**:
- `[spell_name]_variants` - Different ranks of the same spell
- Group logically by spell type or function

## ⚠️ Common Mistakes

1. **Forgetting commas**: Each entry needs a comma except the last one
2. **Wrong quotes**: Use `"` not `'` 
3. **Missing canonical ID**: In aliases, make sure the canonical ID exists in names
4. **Circular aliases**: Don't create loops (A→B, B→A)

## 🧪 Validation

The system includes automatic validation:
- Checks for circular aliases
- Reports loading errors
- Shows count of loaded mappings

Look for these messages when running the analyzer:
```
✅ Loaded 45 spell aliases
✅ Loaded 312 spell names
```

## 📖 Examples

### Adding a New Boss Ability
```json
// In spell_names.json, add to boss_abilities_aq:
"26999": "New AQ Boss Ability"
```

### Merging Spell Ranks
```json
// In spell_aliases.json, create new group:
"new_spell_variants": {
  "12001": 12000,  // Rank 1 → Canonical
  "12002": 12000,  // Rank 2 → Canonical  
  "12003": 12000   // Rank 3 → Canonical
}
```

### Adding Multiple Related Spells
```json
// In spell_names.json:
"new_class_abilities": {
  "15001": "New Ability Rank 1",
  "15002": "New Ability Rank 2", 
  "15003": "Different New Ability"
}

// In spell_aliases.json:
"new_ability_variants": {
  "15002": 15001  // Merge ranks 1 and 2
}
```

## 🤝 Contributing Back

If you add missing spells, please consider:
1. Creating a GitHub issue with your additions
2. Submitting a pull request
3. Sharing in the community Discord

This helps everyone benefit from your discoveries!

## 🆘 Getting Help

If you're stuck:
1. Check the JSON syntax with an online validator
2. Look at existing examples in the files
3. Ask in the community Discord
4. Create a GitHub issue with your question

Remember: **You can't break anything permanently** - just restore from Git if something goes wrong! 