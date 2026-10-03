# WarcraftLogs Analyzer

TBC Classic raid analysis desktop app. Fetches data from the WarcraftLogs API, stores in SQLite, renders via PySide6.
The Toads Hub web app reuses `wcl-core` (analysis), `wcl-store` (storage, on Postgres) and `wcl-app` (services)
from this repo.

## Build & Install

```bash
pip install -e ".[dev]"       # core + dev tools
pip install -e ".[dev,gui]"   # include PySide6 GUI
pip install -e ".[dev,postgres]"  # include wcl-store's Postgres backend (SQLAlchemy, psycopg 3, Alembic)
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
pytest --cov=warcraftlogs_client --cov=wcl_core --cov=wcl_store --cov=wcl_app \
  --cov-report=term-missing                     # with coverage
WCL_STORE_TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres \
  pytest -rs tests/test_store_contract.py tests/test_wcl_store_package.py tests/test_wcl_app_package.py \
  tests/test_home_service.py tests/test_badges.py tests/step_defs/test_storage.py
```

The storage contract (`tests/test_store_contract.py`) runs every test on SQLite and on Postgres. Without
`WCL_STORE_TEST_DATABASE_URL` (or without the `postgres` extra) the Postgres half is skipped with that reason;
CI's `storage-postgres` job runs it against a `postgres:16.4` service and fails on any skip. Each run uses a
throwaway schema, so any scratch database works.

## Linting & Quality

`scripts/dev.py` holds every check; CI, pre-commit and the `Makefile` call its tasks, so all three agree.

```bash
python scripts/dev.py check     # every blocking CI check that needs no network, fastest first (or: make check)
python scripts/dev.py fix       # Ruff fixes and formatting (or: make fix)
python scripts/dev.py types imports -k   # any tasks, in order; -k keeps going after a failure
pre-commit install              # run the same pinned tools on every commit
```

