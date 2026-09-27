"""Postgres backend for wcl-store (install ``wcl-store[postgres]``).

``upgrade(url)`` brings a database to the latest numbered Alembic migration; ``PostgresRaidRepository``
implements ``wcl_store.RaidRepository`` on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

try:
    from .repository import PostgresRaidRepository, PostgresStorageError, make_engine
except ModuleNotFoundError as e:  # pragma: no cover - depends on what is installed
    if e.name not in ("sqlalchemy", "psycopg"):
        raise
    raise ModuleNotFoundError(
        f"wcl_store.postgres needs {e.name}: install the extra, e.g. pip install 'wcl-store[postgres]'", name=e.name
    ) from e

if TYPE_CHECKING:
    from alembic.config import Config
    from sqlalchemy import Connection, Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

__all__ = [
    "MIGRATIONS_DIR",
    "PostgresRaidRepository",
    "PostgresStorageError",
    "alembic_config",
    "make_engine",
    "upgrade",
]


def alembic_config(connection: Connection | None = None) -> Config:
    """Alembic config for the bundled migrations, optionally bound to an open connection."""
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def upgrade(target: str | Engine, revision: str = "head") -> None:
    """Run the bundled migrations up to ``revision`` against a URL or engine."""
    from alembic import command

    engine = make_engine(target) if isinstance(target, str) else target
    try:
        with engine.begin() as conn:
            command.upgrade(alembic_config(conn), revision)
    finally:
        if isinstance(target, str):
            engine.dispose()
