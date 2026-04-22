# WCL Analyzer v3.0 — TBC Edition

A desktop application for analyzing **Warcraft Logs** reports with a focus on **spell casts, utility usage, and consumable tracking** for The Burning Crusade Classic.

Traditional metrics are heavily influenced by gear, but **casts and abilities** offer a clearer view of player behavior, decision-making, and contribution to the raid.

---

## Windows Installer

A standalone Windows installer is available that bundles everything — no Python installation required.

1. Download `WarcraftLogsAnalyzer-3.0.0-Setup.exe` from the [Releases](https://github.com/lgriffin/warcraftlogs_project/releases) page
2. Run the installer and follow the prompts
3. Launch **WarcraftLogs Analyzer** from the Start Menu or desktop shortcut

On first launch the app copies a default config and creates a local SQLite database. All user data is stored separately from the application:

| Data | Location |
|------|----------|
| Config | `%APPDATA%\WarcraftLogsAnalyzer\config.json` |
| Database | `%APPDATA%\WarcraftLogsAnalyzer\warcraftlogs_history.db` |
| Cache | `%LOCALAPPDATA%\WarcraftLogsAnalyzer\cache\` |

Uninstalling the app does not remove user data — delete the folders above manually if needed.

### Building the Installer

To build the installer from source:

```bash
pip install pyinstaller
python -m PyInstaller warcraftlogs_analyzer.spec
```

The runnable output is in `dist/WarcraftLogsAnalyzer/` — the `build/` directory is only PyInstaller's working area and cannot be run directly.

To create the installer `.exe`, install [Inno Setup](https://jrsoftware.org/isinfo.php) and compile `installer.iss`.

---

## Quick Start (From Source)

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
- **History Tab** — Browse all imported raids and characters. View performance trends over time with charts for healing, damage, mitigation, and consumables. Character insights include consistency scores, personal bests, radar charts, and calendar heatmaps.
- **Raid Groups Tab** — Create and manage raid groups, assign characters, set raid days, and view group dashboards with aggregated performance, attendance, and role coverage.
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

### Raid Groups

Create named groups of characters to track your raid roster over time:

- **Group Management** — Create, rename, and delete raid groups. Add/remove characters detected from imported reports.
- **Raid Days** — Select which days your group raids (Mon-Sun). The view automatically shows matching raids from your history.
- **Group Dashboard** — Aggregated performance chart, attendance tracker, and role coverage matrix for group members.
- **History Integration** — Characters show colored group tag pills in the History tab. Filter the character list by raid group.

### Character Insights

The History tab includes advanced analytics per character:

- **Consistency Score** — How stable performance is across raids (lower variance = higher score)
- **Consumable Compliance** — Percentage of raids where consumables were used, with average per raid
- **Personal Bests** — Best and worst performances for healing, damage, and mitigation with raid context

### Radar Chart

The Radar (spider) chart shows a character's relative standing across six dimensions, each scored 0-100:

| Axis | How it's calculated |
|------|-------------------|
| **Healing** | Percentile rank of average healing output vs. all tracked characters |
| **Damage** | Percentile rank of average damage output vs. all tracked characters |
| **Mitigation** | Percentile rank of average mitigation % vs. all tracked tanks |
| **Activity** | Percentile rank of total raids attended vs. all tracked characters |
| **Consumables** | Percentile rank of total consumables used vs. all tracked characters |
| **Consistency** | Average consistency score across roles (100 = identical every raid, lower = more variance between raids) |

Hover over any axis label on the chart for a tooltip explanation.

### Calendar Heatmap

A GitHub-style activity heatmap showing raid participation over the last 6 months, colored by performance intensity.

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
