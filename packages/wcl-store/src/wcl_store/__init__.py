"""wcl-store: storage for WCL Analyzer raid data behind one ``RaidRepository`` contract.

Backends:

- ``wcl_store.sqlite.PerformanceDB``: the desktop app's SQLite database (standard library only).
- ``wcl_store.postgres.PostgresRaidRepository``: Postgres through SQLAlchemy Core and psycopg 3, with Alembic
  migrations. Needs the ``wcl-store[postgres]`` extra.

Importing this package loads neither backend.
"""

from .errors import StorageError
from .repository import RaidRepository
from .scope import RaidScope, narrowed

__all__ = ["RaidRepository", "RaidScope", "StorageError", "narrowed"]
