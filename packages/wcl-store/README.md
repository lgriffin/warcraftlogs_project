# wcl-store

Storage for WCL Analyzer raid data. The application services are written against one protocol,
`wcl_store.RaidRepository`, and two backends implement it:

- `wcl_store.sqlite.PerformanceDB`: the desktop app's SQLite database. Standard library only. It also keeps
  the desktop views' read queries, which are not part of the protocol yet.
- `wcl_store.postgres.PostgresRaidRepository`: Postgres through SQLAlchemy Core and psycopg 3, for the
  Toads Hub. Install the `postgres` extra.

Both raise `wcl_store.StorageError` when the database fails. `tests/test_store_contract.py` in the
repository runs the same checks against both backends.

Install from another project, pinned to a commit (wcl-store depends on wcl-core from the same commit):

```toml
[project]
dependencies = ["wcl-store[postgres]"]

[tool.uv.sources]
wcl-core = { git = "https://github.com/lgriffin/warcraftlogs_project", subdirectory = "packages/wcl-core", rev = "<sha>" }
wcl-store = { git = "https://github.com/lgriffin/warcraftlogs_project", subdirectory = "packages/wcl-store", rev = "<sha>" }
```

Create or upgrade the Postgres schema with the bundled Alembic migrations, then open a repository:

```python
import os

from wcl_store.postgres import PostgresRaidRepository, upgrade

url = os.environ["DATABASE_URL"]  # a plain postgresql:// URL uses psycopg 3
upgrade(url)
with PostgresRaidRepository(url) as repo:
    repo.import_raid(analysis)
```

Services take storage through `AppContext(storage=...)`, for example
`AppContext(config, storage=lambda: PostgresRaidRepository(engine))` with one shared engine.

To run the migrations from a host project's own Alembic setup instead, point `script_location` at
`wcl_store.postgres:migrations`. Revisions are numbered `0001`, `0002`, ...
