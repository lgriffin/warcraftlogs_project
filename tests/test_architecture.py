"""Layer-boundary checks for the clean architecture (REQ-ARCH-LAYERS-001).

Layers, innermost first. Each layer may import only itself and the layers inside it:

    core        WCL API client, auth, config, analysis engine, domain models (moving to ``wcl_core``)
    persistence ``wcl_store``: the RaidRepository protocol, PerformanceDB (SQLite) and Postgres backends
    services    ``wcl_app``: the application layer every frontend shares (``services/`` is its alias)
    presenters  text/Markdown renderers of domain models (``renderers/``)
    frontends   CLI, PySide6 desktop, updater

Frontends (CLI, desktop, and later the Toads API and bot) talk to ``services`` only. From core they may use
the shared vocabulary in ``FRONTEND_SAFE_CORE`` (domain models, errors, paths, version), never the client,
analysis engine, config, database or SQL directly.

Existing shortcuts are listed in ``KNOWN_VIOLATIONS``. The test fails on any new one, and also when a listed
one disappears, so the list can only shrink. When you move a view onto a service, delete its entry.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {
    "warcraftlogs_client": ROOT / "warcraftlogs_client",
    # After the wcl-core split the headless modules live here; old names stay as aliases.
    "wcl_core": ROOT / "packages" / "wcl-core" / "src" / "wcl_core",
    # The persistence layer. Its modules keep the "wcl_store." prefix so they never collide with core names.
    "wcl_store": ROOT / "packages" / "wcl-store" / "src" / "wcl_store",
    # The services layer, prefixed the same way so "wcl_app.context" never collides with a core name.
    "wcl_app": ROOT / "packages" / "wcl-app" / "src" / "wcl_app",
}
PREFIXED = {"wcl_store", "wcl_app"}

LAYER_ORDER = ["core", "persistence", "services", "presenters", "frontends"]

FRONTEND_SAFE_CORE = {"models", "common", "paths", "version"}

# Third-party modules a layer must never import, whatever the layer order says.
FORBIDDEN_EXTERNAL = {
    "core": {"PySide6", "sqlite3", "sqlalchemy", "fastapi", "discord"},
    "persistence": {"PySide6", "fastapi", "discord"},
    "services": {"PySide6", "sqlite3", "fastapi", "discord"},
    "presenters": {"PySide6", "sqlite3", "fastapi", "discord"},
}

# (importing module, imported module or external package) pairs that predate this check.
KNOWN_VIOLATIONS = {
    # CLI
    ("cli", "consumes_analysis"),
    ("cli", "database"),
    ("cli", "spell_manager"),
    # Desktop views still reach past services
    ("gui.boss_insights_view", "database"),
    ("gui.character_view", "database"),
    ("gui.download_view", "database"),
    ("gui.encounter_deep_dive_view", "client"),
    ("gui.encounter_worker", "analysis"),
    ("gui.encounter_worker", "client"),
    ("gui.find_character_view", "database"),
    ("gui.insights_view", "database"),
    ("gui.main_window", "auth"),
    ("gui.main_window", "client"),
    ("gui.main_window", "config"),
    ("gui.main_window", "database"),
    ("gui.raid_analysis_widget", "database"),
    ("gui.raid_cross_analysis_widget", "database"),
    ("gui.raid_diff_view", "database"),
    ("gui.raid_group_view", "database"),
    ("gui.raid_list_widget", "database"),
    ("gui.raids_view", "database"),
    ("gui.reference_view", "config"),
    ("gui.reference_view", "database"),
    ("gui.reference_view", "user_auth"),
    ("gui.settings_view", "auth"),
    ("gui.settings_view", "cache"),
    ("gui.settings_view", "config"),
    ("gui.settings_view", "database"),
    ("gui.settings_view", "user_auth"),
    ("gui.worker", "cache"),
}


def layer_of(name: str) -> str | None:
    """Layer of a package-relative module name such as ``gui.main_window`` or ``client``."""
    top = name.split(".")[0]
    if top in ("", "__init__"):
        return None
    if top in ("database", "wcl_store"):
        return "persistence"
    if top in ("services", "wcl_app"):
        return "services"
    if top == "renderers":
        return "presenters"
    if top in ("cli", "gui", "updater", "__main__"):
        return "frontends"
    # templates/ holds data only; everything else is headless core
    return "core"


def _module_name(pkg_dir: Path, path: Path, prefix: str = "") -> str:
    parts = list(path.relative_to(pkg_dir).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([prefix, *parts] if prefix else parts)


def _imports(pkg_dir: Path, path: Path, prefix: str = "") -> set[tuple[str, bool]]:
    """(target, internal) pairs: internal targets are package-relative, external ones are top-level names."""
    mod = _module_name(pkg_dir, path, prefix)
    # Package the file lives in, for resolving relative imports.
    here = mod.split(".") if path.name == "__init__.py" else mod.split(".")[:-1]
    here = [p for p in here if p]
    found: set[tuple[str, bool]] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            targets = [a.name for a in node.names]
            absolute = True
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = here[: len(here) - (node.level - 1)] if node.level > 1 else here
                prefix = ".".join(base + ([node.module] if node.module else []))
                # "from . import paths" imports submodules, so include each name
                targets = [f"{prefix}.{a.name}".lstrip(".") for a in node.names] if not node.module else [prefix]
                for t in targets:
                    found.add((t, True))
                continue
            targets = [node.module or ""]
            if node.module in PACKAGES:
                targets = [f"{node.module}.{a.name}" for a in node.names]
            absolute = True
        else:
            continue
        if absolute:
            for t in targets:
                top, _, rest = t.partition(".")
                if top in PREFIXED:
                    found.add((t, True))
                elif top in PACKAGES:
                    if rest:
                        found.add((rest, True))
                else:
                    found.add((top, False))
    return found


def collect_edges() -> dict[str, set[tuple[str, bool]]]:
    edges: dict[str, set[tuple[str, bool]]] = {}
    for name, pkg_dir in PACKAGES.items():
        if not pkg_dir.is_dir():
            continue
        prefix = name if name in PREFIXED else ""
        for path in sorted(pkg_dir.rglob("*.py")):
            mod = _module_name(pkg_dir, path, prefix) or "__init__"
            edges.setdefault(mod, set()).update(_imports(pkg_dir, path, prefix))
    return edges


def find_violations() -> set[tuple[str, str]]:
    violations: set[tuple[str, str]] = set()
    for mod, targets in collect_edges().items():
        src = layer_of(mod)
        if src is None:
            continue
        for target, internal in targets:
            if not internal:
                if target in FORBIDDEN_EXTERNAL.get(src, ()):
                    violations.add((mod, target))
                continue
            dst = layer_of(target)
            if dst is None:
                continue
            top = target.split(".")[0]
            outward = LAYER_ORDER.index(dst) > LAYER_ORDER.index(src)
            bypasses_services = src == "frontends" and dst in ("core", "persistence") and top not in FRONTEND_SAFE_CORE
            reads_storage = src == "presenters" and dst == "persistence"
            if outward or bypasses_services or reads_storage:
                violations.add((mod, top))
    return violations


def test_no_new_layer_violations():
    new = sorted(find_violations() - KNOWN_VIOLATIONS)
    assert not new, (
        "These imports cross a layer boundary. Frontends go through warcraftlogs_client/services/, "
        "and inner layers never import outer ones (see tests/test_architecture.py docstring):\n"
        + "\n".join(f"  {m} -> {t}" for m, t in new)
    )


def test_known_violations_are_not_stale():
    fixed = sorted(KNOWN_VIOLATIONS - find_violations())
    assert not fixed, "Fixed, so delete from KNOWN_VIOLATIONS:\n" + "\n".join(f"  {m} -> {t}" for m, t in fixed)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from ..database import PerformanceDB\n", ("database", True)),
        ("from . import paths\n", ("gui.paths", True)),
        ("from warcraftlogs_client import paths\n", ("paths", True)),
        ("from wcl_core.client import WarcraftLogsClient\n", ("client", True)),
        ("import sqlite3\n", ("sqlite3", False)),
        ("from wcl_store import StorageError\n", ("wcl_store.StorageError", True)),
        ("from wcl_store.sqlite import PerformanceDB\n", ("wcl_store.sqlite", True)),
    ],
)
def test_import_resolution(tmp_path, source, expected):
    pkg_dir = tmp_path / "warcraftlogs_client"
    (pkg_dir / "gui").mkdir(parents=True)
    f = pkg_dir / "gui" / "view.py"
    f.write_text(source, encoding="utf-8")
    assert expected in _imports(pkg_dir, f)


def test_detector_flags_a_frontend_reaching_the_database(monkeypatch):
    monkeypatch.setattr(
        "tests.test_architecture.collect_edges",
        lambda: {"gui.new_view": {("database", True), ("services", True), ("models", True)}},
    )
    assert find_violations() == {("gui.new_view", "database")}


def test_detector_flags_an_inner_layer_importing_an_outer_one(monkeypatch):
    monkeypatch.setattr(
        "tests.test_architecture.collect_edges",
        lambda: {
            "database": {("services.raids", True)},
            "analysis": {("renderers.markdown", True), ("PySide6", False)},
            "services.raids": {("gui.worker", True)},
        },
    )
    assert find_violations() == {
        ("database", "services"),
        ("analysis", "renderers"),
        ("analysis", "PySide6"),
        ("services.raids", "gui"),
    }


def test_wcl_store_modules_resolve_inside_their_package(tmp_path):
    pkg_dir = tmp_path / "wcl_store"
    (pkg_dir / "postgres").mkdir(parents=True)
    f = pkg_dir / "postgres" / "repository.py"
    f.write_text("from ..errors import StorageError\nfrom . import schema\n", encoding="utf-8")
    assert _imports(pkg_dir, f, "wcl_store") == {("wcl_store.errors", True), ("wcl_store.postgres.schema", True)}
    assert layer_of("wcl_store.postgres.schema") == "persistence"


def test_detector_flags_storage_reaching_outward_or_a_frontend_skipping_services(monkeypatch):
    monkeypatch.setattr(
        "tests.test_architecture.collect_edges",
        lambda: {
            "wcl_store.sqlite": {("services.raids", True), ("models", True), ("PySide6", False)},
            "services.roles": {("wcl_store", True), ("sqlite3", False)},
            "gui.new_view": {("wcl_store.sqlite", True)},
        },
    )
    assert find_violations() == {
        ("wcl_store.sqlite", "services"),
        ("wcl_store.sqlite", "PySide6"),
        ("services.roles", "sqlite3"),
        ("gui.new_view", "wcl_store"),
    }


def test_wcl_app_is_the_services_layer(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "wcl_app"
    pkg_dir.mkdir()
    f = pkg_dir / "roles.py"
    f.write_text(
        "from wcl_app.context import AppContext\nfrom wcl_core.analysis import OVERRIDE_ROLES\n", encoding="utf-8"
    )
    assert _imports(pkg_dir, f, "wcl_app") == {("wcl_app.context", True), ("analysis", True)}
    assert layer_of("wcl_app.raids") == "services"

    monkeypatch.setattr(
        "tests.test_architecture.collect_edges",
        lambda: {
            "wcl_app.raids": {("wcl_store", True), ("analysis", True), ("gui.worker", True), ("sqlite3", False)},
            "wcl_store.sqlite": {("wcl_app.context", True)},
            "gui.new_view": {("wcl_app", True)},
        },
    )
    assert find_violations() == {
        ("wcl_app.raids", "gui"),
        ("wcl_app.raids", "sqlite3"),
        ("wcl_store.sqlite", "wcl_app"),
    }
