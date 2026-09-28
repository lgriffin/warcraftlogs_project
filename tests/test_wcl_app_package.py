"""wcl-app as a standalone package: aliases, layering, version, and services run by a headless host."""

import ast
import importlib
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import wcl_app
from wcl_app import AppContext, RaidService, RoleOverrideService

ROOT = Path(__file__).resolve().parent.parent
APP_SRC = Path(wcl_app.__file__).resolve().parent
MODULES = [
    "badges",
    "charts",
    "context",
    "healing",
    "home",
    "lineage",
    "player_page",
    "players",
    "raids",
    "reference",
    "roles",
]
CODE = "raidReport000001"
OTHER = "raidReport000002"


def test_old_package_path_is_the_same_package():
    assert importlib.import_module("warcraftlogs_client.services") is wcl_app


@pytest.mark.parametrize("name", MODULES)
def test_old_import_path_is_the_same_module(name):
    assert importlib.import_module(f"warcraftlogs_client.services.{name}") is importlib.import_module(f"wcl_app.{name}")


def test_patching_the_old_path_reaches_the_service(tmp_path):
    """Tests and callers that patch ``warcraftlogs_client.services.raids`` still patch what RaidService calls."""
    ctx = AppContext(config={}, db_path=str(tmp_path / "t.db"), _client=MagicMock())
    with patch("warcraftlogs_client.services.raids.analyze_raid") as analyze:
        RaidService(ctx).analyze(CODE)
    analyze.assert_called_once()


class FakeRepository:
    """In-memory stand-in for a RaidRepository: just the calls RaidService and RoleOverrideService make here."""

    def __init__(self):
        self.raids: dict[str, tuple[object, str]] = {}
        self.overrides: dict[tuple[str, str], str] = {}
        self.opened = 0

    def __enter__(self):
        self.opened += 1
        return self

    def __exit__(self, *exc):
        return False

    def set_role_override(self, character_name: str, role: str, report_id: str = "") -> None:
        self.overrides[(character_name, report_id)] = role

    def get_role_overrides_for_report(self, report_id: str) -> dict[str, str]:
        found = {n: r for (n, code), r in self.overrides.items() if code == ""}
        found.update({n: r for (n, code), r in self.overrides.items() if code == report_id})
        return found

    def import_raid(self, analysis, source: str = "guild") -> None:
        self.raids[analysis.metadata.report_id] = (analysis, source)

    def get_imported_report_codes(self) -> dict[str, str]:
        return {code: source for code, (_, source) in self.raids.items()}

    def get_raid_analysis(self, report_id: str):
        stored = self.raids.get(report_id)
        return stored[0] if stored else None


@contextmanager
def _no_config_or_sqlite():
    """Fail the test if anything reads config.json or opens the SQLite database."""

    def refuse(*_a, **_k):
        raise AssertionError("a headless host must not read config.json or open SQLite")

    with (
        patch("wcl_core.config.load_config", side_effect=refuse),
        patch("wcl_store.sqlite.PerformanceDB", side_effect=refuse),
    ):
        yield


def _fake_analysis(report_id):
    analysis = MagicMock()
    analysis.metadata.report_id = report_id
    return analysis


@pytest.mark.ears_ubiquitous
def test_raid_service_runs_headless_with_an_injected_client_and_repository():
    """The Toads Hub worker's path: its own client and storage, saved role overrides applied, no files."""
    repo = FakeRepository()
    client = MagicMock(name="host WarcraftLogsClient")
    ctx = AppContext.headless(client, storage=lambda: repo, config={"role_thresholds": {"tank_min_taken": 1}})
    repo.set_role_override("Holy", "tank")
    repo.set_role_override("Holy", "dps", CODE)
    repo.set_role_override("Enh", "ranged", OTHER)

    with (
        _no_config_or_sqlite(),
        patch("wcl_app.raids.analyze_raid", side_effect=lambda *a, **k: _fake_analysis(CODE)) as analyze,
    ):
        analysis = RaidService(ctx).analyze_and_save(CODE)
        assert RaidService(ctx).imported_codes() == {CODE}
        assert RaidService(ctx).get_raid(CODE) is analysis

    args, kwargs = analyze.call_args
    assert args == (client, CODE)
    assert kwargs["role_overrides"] == {"Holy": "dps"}  # the raid's own override beats the character-wide one
    assert kwargs["tank_min_taken"] == 1
    assert repo.raids[CODE][1] == "guild"
    assert ctx.wcl_client is client


