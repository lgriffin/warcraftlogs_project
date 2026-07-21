# WarcraftLogs Analyzer Testing Guide

## Overview

The WarcraftLogs Analyzer employs a multi-tier testing strategy spanning eight levels, from granular unit tests through live API smoke tests and GUI widget validation. The strategy ensures correctness at every layer: data models, API client, analysis pipeline, database persistence, renderers, and the PySide6 desktop interface.

## Coverage Targets

| Metric     | Threshold | Notes                                    |
|------------|-----------|------------------------------------------|
| Lines      | 80%       | Enforced in CI via `--cov-fail-under=80` |
| Statements | 80%       | Rising target as coverage improves       |

Coverage is gathered from `warcraftlogs_client/`, with `warcraftlogs_client/gui/*` initially excluded from the non-GUI threshold (GUI coverage comes from Tier 3).

---

## Test Tier Architecture

### Tier 1: TDD Unit Tests

**Location:** `tests/test_*.py`
**Framework:** pytest
**Count:** ~250+ tests across 27 files

The foundation layer. Each module has a dedicated test file covering its public API, edge cases, and error paths. Tests use `unittest.mock.MagicMock` for the WarcraftLogs API client and real SQLite databases via `tmp_path`.

| Module | Test File | Focus |
|--------|-----------|-------|
| CLI parsing | `test_cli.py` | All subcommands, flags, --version |
| API client | `test_client.py` | Bearer auth, JSON parsing, cast tables, pagination |
| Rate limiting | `test_rate_limiting.py` | Throttle timing, 429 retry, exponential backoff |
| OAuth2 (client) | `test_auth.py` | Token validity, refresh, error scenarios |
| OAuth2 (user) | `test_user_auth.py` | Token save/load, refresh, revoke, callback server |
| Configuration | `test_config.py` | Loading, validation, env overrides, caching |
| Analysis pipeline | `test_analysis.py` | Role classification, composition, consumable tracking |
| Database (core) | `test_database.py` | Schema, upsert, history, trends, groups, case-insensitive matching |
| Database (extended) | `test_database_extended.py` | Consumable summary, spell trends, compliance, personal bests |
| Reference reports | `test_reference_reports.py` | Isolation, comparison, migration, head-to-head helpers |
| Encounters | `test_encounters.py` | Boss filtering, damage merge, pet exclusion |
| Aura/debuff uptime | `test_aura_uptime.py` | Band clamping, config filtering, DB roundtrip |
| Interrupts | `test_interrupts.py` | Extraction from cast events, begincast filtering |
| Totem uptime | `test_totem_uptime.py` | Band merging, multi-shaman, prepull |
| Cancelled casts | `test_cancelled_casts.py` | All-completed/cancelled, multi-player, DB roundtrip |
| My Character | `test_my_character.py` | Role detection, boss comparison, trends |
| Raid diff | `test_raid_diff.py` | Consumable/interrupt summary computation |
| Data models | `test_models.py` | Overheal/mitigation percent, timestamps, composition |
| Table models | `test_table_models.py` | Display data, sorting, formatting, checkbox mode |
| Cache | `test_cache.py` | Safe filenames, JSON roundtrip, corrupt handling |
| Renderers | `test_renderers.py` | Console output, summary tables |
| Markdown renderer | `test_markdown_renderer.py` | Markdown structure, file export |
| Spell manager | `test_spell_manager.py` | ID resolution, aggregation, circular alias detection |
| Dynamic role parser | `test_dynamic_role_parser.py` | Group-by-class, healer identification |
| Path resolution | `test_paths.py` | Frozen/dev detection, directory resolution |
| Error hierarchy | `test_errors.py` | Inheritance, severity, safe_api_call, error_handler |
| Common data | `test_common_data.py` | Legacy wrapper delegation |

### Tier 2: BDD Behavioral Tests

**Location:** `tests/features/` + `tests/step_defs/`
**Framework:** pytest-bdd (Gherkin syntax)
**Count:** ~50+ scenarios across 10 feature files

BDD tests describe system behavior in plain language, readable by non-engineers. They operate at a higher abstraction level than unit tests, verifying workflows rather than individual functions.

