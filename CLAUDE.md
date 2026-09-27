# WarcraftLogs Analyzer

TBC Classic raid analysis desktop app. Fetches data from the WarcraftLogs API, stores in SQLite, renders via PySide6.

## Build & Install

```bash
pip install -e ".[dev]"       # core + dev tools
pip install -e ".[dev,gui]"   # include PySide6 GUI
```

## Running

```bash
warcraftlogs            # CLI
warcraftlogs-gui        # PySide6 desktop app
```

## Testing

```bash
pytest                                          # unit + BDD tests (no GUI)
pytest tests/gui/ -v                            # GUI widget tests (needs PySide6)
pytest tests/fuzz/ -v                           # property-based fuzz tests
pytest tests/test_security.py -v                # security tests
pytest --cov=warcraftlogs_client --cov=wcl_core --cov-report=term-missing  # with coverage
```

## Linting & Quality

```bash
ruff check .                    # lint
ruff format --check .           # format check
ruff check --fix . && ruff format .  # auto-fix
mypy warcraftlogs_client/ packages/wcl-core/src/ --exclude 'gui/'
lint-imports                    # wcl-core imports no Qt/SQLite/desktop code
vulture warcraftlogs_client/ packages/wcl-core/src/ vulture_whitelist.py --min-confidence 80 --exclude warcraftlogs_client/gui/
bandit -c pyproject.toml -r warcraftlogs_client/
codespell warcraftlogs_client/ packages/wcl-core/src/ tests/
```

## Project Structure

- `warcraftlogs_client/` — main package (client, analysis, database, models, renderers)
- `warcraftlogs_client/gui/` — PySide6 desktop app (excluded from mypy/vulture/coverage)
- `tests/` — unit, BDD (`tests/features/` + `tests/step_defs/`), fuzz (`tests/fuzz/`), GUI (`tests/gui/`)
- `packages/wcl-core/` — `wcl_core`: WCL client, analysis, models, spell data and role configs (no Qt, no SQLite). `warcraftlogs_client/<module>.py` files for moved modules are import aliases
- `packages/wcl-core/src/wcl_core/data/` — spell name mappings and consumes/interrupt/debuff/totem/cooldown configs
- `guides/` — project documentation

## Conventions

- Python 3.10+, line length 120
- Ruff for linting and formatting (config in pyproject.toml)
- All changes go through PRs — never push directly to master
- Config in `pyproject.toml`, not separate tool config files
- `config.json` holds API credentials — never commit real values (template in `config.example.json`)

## Architecture rules

Layers, innermost first; each may import only itself and inner layers. `tests/test_architecture.py` enforces this.

1. **core**: WCL client, auth, config, analysis, domain models (moving to `wcl_core`). No Qt, SQLite, web or bot code.
2. **persistence**: `database.py` (`PerformanceDB`). The only place SQL lives.
3. **services**: `warcraftlogs_client/services/` (future `wcl-app`). The application layer every frontend shares. No Qt, `sqlite3`, FastAPI or Discord imports.
4. **presenters**: `renderers/`. Turn domain models into text; never read storage.
5. **frontends**: CLI, PySide6 desktop, and later the Toads API and bot. Call services only; from core they may use just `models`, `common`, `paths`, `version`.

New features go into a service first, then each frontend adapts it. Charts share presenter payloads, not drawing code. Auth/RBAC stays in the frontend adapters. Existing shortcuts are listed in `KNOWN_VIOLATIONS` in the test; the list may only shrink, so move a view onto a service and delete its entry rather than adding new ones.