def test_headless_context_needs_no_credentials_or_config_file():
    repo = FakeRepository()
    with _no_config_or_sqlite():
        ctx = AppContext.headless(MagicMock(), storage=lambda: repo)
        with ctx.repository() as opened:
            assert opened is repo
    assert ctx.config == {} and ctx.db_path is None


def test_headless_reference_analysis_uses_only_the_injected_user_client():
    """Reference reports never fall back to the desktop's signed-in token file or config.json."""
    from wcl_app import ReferenceAuthRequired

    repo = FakeRepository()
    refuse = AssertionError("a headless host must not read the desktop's user token")
    with _no_config_or_sqlite(), patch("wcl_core.user_auth.UserTokenManager", side_effect=refuse):
        with pytest.raises(ReferenceAuthRequired):
            RaidService(AppContext.headless(MagicMock(), storage=lambda: repo)).analyze(CODE, reference=True)

        user = MagicMock(name="member's WarcraftLogsClient")
        ctx = AppContext.headless(MagicMock(), storage=lambda: repo, user_client=lambda: user)
        with patch("wcl_app.raids.analyze_raid", side_effect=lambda *a, **k: _fake_analysis(CODE)) as analyze:
            RaidService(ctx).analyze(CODE, reference=True)
    assert analyze.call_args.args == (user, CODE)


def test_role_override_service_reanalyses_through_the_injected_client():
    repo = FakeRepository()
    ctx = AppContext.headless(MagicMock(), storage=lambda: repo)
    with _no_config_or_sqlite(), ctx.repository() as db:
        service = RoleOverrideService.from_context(ctx, db)
    assert service._analyze is not None and service._analyze.__self__.ctx is ctx


@pytest.mark.postgres
def test_raid_service_on_postgres_applies_saved_overrides(pg_empty_engine, sample_raid_analysis):
    from wcl_store.postgres import PostgresRaidRepository

    sample_raid_analysis.metadata.report_id = CODE
    client = MagicMock(name="host WarcraftLogsClient")
    ctx = AppContext.headless(client, storage=lambda: PostgresRaidRepository(pg_empty_engine))
    with ctx.repository() as repo:
        repo.set_role_override("StabbyRogue", "tank")

    with _no_config_or_sqlite(), patch("wcl_app.raids.analyze_raid", return_value=sample_raid_analysis) as analyze:
        RaidService(ctx).analyze_and_save(CODE)

    assert analyze.call_args.args == (client, CODE)
    assert analyze.call_args.kwargs["role_overrides"] == {"StabbyRogue": "tank"}
    assert RaidService(ctx).imported_codes() == {CODE}


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: use absolute wcl_app./wcl_core./wcl_store. imports"
            if node.module:
                names.append(node.module)
    return names


@pytest.mark.ears_ubiquitous
def test_req_core_app_001_app_imports_only_core_store_and_stdlib():
    """wcl-app imports no Qt, sqlite3, web, bot or desktop module (also enforced by lint-imports)."""
    forbidden = ("PySide6", "sqlite3", "fastapi", "discord", "warcraftlogs_client")
    for path in APP_SRC.rglob("*.py"):
        for name in _imports(path):
            assert name.split(".")[0] not in forbidden, f"{path.relative_to(APP_SRC)} imports {name}"


def test_importing_every_module_loads_no_desktop_qt_or_sqlite():
    code = (
        "import importlib, pkgutil, sys, wcl_app\n"
        "for m in pkgutil.walk_packages(wcl_app.__path__, 'wcl_app.'): importlib.import_module(m.name)\n"
        "bad = {'warcraftlogs_client', 'PySide6', 'sqlite3', 'sqlalchemy'} & {m.split('.')[0] for m in sys.modules}\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=APP_SRC.parent)


def _version(pyproject: Path) -> str:
    match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    assert match, pyproject
    return match.group(1)


def test_wcl_app_version_matches_the_app():
    assert _version(ROOT / "packages/wcl-app/pyproject.toml") == _version(ROOT / "pyproject.toml")


def test_wcl_app_depends_only_on_core_store_and_requests():
    text = (ROOT / "packages/wcl-app/pyproject.toml").read_text(encoding="utf-8")
    deps = re.search(r"^dependencies = \[(.*?)\]", text, re.M | re.S)
    assert deps
    assert re.findall(r'"([^"]+)"', deps.group(1)) == ["wcl-core", "wcl-store", "requests>=2.31.0"]


def test_release_script_bumps_the_wcl_app_version():
    script = (ROOT / "build_release.sh").read_text(encoding="utf-8")
    assert '"s/^version = .*/version = \\"${VERSION}\\"/" packages/wcl-app/pyproject.toml' in script