| Feature File | Step Defs | Coverage |
|-------------|-----------|----------|
| `auth.feature` | `test_auth.py` | Token lifecycle, error scenarios |
| `cli.feature` | `test_cli.py` | Command-line workflows |
| `configuration.feature` | `test_configuration.py` | Config load/validate |
| `consumables.feature` | `test_consumables.py` | Consumable tracking |
| `database.feature` | `test_database.py` | Import, query, history |
| `encounter_analysis.feature` | `test_encounter_analysis.py` | Boss encounter analysis |
| `raid_analysis.feature` | `test_raid_analysis.py` | Full raid analysis pipeline |
| `reference_reports.feature` | `test_reference_reports.py` | Reference report comparison |
| `report_export.feature` | `test_report_export.py` | Markdown/console export |
| `user_auth.feature` | `test_user_auth.py` | User OAuth2 flow |

**Rationale for both TDD and BDD:** TDD catches the *how* (code paths, edge cases). BDD verifies the *what* (user-facing behavior, workflows).

### Tier 3: GUI Widget Tests

**Location:** `tests/gui/`
**Framework:** pytest-qt
**Count:** ~50+ tests across 7 files

Drives actual PySide6 widgets: clicking buttons, verifying table contents, checking signal emissions, simulating navigation workflows. Uses `qtbot` for widget lifecycle management and signal waiting.

| Test File | Widget Under Test | Focus |
|-----------|------------------|-------|
| `test_nav_stack.py` | `NavigationStack` | Push/pop, depth changes, base page switching |
| `test_download_view.py` | `DownloadView` | Table population, day filters, status column |
| `test_raid_analysis_widget.py` | `RaidAnalysisWidget` | Header buttons, tabs, Refresh/Delete, signals |
| `test_raids_view.py` | `RaidsView` | Raid list, boss dropdown |
| `test_settings_view.py` | `SettingsView` | Config fields, save/load |
| `test_table_models.py` | Table models | Data display, sorting (pytest-qt version) |
| `test_main_window.py` | `MainWindow` | Navigation, view switching, signal routing |

All GUI tests use `pytest.importorskip("PySide6")` and gracefully skip when PySide6 is not installed. Database calls are mocked to avoid I/O.

### Tier 4: Property-Based Fuzz Tests

**Location:** `tests/fuzz/`
**Framework:** hypothesis
**Count:** ~30+ tests across 4 files

Generates random and adversarial inputs to find crashes and edge cases that handwritten tests miss. Every property test runs 50 examples by default.

| Test File | Target | Fuzzing Strategy |
|-----------|--------|-----------------|
| `test_config_fuzzing.py` | `load_config` | Random dicts, arbitrary types for each config key |
| `test_model_fuzzing.py` | Model constructors | Random strings, ints for all fields |
| `test_cache_fuzzing.py` | `_safe_filename`, cache I/O | Adversarial report IDs, random JSON |
| `test_spell_manager_fuzzing.py` | Spell resolution | Random spell IDs and names |

### Tier 5: Security Tests

**Location:** `tests/test_security.py`
**Focus:** OWASP-aligned security validation

| Test Class | Focus |
|-----------|-------|
| `TestTokenLeakage` | Secrets not in cache files, error messages, or exports |
| `TestSQLInjection` | Adversarial character names, report IDs, consumable names |
| `TestPathTraversal` | Report IDs with `../` cannot escape cache directory |

### Tier 6: API Surface Snapshot Tests

**Location:** `tests/test_api_surface.py`
**Purpose:** Breaking-change detector

Snapshots the public API surface: model exports, dataclass fields, database schema, CLI subcommands. Any accidental rename, removal, or field change causes immediate test failure.

| Snapshot | What It Guards |
|----------|---------------|
| Model exports | All public classes in `warcraftlogs_client.models` |
| Dataclass fields | Field names on RaidMetadata, HealerPerformance, RaidAnalysis, etc. |
| Database schema | Table names and structure |
| CLI structure | Subcommand names and arguments |

### Tier 7: Integration Tests

**Location:** `tests/integration/`
**Focus:** Cross-module correctness with real SQLite

