"""wcl-store as a standalone package: aliases, errors, layering, version and the Postgres migrations."""

import ast
import importlib
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import wcl_store
from wcl_store import RaidRepository, StorageError
from wcl_store.sqlite import PerformanceDB, SQLiteStorageError

from warcraftlogs_client.services import AppContext, RaidService

ROOT = Path(__file__).resolve().parent.parent
STORE_SRC = Path(wcl_store.__file__).resolve().parent


def test_old_import_path_is_the_same_module():
    assert importlib.import_module("warcraftlogs_client.database") is importlib.import_module("wcl_store.sqlite")


def test_performance_db_is_a_raid_repository(tmp_path):
    with PerformanceDB(str(tmp_path / "t.db")) as db:
        assert isinstance(db, RaidRepository)


def test_sqlite_errors_leave_as_storage_errors_that_are_still_sqlite_errors(tmp_path):
    """Services catch StorageError; the desktop views' existing ``except sqlite3.Error`` keeps working."""
    with PerformanceDB(str(tmp_path / "t.db")) as db:
        db._get_conn().execute("DROP TABLE raids")
        with pytest.raises(SQLiteStorageError) as info:
            db.is_raid_imported("x")
    assert isinstance(info.value, StorageError)
    assert isinstance(info.value, sqlite3.Error)
    assert isinstance(info.value.__cause__, sqlite3.OperationalError)


def test_app_context_opens_injected_storage(tmp_path, sample_raid_analysis):
    """Hosts such as the Toads Hub worker hand services their own repository through ``storage``."""
    code = "aBcDeFgHiJkLmN12"
    sample_raid_analysis.metadata.report_id = code
    other = str(tmp_path / "other.db")
    ctx = AppContext(config={}, db_path=str(tmp_path / "desktop.db"), storage=lambda: PerformanceDB(other))

    RaidService(ctx).save(sample_raid_analysis)

    assert RaidService(ctx).imported_codes() == {code}
    with PerformanceDB(other) as db:
        assert db.is_raid_imported(code)
    with ctx.db() as desktop:
        assert not desktop.is_raid_imported(code)


def test_contract_module_calls_every_protocol_method():
    """A method added to RaidRepository must be exercised by the contract module too."""
    methods = sorted(n for n, v in vars(RaidRepository).items() if not n.startswith("_") and callable(v))
    assert len(methods) == 26
    contract = (ROOT / "tests" / "test_store_contract.py").read_text(encoding="utf-8")
    missing = [m for m in methods if f".{m}(" not in contract]
    assert not missing, f"tests/test_store_contract.py never calls: {missing}"


@pytest.mark.postgres
def test_services_run_on_postgres(pg_empty_engine, sample_raid_analysis):
    from wcl_store.postgres import PostgresRaidRepository

    from warcraftlogs_client.services import RoleOverrideService

    code = "aBcDeFgHiJkLmN12"
    sample_raid_analysis.metadata.report_id = code
    ctx = AppContext(config={}, storage=lambda: PostgresRaidRepository(pg_empty_engine))
    RaidService(ctx).save(sample_raid_analysis)
    assert RaidService(ctx).list_raids()[0]["report_id"] == code

    with ctx.repository() as repo:
        results = RoleOverrideService(repo).set("StabbyRogue", "tank", reanalyze=True)
        assert [(r.report_id, r.ok) for r in results] == [(code, False)]  # no WCL access here to re-analyse
        assert repo.get_role_overrides_for_report(code) == {"StabbyRogue": "tank"}


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


@pytest.mark.ears_ubiquitous
def test_req_core_store_002_store_imports_no_qt_web_bot_or_desktop_code():
    """REQ-CORE-STORE-002: wcl-store imports no Qt, web, bot or desktop module (also enforced by lint-imports)."""
    forbidden = ("PySide6", "fastapi", "discord", "warcraftlogs_client")
    for path in STORE_SRC.rglob("*.py"):
        for name in _imports(path):
            assert name.split(".")[0] not in forbidden, f"{path.relative_to(STORE_SRC)} imports {name}"


def test_sqlite_side_needs_no_postgres_extra():
    """The desktop app installs wcl-store without SQLAlchemy, psycopg or Alembic."""
    code = (
        "import sys, wcl_store, wcl_store.sqlite; "
        "bad = {'sqlalchemy', 'psycopg', 'alembic', 'warcraftlogs_client'} & {m.split('.')[0] for m in sys.modules}; "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=STORE_SRC.parent)


def test_wcl_store_version_matches_the_app():
    def version(pyproject: Path) -> str:
        match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
        assert match, pyproject
        return match.group(1)

    assert version(ROOT / "packages/wcl-store/pyproject.toml") == version(ROOT / "pyproject.toml")


def test_release_script_bumps_every_package_version():
    script = (ROOT / "build_release.sh").read_text(encoding="utf-8")
    for pyproject in ("pyproject.toml", "packages/wcl-core/pyproject.toml", "packages/wcl-store/pyproject.toml"):
        assert f'"s/^version = .*/version = \\"${{VERSION}}\\"/" {pyproject}' in script, pyproject


def test_migrations_are_numbered_in_sequence():
    versions = sorted((STORE_SRC / "postgres" / "migrations" / "versions").glob("*.py"))
    assert versions, "no migrations"
    for i, path in enumerate(versions, 1):
        assert path.name.startswith(f"{i:04d}_"), path.name
        source = path.read_text(encoding="utf-8")
        assert f'revision: str = "{i:04d}"' in source
        down = "None" if i == 1 else f'"{i - 1:04d}"'
        assert f"down_revision: str | Sequence[str] | None = {down}" in source


def test_make_engine_uses_psycopg_3():
    pytest.importorskip("sqlalchemy", reason="needs the postgres extra")
    from wcl_store.postgres import make_engine

    for url in ("postgresql://localhost/wcl", "postgres://localhost/wcl", "postgresql+psycopg://localhost/wcl"):
        assert make_engine(url).url.drivername == "postgresql+psycopg"


@pytest.mark.postgres
def test_migrations_match_the_schema_and_downgrade_cleanly(pg_engine):
    """Alembic's head equals ``schema.metadata``, and every revision can be undone and redone."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect
    from wcl_store.postgres import alembic_config
    from wcl_store.postgres.schema import VERSION_TABLE, metadata

    def diff() -> list:
        with pg_engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn, opts={"compare_server_default": True, "version_table": VERSION_TABLE}
            )
            return compare_metadata(ctx, metadata)

    assert diff() == []
    with pg_engine.begin() as conn:
        command.downgrade(alembic_config(conn), "base")
    with pg_engine.connect() as conn:
        # Its own revision table, so it can share a database with another app's Alembic migrations.
        assert set(inspect(conn).get_table_names()) == {VERSION_TABLE}
    with pg_engine.begin() as conn:
        command.upgrade(alembic_config(conn), "head")
    assert diff() == []
