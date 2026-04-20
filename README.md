# WCL Analyzer v3.0 — TBC Edition

A desktop application for analyzing **Warcraft Logs** reports with a focus on **spell casts, utility usage, and consumable tracking** for The Burning Crusade Classic.

Traditional metrics are heavily influenced by gear, but **casts and abilities** offer a clearer view of player behavior, decision-making, and contribution to the raid.

---

## Quick Start (No Programming Experience Needed)

### 1. Install Python

- Download Python 3.10+ from [python.org](https://www.python.org/downloads/)
- During installation, **check "Add Python to PATH"**

### 2. Download the Project

```bash
git clone https://github.com/your-username/warcraftlogs-client.git
cd warcraftlogs-client
```

Or download and extract the ZIP from GitHub.

### 3. Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Launch the App

**Double-click** `WCL Analyzer.bat` — no terminal required.

Or from a terminal:

```bash
python -m warcraftlogs_client.gui.app
```

### 5. Configure API Credentials

1. Go to the [WarcraftLogs API Client Management](https://www.warcraftlogs.com/api/clients/) page and create a client
2. Open the **Settings** tab in the app
3. Enter your Client ID and Client Secret
4. Set your Guild ID
5. Click **Save Settings**

---

## Features

### Desktop GUI

The full-featured PySide6 desktop app provides:

- **Analyze Tab** — Enter a report ID or select from your guild's recent reports to run a full raid analysis. Results are broken down by role (Healers, Tanks, Melee DPS, Ranged DPS) with clickable character names for detailed spell/ability breakdowns.
- **History Tab** — Browse all imported raids and characters. View performance trends over time with charts for healing, damage, mitigation, and consumables. Compare raids side by side.
- **Character Tab** — Set up your main character to view WarcraftLogs profile data, rankings, and recent reports. Links directly to your WCL profile page.
- **Settings Tab** — Configure API credentials, role detection thresholds, and manage the local database.

### Raid Analysis

For each raid, the analyzer automatically classifies players into roles and provides:

- **Healers**: Healing output, overhealing %, spell breakdown, dispels, resource usage
- **Tanks**: Damage taken, mitigation %, damage taken breakdown, abilities used
- **Melee DPS**: Total damage, ability breakdown with casts and damage per ability
- **Ranged DPS**: Same as melee, with automatic hybrid class detection (Shadow Priest, Boomkin, Elemental Shaman)
- **Consumables**: Protection potions, mana potions, and tracked consumable usage across all roles

### Consumable Tracking

Tracks consumable usage per player per raid:

- **Buff-based tracking** via the WCL Buffs table (protection potions, mana potions, dark runes)
- **Cast-based tracking** for specific potions with timestamps:
  - Destruction Potion (22839)
  - Super Mana Potion (22832)
  - Haste Potion (22838)

Timestamps show when each potion was used during the raid, visible in both the overall raid Consumables tab and individual character detail panels.

Consumables to track via buffs are configured in `consumes_config.json`.

### Local Database

All analyzed raids are saved to a local SQLite database (`warcraftlogs_history.db`), enabling:

- Performance trends over time per character
- Consumable usage history across raids
- Quick re-viewing of past raids without re-fetching from the API
- Guild report list shows which raids are already cached

The database can be cleared from **Settings > Clear Database** (requires typing "I am Toad" to confirm).

### Guild Reports

The Analyze tab automatically fetches your guild's recent reports with:

- Day-of-week filtering (defaults to Wed/Thu/Sun raid days)
- Saved/cached indicators for previously imported raids
- Clickable report codes that open the raid on WarcraftLogs
- Double-click to immediately analyze a report

---

## Role Detection

Classic WoW / TBC does not expose role information directly, so the analyzer uses heuristics:

- **Tanks**: Warriors, Druids, and Paladins with high damage taken AND high mitigation %
- **Healers**: Priests, Paladins, Druids, and Shamans with healing above a configurable threshold
- **Hybrid DPS**: Warriors, Paladins, Druids, Shamans, and Priests are classified as melee or ranged based on their damage profile (melee swing % vs spell damage %)

Thresholds are configurable in Settings:

```json
{
  "role_thresholds": {
    "healer_min_healing": 50000,
    "tank_min_taken": 150000,
    "tank_min_mitigation": 40
  }
}
```

---

## Spell Management

Classic WoW uses multiple spell IDs for the same ability (different ranks). The spell management system handles this automatically.

### Adding Missing Spells

If you see `(ID 12345)` instead of a spell name:

```bash
python manage_spells.py add-name 12345 "Actual Spell Name" warrior_abilities
```

Or edit `spell_data/spell_names.json` directly.

### Merging Duplicate Spells

```bash
python manage_spells.py add-alias 12001,12002,12003 12000 new_spell_variants
```

Or edit `spell_data/spell_aliases.json` directly.

### Spell Management Commands

```bash
python manage_spells.py validate           # Check configuration
python manage_spells.py search "Flash Heal" # Find spells
python manage_spells.py list-categories    # Show categories
python manage_spells.py list-groups        # Show alias groups
```

---

## CLI Mode

The command-line interface is still available for scripting and automation:

```bash
python -m warcraftlogs_client.cli unified --md    # Full analysis with markdown output
python -m warcraftlogs_client.cli healer           # Healer-focused analysis
python -m warcraftlogs_client.cli tank             # Tank mitigation analysis
python -m warcraftlogs_client.cli melee            # Melee DPS analysis
python -m warcraftlogs_client.cli ranged           # Ranged DPS analysis
python -m warcraftlogs_client.cli consumes raid1 raid2 --csv report.csv  # Consumables
```

Markdown reports are saved to the `reports/` directory.

---

## Config Files

| File | Purpose |
|------|---------|
| `config.json` | API credentials, guild ID, role thresholds, character settings |
| `consumes_config.json` | Buff-based consumable tracking IDs (protection pots, mana pots, etc.) |
| `spell_data/spell_names.json` | Spell ID to name mappings |
| `spell_data/spell_aliases.json` | Spell rank/variant merging rules |

---

## Output

- GUI: Results displayed in interactive tables with charts
- CLI: Markdown files saved to `reports/` directory
- Database: SQLite file at `warcraftlogs_history.db`

Place a `logo.png` in the `reports/` folder to customise markdown output with your guild logo.