| Test File | Scope |
|-----------|-------|
| `test_full_pipeline.py` | End-to-end: analyze -> import -> query -> verify |
| `test_reimport_idempotency.py` | Upsert semantics, double-import safety |
| `test_delete_cascade.py` | Cascading deletes across all tables |
| `test_reference_workflow.py` | Guild vs reference isolation, comparison queries |

### Tier 8: Live API Smoke Tests (Opt-In)

**Location:** `tests/integration/test_live_api.py`
**Activation:** `WCL_LIVE_TESTS=true` environment variable
**Requirements:** `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET` environment variables

Makes real HTTP requests to the WarcraftLogs API to verify authentication, response shapes, and URL construction. Not run in CI by default.

---

## Running Tests

### Primary Commands

```bash
# Unit + BDD (default, ~300+ tests)
pytest

# With coverage report
pytest --cov=warcraftlogs_client --cov-report=term-missing

# GUI tests (requires PySide6)
pytest tests/gui/ -v

# Fuzz tests
pytest tests/fuzz/ -v

# Integration tests
pytest tests/integration/ -v --ignore=tests/integration/test_live_api.py

# Security tests
pytest tests/test_security.py -v

# API surface tests
pytest tests/test_api_surface.py -v

# All tests except live API
pytest --ignore=tests/integration/test_live_api.py

# Parallel execution (faster)
pytest -n auto --ignore=tests/integration/test_live_api.py
```

### Live API Tests (Opt-In)

```bash
# Windows
set WCL_LIVE_TESTS=true
set WCL_CLIENT_ID=your_client_id
set WCL_CLIENT_SECRET=your_client_secret
pytest tests/integration/test_live_api.py -v

# Linux/macOS
WCL_LIVE_TESTS=true WCL_CLIENT_ID=... WCL_CLIENT_SECRET=... pytest tests/integration/test_live_api.py -v
```

### GUI Tests on Headless Linux

```bash
xvfb-run pytest tests/gui/ -v
```

### Selective Execution by Marker

```bash
pytest -m "not gui and not fuzz"     # Skip GUI and fuzz
pytest -m security                    # Security tests only
pytest -m integration                 # Integration tests only
pytest -m "not slow and not live"     # Fast tests only
```

---

## CI Pipeline

| Job | Trigger | Command | Enforcement |
|-----|---------|---------|-------------|
| **lint** | Every push/PR | `ruff check`, `ruff format --check`, `codespell`, `vulture` | Hard fail (except vulture) |
| **test** | Every push/PR | `pytest --cov --cov-fail-under=80` (Python 3.10 + 3.12) | Hard fail |
| **gui-test** | Every push/PR | `xvfb-run pytest tests/gui/` | Soft fail (continue-on-error) |
| **fuzz** | Every push/PR | `pytest tests/fuzz/` | Hard fail |
| **type-check** | Every push/PR | `mypy` (excludes gui/) | Soft fail |
| **security** | Every push/PR | `bandit` + `pytest tests/test_security.py` + `pip-audit` | Hard fail (except pip-audit) |
| **quality** | Every push/PR | `radon cc` + `radon mi` | Soft fail |

---

## Mocking Strategy

| Layer | Mock Approach | Real/Fake |
|-------|--------------|-----------|
| WarcraftLogs API | `unittest.mock.MagicMock` via `mock_client` fixture | Mocked |
| SQLite database | Real `PerformanceDB` in `tmp_path` | Real |
| Configuration | `monkeypatch` or `mock.patch` on `load_config` | Mocked |
| PySide6 widgets | `qtbot` from pytest-qt for lifecycle, mocked DB | Real widgets |
| File I/O (cache) | `monkeypatch` `CACHE_DIR` to `tmp_path` | Real I/O |

---

## Test Helpers & Fixtures