Tasks: `format lint spelling imports deadcode types security test mutation` (together, `check`), plus `audit`, `diffcov`
(coverage of lines changed since origin/master, after `test`), `pgcov` (the storage tests on both backends and the
Postgres backend's changed-line coverage, which `diffcov` leaves out; CI's `storage-postgres` job runs it), `fuzz`,
`gui`. The coverage floor in `pyproject.toml` only goes up, and so do the mutation floors in `[tool.wcl.mutation]`
(`python scripts/mutate.py <module> -v` lists the mutants a module's tests miss).

CI's `ci-success` job is the one required check: it needs every other job and fails if any failed, was cancelled or was
skipped (`scripts/ci_gate.py`). A new CI job goes in its `needs` and either lists its `dev.py` tasks in `JOB_TASKS` or
gets a reason in `OUTSIDE_DEV` (both in `tests/test_dev_tasks.py`).

Checker versions are pinned in the `dev` extra; bump them through Dependabot, not by hand. The underlying commands:

```bash
ruff check .                    # lint
ruff format --check .           # format check
ruff check --fix . && ruff format .  # auto-fix
mypy warcraftlogs_client/ packages/wcl-core/src/ packages/wcl-store/src/ packages/wcl-app/src/ --exclude 'gui/'
lint-imports                    # package layering contracts (see [tool.importlinter] in pyproject.toml)
vulture warcraftlogs_client/ packages/wcl-core/src/ packages/wcl-store/src/ packages/wcl-app/src/ \
  vulture_whitelist.py --min-confidence 80 --exclude warcraftlogs_client/gui/
bandit -c pyproject.toml -r warcraftlogs_client/ packages/wcl-core/src/ packages/wcl-store/src/ packages/wcl-app/src/
codespell warcraftlogs_client/ packages/wcl-core/src/ packages/wcl-store/src/ packages/wcl-app/src/ tests/
```

## Project Structure

- `warcraftlogs_client/` — main package (CLI, services, renderers, GUI; `<module>.py` aliases for code moved to
  `packages/`)
- `warcraftlogs_client/gui/` — PySide6 desktop app (excluded from mypy/vulture/coverage)
- `tests/` — unit, BDD (`tests/features/` + `tests/step_defs/`), fuzz (`tests/fuzz/`), GUI (`tests/gui/`)
- `packages/wcl-core/` — `wcl_core`: WCL client, auth (client credentials and the user OAuth flow), analysis, models,
  spell data and role configs (no Qt, no SQLite). `warcraftlogs_client/<module>.py` files for moved modules are import
  aliases. All its HTTP goes through `wcl_core.http`; tests fake it with `wcl_core.testing` (`FakeWarcraftLogs`,
  `FakeDiscord`, `FakeHub`), not `unittest.mock`. The shared packages read the time only through `wcl_core.clock`
  (`tests/test_clock.py`); tests use `FakeClock`. `wcl_core.hub` is the Toads Hub client (`guides/hub_bridge.md`)
- `packages/wcl-core/src/wcl_core/data/` — spell name mappings and consumes/interrupt/debuff/totem/cooldown configs
- `packages/wcl-store/` — `wcl_store`: the `RaidRepository` protocol and `StorageError`, the SQLite backend
  (`wcl_store.sqlite.PerformanceDB`, formerly `database.py`, which stays as an import alias) and the Postgres backend
  (`wcl_store.postgres`, SQLAlchemy Core + psycopg 3, `postgres` extra)
- `packages/wcl-store/src/wcl_store/postgres/migrations/` — Alembic migrations for the Postgres schema, numbered
  `0001_…`; `wcl_store.postgres.upgrade(url)` runs them
- `packages/wcl-app/` — `wcl_app`: the application services (`AppContext`, `RaidService`, `PlayerService`,
  `PlayerPageService`, `RoleOverrideService`, `HomeService`, `BadgeService`, `ReferenceService`, `BridgeService`,
  lineage); depends only on wcl-core and wcl-store. `warcraftlogs_client/services/` is an import alias of it.
  Headless hosts use `AppContext.headless(client, storage)`
- `guides/` — project documentation; `guides/CHARTER.md` is the engineering charter (requirement IDs and statuses,
  audited by `tests/test_charter.py`; change a status in the pull request that changes the check),
  `guides/home_widgets.md` the Home widget payload contract the Toads Hub shares, `guides/badges.md` the Toads badge
  payload and its thresholds, and `guides/reference_comparison.md` the reference comparison payload

## Conventions

- Python 3.10+, line length 120
- Ruff for linting and formatting (config in pyproject.toml)
- Ruff also enforces security (`S`), blind excepts (`BLE`), pathlib (`PTH`) and a complexity ceiling of 15 (`C901`).
  Split a function rather than adding `# noqa: C901`; the existing ones are a list to shrink. A deliberate catch-all
  gets `# noqa: BLE001 - <why>`
- All changes go through PRs — never push directly to master
- Config in `pyproject.toml`, not separate tool config files
- `config.json` holds API credentials — never commit real values (template in `config.example.json`)

## Architecture rules

Layers, innermost first; each may import only itself and inner layers. `tests/test_architecture.py` enforces this.

1. **core**: WCL client, auth, config, analysis, domain models (moving to `wcl_core`). No Qt, SQLite, web or bot code.
2. **persistence**: `wcl_store` (`packages/wcl-store`). The only place SQL lives. Services depend on the
   `RaidRepository` protocol and catch `StorageError`, never a driver's exceptions; `PerformanceDB` keeps extra
   desktop-only queries. A new storage operation a service needs goes into the protocol, both backends and
   `tests/test_store_contract.py` together; a Postgres schema change is a new numbered Alembic revision
   (`test_migrations_match_the_schema_and_downgrade_cleanly` checks it matches `schema.py`). No Qt, web, bot or desktop
   imports.
3. **services**: `wcl_app` (`packages/wcl-app`; `warcraftlogs_client/services/` is its alias). The application layer
   every frontend shares. Imports only wcl-core, wcl-store, `requests` and the standard library: no Qt, `sqlite3`,
   FastAPI, Discord or `warcraftlogs_client` (`lint-imports`). Storage comes from `AppContext.repository()`: the desktop
   SQLite database, or whatever the host passes as `AppContext(storage=...)` / `AppContext.headless(client, storage)`.
4. **presenters**: `renderers/`. Turn domain models into text; never read storage.
5. **frontends**: CLI, PySide6 desktop, and later the Toads API and bot. Call services only; from core they may use just
   `models`, `common`, `paths`, `version`.

New features go into a service first, then each frontend adapts it. Charts share presenter payloads, not drawing code.
Auth/RBAC stays in the frontend adapters. Existing shortcuts are listed in `KNOWN_VIOLATIONS` in the test; the list may
only shrink, so move a view onto a service and delete its entry rather than adding new ones.
