# Developer Guide

## Overview

WarcraftLogs Analyzer fetches raid performance data from the [WarcraftLogs](https://www.warcraftlogs.com) GraphQL API, runs role-based analysis (healers, tanks, melee/ranged DPS), and stores historical trends in a local SQLite database. It ships as both a CLI tool and a PySide6 desktop application.

## Architecture

```
User Input (GUI / CLI)
    |
    v
Config & Auth (config.py, auth.py)
    |
    v
WarcraftLogs GraphQL API (client.py)
    |
    v
Analysis Engine (analysis.py, consumes_analysis.py)
    |-- Role detection (dynamic_role_parser.py)
    |-- Spell mapping (spell_manager.py)
    |
    v
Data Models (models.py)
    |
    +---> Renderers (renderers/console.py, renderers/markdown.py)
    +---> SQLite Persistence (database.py)
    +---> GUI Display (gui/)
```

## Entry Points

| Entry Point | Command | Module |
|-------------|---------|--------|
| CLI | `warcraftlogs` | `warcraftlogs_client.cli:main` |
| Desktop App | `warcraftlogs-gui` | `warcraftlogs_client.gui.app:run` |

The CLI provides subcommands: `unified`, `healer`, `tank`, `melee`, `ranged`, `consumes`, `history`. Run `warcraftlogs --help` for details.

## Module Reference

### Core

| Module | Purpose |
|--------|---------|
| `client.py` | GraphQL API client with rate limiting (250ms throttle, exponential backoff on 429/5xx) |
| `analysis.py` | Raid analysis orchestration: role detection, performance calculation, consumable tracking |
| `database.py` | SQLite persistence with schema migrations, trend queries, raid group management |
| `models.py` | Dataclasses for all domain objects (`RaidAnalysis`, `HealerPerformance`, `TankPerformance`, etc.) |
| `config.py` | Configuration loading from `config.json` with env var overrides |
| `auth.py` | OAuth2 client credentials token management with auto-renewal |
| `spell_manager.py` | Spell ID-to-name mapping with rank deduplication via `spell_aliases.json` |
| `consumes_analysis.py` | Multi-raid consumable usage tracking with spike detection |
| `cache.py` | JSON file cache for API query results |
| `paths.py` | Path resolution for dev vs PyInstaller frozen environments |
| `common/errors.py` | Exception hierarchy: `WarcraftLogsError`, `ApiError`, `ConfigurationError`, `DataProcessingError` |
| `cli.py` | Argument parser and CLI subcommand dispatch |

### Renderers

| Module | Purpose |
|--------|---------|
| `renderers/console.py` | Terminal-formatted raid reports |
| `renderers/markdown.py` | Markdown export with tables and sections |

### GUI (PySide6)

| Module | Purpose |
|--------|---------|
| `gui/app.py` | QApplication entry point |
| `gui/main_window.py` | Sidebar navigation with stacked views |
| `gui/analyze_view.py` | Report input, live analysis, results tables with consumable filtering |
| `gui/history_view.py` | Character history browser with trend charts and heatmaps |
| `gui/character_view.py` | WCL profile integration, rankings, performance trends |
| `gui/raid_group_view.py` | Raid roster management (CRUD) with attendance and role coverage analytics |
| `gui/settings_view.py` | API credentials, role thresholds, database management |
| `gui/worker.py` | QThread wrappers for background API calls |
| `gui/charts.py` | Line charts, radar/spider charts, calendar heatmaps |
| `gui/table_models.py` | Qt AbstractTableModel implementations for tabular data |
| `gui/detail_panel.py` | Character spell/ability detail side panel |
| `gui/styles.py` | Dark theme color constants and stylesheet definitions |

## Key Design Patterns

**Separation of concerns**: Analysis functions (`analysis.py`) return dataclasses and never print. Presentation is handled by renderers or GUI views.

**Singleton management**: `SpellManager` and `ConfigManager` use module-level singletons with explicit reset functions for testability.

**Rate limiting**: All API calls go through `WarcraftLogsClient.run_query()`, which enforces a minimum 250ms interval between requests and retries with exponential backoff (1s, 2s, 4s) on 429/5xx responses, up to 3 attempts.

**Role detection pipeline**: Players are classified by analyzing their combat events. Fixed roles (Rogue=melee, Mage=ranged) are assigned directly. Hybrid classes (Warrior, Paladin, Druid, Shaman, Priest) are classified by examining their damage profile: if >40% of damage comes from melee swings, they are melee; otherwise ranged.

**Spell deduplication**: Classic WoW has multiple spell IDs per rank. `spell_aliases.json` maps variant IDs to a canonical ID so "Greater Heal Rank 1-7" all aggregate into a single "Greater Heal" entry.

## Data Flow: Raid Analysis

1. `analyze_raid()` fetches report metadata and master actor list from the API
2. `_identify_composition()` determines each player's role (tank/healer/melee/ranged)
3. `_analyze_healers/tanks/dps()` fetch per-player event data and build performance objects
4. `_analyze_consumables()` checks buff tables and cast events against `consumes_config.json`
5. Results are returned as a `RaidAnalysis` dataclass
6. Optionally persisted to SQLite via `PerformanceDB.import_raid()`

## Database Schema

The SQLite database (`warcraftlogs_history.db`) stores:

- **characters** - name, class, first/last seen
- **raids** - report_id, title, owner, date, timestamps
- **healer_performance** + **healer_spells** - per-character healing with spell breakdowns
- **tank_performance** + **tank_damage_taken** + **tank_abilities** - damage taken/mitigated with breakdowns
- **dps_performance** + **dps_abilities** - damage dealt with ability breakdowns
- **consumable_usage** - consumable counts and timestamps per character per raid
- **raid_groups** + **raid_group_members** - named roster management

Schema versioning uses a `schema_version` table with sequential migrations in `_migrate()`.

## Configuration

### config.json

```json
{
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "report_id": "DEFAULT_REPORT_ID",
  "guild_id": 774065,
  "role_thresholds": {
    "healer_min_healing": 50000,
    "tank_min_taken": 150000,
    "tank_min_mitigation": 40
  },
  "character_name": "",
  "character_server": "",
  "character_region": "eu",
  "wcl_api_url": "https://fresh.warcraftlogs.com/api/v2/client"
}
```

Environment variable overrides: `WARCRAFTLOGS_CLIENT_ID`, `WARCRAFTLOGS_CLIENT_SECRET`, `WARCRAFTLOGS_REPORT_ID`.

### consumes_config.json

Maps spell IDs to consumable names, split by detection method:

- **buff_consumables** - detected via aura/buff tables (e.g., Haste Potion, Destruction Potion)
- **cast_consumables** - detected via cast events (e.g., Super Mana Potion, Dark Rune)

### Spell Data (spell_data/)

- `spell_names.json` - spell ID to display name mappings by category
- `spell_aliases.json` - maps rank variants to canonical spell IDs for deduplication

## Development Setup

### Prerequisites

- Python 3.10+
- A WarcraftLogs API client (create one at https://www.warcraftlogs.com/api/clients)

### Installation

```bash
# Clone and install in development mode
git clone https://github.com/lgriffin/warcraftlogs_project.git
cd warcraftlogs_project
pip install -e ".[dev,gui]"
```

### Running

```bash
# CLI
warcraftlogs unified --report-id YOUR_REPORT_ID

# GUI
warcraftlogs-gui
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=warcraftlogs_client --cov-report=term-missing

# Run a specific test file
pytest tests/test_analysis.py -v
```

Tests use `tmp_path` fixtures for file/database isolation and `MagicMock` for API client mocking. The `conftest.py` provides shared fixtures including `mock_client`, `sample_raid_analysis`, and a temporary `db` fixture.

### Linting

```bash
ruff check .
```

## Building the Installer

### PyInstaller (Windows executable)

```bash
pip install pyinstaller
pyinstaller warcraftlogs_analyzer.spec
```

Output: `dist/WarcraftLogsAnalyzer/WarcraftLogsAnalyzer.exe`

### Inno Setup (Windows installer)

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php):

```bash
# After PyInstaller build:
iscc installer.iss
```

Output: `installer_output/WarcraftLogsAnalyzer-3.0.0-Setup.exe`

## File Locations

| Environment | Config | Database | Cache | Reports |
|-------------|--------|----------|-------|---------|
| Development | `./config.json` | `./warcraftlogs_history.db` | `./.cache/` | `./reports/` |
| Installed | `%APPDATA%/WarcraftLogsAnalyzer/config.json` | `%APPDATA%/.../warcraftlogs_history.db` | `%LOCALAPPDATA%/.../cache/` | `%APPDATA%/.../reports/` |

Path resolution is handled by `paths.py`, which detects frozen (PyInstaller) vs development environments.

## Adding New Features

### Adding a new consumable

Edit `consumes_config.json` and add the spell ID and name to either `buff_consumables` or `cast_consumables` depending on how WarcraftLogs tracks it.

### Adding a new spell alias

Edit `spell_data/spell_aliases.json` to map variant spell IDs to a canonical ID. This ensures all ranks of a spell aggregate into a single entry.

### Adding a new database query

1. Add the query method to `PerformanceDB` in `database.py`
2. Write tests in `tests/test_database.py` or `tests/test_database_extended.py`
3. If it needs a schema change, increment `SCHEMA_VERSION` and add migration logic to `_migrate()`
