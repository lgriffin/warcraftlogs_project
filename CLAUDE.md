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
pytest --cov=warcraftlogs_client --cov-report=term-missing  # with coverage
```

## Linting & Quality

```bash
ruff check .                    # lint
ruff format --check .           # format check
ruff check --fix . && ruff format .  # auto-fix
mypy warcraftlogs_client/ --exclude 'gui/'
vulture warcraftlogs_client/ vulture_whitelist.py --min-confidence 80 --exclude warcraftlogs_client/gui/
bandit -c pyproject.toml -r warcraftlogs_client/
codespell warcraftlogs_client/ tests/
```

## Project Structure

- `warcraftlogs_client/` — main package (client, analysis, database, models, renderers)
- `warcraftlogs_client/gui/` — PySide6 desktop app (excluded from mypy/vulture/coverage)
- `tests/` — unit, BDD (`tests/features/` + `tests/step_defs/`), fuzz (`tests/fuzz/`), GUI (`tests/gui/`)
- `spell_data/` — spell name mappings
- `guides/` — project documentation

## Conventions

- Python 3.10+, line length 120
- Ruff for linting and formatting (config in pyproject.toml)
- All changes go through PRs — never push directly to master
- Config in `pyproject.toml`, not separate tool config files
- `config.json` holds API credentials — never commit real values (template in `config.example.json`)
