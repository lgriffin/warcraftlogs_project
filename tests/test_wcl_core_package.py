"""wcl-core as a standalone package: aliases, packaged data, host directory, headless imports."""

import ast
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
import wcl_core
from wcl_core import paths

CORE_SRC = Path(wcl_core.__file__).resolve().parent
MOVED = [
    "analysis",
    "auth",
    "cache",
    "client",
    "config",
    "consumes_analysis",
    "dynamic_role_parser",
    "models",
    "paths",
    "spell_manager",
    "common.data",
    "common.errors",
]


@pytest.mark.parametrize("name", MOVED)
def test_old_import_path_is_the_same_module(name):
    assert importlib.import_module(f"warcraftlogs_client.{name}") is importlib.import_module(f"wcl_core.{name}")


@pytest.mark.parametrize(
    "path",
    [
        paths.get_spell_data_dir() / "spell_names.json",
        paths.get_spell_data_dir() / "spell_aliases.json",
        paths.get_consumes_config_path(),
        paths.get_interrupt_config_path(),
        paths.get_debuff_config_path(),
        paths.get_totem_config_path(),
        paths.get_cooldowns_config_path(),
    ],
    ids=lambda p: p.name,
)
def test_analysis_data_ships_inside_the_package(path):
    assert path.is_file()
    assert CORE_SRC in path.resolve().parents


def test_desktop_keeps_the_project_root_as_app_dir():
    import warcraftlogs_client

    assert paths.get_app_dir() == Path(warcraftlogs_client.__file__).resolve().parent.parent


def test_standalone_host_uses_wcl_app_dir(tmp_path):
    """Without warcraftlogs_client (as in the Toads Hub worker), $WCL_APP_DIR picks the host directory."""
    code = (
        "import sys; from wcl_core import paths, analysis; "
        "assert 'warcraftlogs_client' not in sys.modules; "
        "print(paths.get_app_dir()); print(paths.get_consumes_config_path().is_file())"
    )
    env = {"WCL_APP_DIR": str(tmp_path), "PATH": ""}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True, cwd=tmp_path
    ).stdout.split()
    assert out == [str(tmp_path), "True"]


FORBIDDEN = ("PySide6", "sqlite3", "sqlalchemy", "warcraftlogs_client")


@pytest.mark.ears_ubiquitous
def test_req_core_arch_001_core_imports_no_qt_or_sqlite():
    """REQ-CORE-ARCH-001: wcl-core imports no Qt, SQLite or SQLAlchemy module (also enforced by lint-imports)."""
    for path in CORE_SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in FORBIDDEN, f"{path.name} imports {name}"


def test_wcl_core_version_matches_the_app():
    root = Path(__file__).resolve().parent.parent

    def version(pyproject: Path) -> str:
        match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
        assert match, pyproject
        return match.group(1)

    assert version(root / "packages/wcl-core/pyproject.toml") == version(root / "pyproject.toml")
