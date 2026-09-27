"""Alembic environment for wcl-store's Postgres schema.

Runs on the connection ``wcl_store.postgres.upgrade`` passes in ``config.attributes["connection"]``, or on
``sqlalchemy.url`` from the Alembic config when run from the ``alembic`` command line.
"""

from alembic import context
from sqlalchemy import Connection
from wcl_store.postgres.repository import make_engine
from wcl_store.postgres.schema import metadata

config = context.config


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("Set sqlalchemy.url, or run migrations through wcl_store.postgres.upgrade()")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            _run(conn)
    finally:
        engine.dispose()