### Shared Fixtures (`tests/conftest.py`)

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `reset_global_state` | function (autouse) | Resets SpellManager and ConfigManager singletons |
| `sample_raid_metadata` | function | Pre-built RaidMetadata |
| `sample_healer_performance` | function | Pre-built HealerPerformance with spells |
| `sample_tank_performance` | function | Pre-built TankPerformance |
| `sample_dps_performance` | function | Pre-built DPSPerformance |
| `sample_composition` | function | Pre-built RaidComposition |
| `sample_raid_analysis` | function | Complete RaidAnalysis |
| `sample_encounter_summary` | function | EncounterSummary with 3 players |
| `sample_master_actors` | function | Raw API actor list |
| `mock_client` | function | MagicMock of WarcraftLogsClient |
| `db` | function | Fresh PerformanceDB in tmp_path |
| `config_file` | function | Valid config.json in tmp_path |
| `build_analysis` | function | Factory fixture with configurable overrides |

### GUI Fixtures (`tests/gui/conftest.py`)

| Fixture | Purpose |
|---------|---------|
| `mock_config` | Patched `load_config` with test credentials |
| `mock_db` | Fresh PerformanceDB for GUI tests |
| `sample_analysis` | Complete RaidAnalysis for widget testing |
| `populated_db` | Database with one imported raid |

### Integration Fixtures (`tests/integration/conftest.py`)

| Fixture/Helper | Purpose |
|----------------|---------|
| `db` | Fresh PerformanceDB |
| `make_analysis()` | Factory function for building RaidAnalysis |

---

## PySide6 Skip Patterns

GUI-dependent tests use `pytest.importorskip("PySide6")` at the top of each file. This ensures tests gracefully skip when PySide6 is not installed (e.g., in headless CI without the `gui` extra).

```python
# Standard pattern for GUI test files
import pytest
pytest.importorskip("PySide6")
# PySide6 imports follow
```

---

## Adding New Tests

### Unit Test (Tier 1)

1. Create `tests/test_<module>.py`
2. Import the module under test
3. Use `mock_client` fixture for API calls, `db` fixture for database
4. Use `build_analysis` fixture for test data
5. Cover happy path, edge cases, and error paths

### BDD Scenario (Tier 2)

1. Add scenario to `tests/features/<domain>.feature` in Gherkin
2. Add step definitions to `tests/step_defs/test_<domain>.py`
3. Use `@given`, `@when`, `@then` decorators with `parsers.parse`

### GUI Test (Tier 3)

1. Create `tests/gui/test_<widget>.py`
2. Start with `pytest.importorskip("PySide6")`
3. Use `qtbot.addWidget()` for cleanup, `qtbot.waitSignal()` for signals
4. Mock database and config to avoid real I/O
5. Mark with `@pytest.mark.gui`

### Fuzz Test (Tier 4)

1. Create `tests/fuzz/test_<module>_fuzzing.py`
2. Use `@given(strategy)` from hypothesis
3. Add `@settings(max_examples=50)` for CI performance
4. Assert the function under test doesn't crash (no specific return value)
5. Mark with `@pytest.mark.fuzz`

---

## Known Gaps

| Gap | Severity | Details |
|-----|----------|---------|
| GUI view logic | Medium | Not all 11 views have dedicated test files |
| Worker thread testing | Medium | QThread-based workers (AnalysisWorker, GuildReportsWorker) lack async testing |
| Visual regression | Low | No screenshot comparison tests |
| Performance benchmarks | Low | No systematic performance regression detection |
| Live API pagination | Low | Live tests don't exercise paginated endpoints |

---

## Architecture Rationale

- **TDD** — fast, deterministic, covers every code path
- **BDD** — Gherkin scenarios readable by non-engineers, verify user-facing behavior
- **GUI** — catches widget bugs that unit tests on models alone would miss
- **Fuzz** — finds crashes from unexpected inputs that handwritten tests overlook
- **Security** — prevents token leakage, SQL injection, path traversal
- **API surface** — breaking-change detector, prevents accidental regressions
- **Integration** — verifies cross-module correctness with real database
- **Live API** — catches URL construction bugs and response shape changes

---

## Configuration Files

| Config | Purpose |
|--------|---------|
| `pyproject.toml [tool.pytest.ini_options]` | Test paths, markers, strict mode |
| `pyproject.toml [tool.coverage.run]` | Coverage source and omissions |
| `pyproject.toml [tool.coverage.report]` | Fail-under threshold, show missing |
| `.github/workflows/ci.yml` | CI pipeline with 7 jobs |
