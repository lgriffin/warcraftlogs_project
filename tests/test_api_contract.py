"""The shared packages' public API: every export is exercised by a test, and the surface is snapshotted.

Phase Q in ``guides/identity_and_profiles.md``. The Toads Hub and bot build on ``wcl_app``, ``wcl_store`` and the
``wcl_core`` test seam, so a rename or a dropped parameter there is a breaking change for them.
``tests/api_surface.txt`` holds one line per export, class member, dataclass field and signature. When the surface
changes on purpose, regenerate it with ``WCL_UPDATE_SURFACE=1 pytest tests/test_api_contract.py`` and commit the
file with the change; a line that disappears is a breaking change and the PR should say so.
"""

from __future__ import annotations

import ast
import difflib
import importlib
import inspect
import os
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
SNAPSHOT = TESTS / "api_surface.txt"
PACKAGES = ("wcl_app", "wcl_store", "wcl_core.http", "wcl_core.testing")


def _exports(package: str) -> list[str]:
    return list(importlib.import_module(package).__all__)


def _source_module(package: str, name: str) -> str:
    """The module an export is defined in, from the ``from X import name`` in the package (or the module itself)."""
    module = importlib.import_module(package)
    path = Path(inspect.getfile(module))
    if path.name != "__init__.py":
        return package
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and any(a.name == name for a in node.names):
            return importlib.util.resolve_name("." * node.level + (node.module or ""), package)
    raise LookupError(f"{package}.{name} is not imported in {path}")


def _tree(module: str) -> ast.Module:
    return ast.parse(Path(inspect.getfile(importlib.import_module(module))).read_text(encoding="utf-8"))


def _top_level(module: str, name: str) -> ast.stmt:
    for node in _tree(module).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return node
    raise LookupError(f"{name} is not defined at the top of {module}")


def _signature(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    kinds = {"property", "classmethod", "staticmethod", "contextmanager", "cached_property"}
    marks = "".join(f"@{ast.unparse(d)} " for d in func.decorator_list if ast.unparse(d).split(".")[-1] in kinds)
    returns = f" -> {ast.unparse(func.returns)}" if func.returns else ""
    return f"{marks}def {func.name}({ast.unparse(func.args)}){returns}"


def _public(name: str) -> bool:
    return not name.startswith("_") or name == "__init__"


def _members(cls: type) -> list[str]:
    """The class's own and inherited public fields and methods, from the source of each class in its MRO."""
    lines: list[str] = []
    seen: set[str] = set()
    for klass in inspect.getmro(cls):
        if not klass.__module__.startswith(("wcl_", "warcraftlogs_client")):
            continue
        node = _top_level(klass.__module__, klass.__name__)
        assert isinstance(node, ast.ClassDef)
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and _public(item.target.id):
                name, line = item.target.id, ast.unparse(item.annotation)
                line += f" = {ast.unparse(item.value)}" if item.value is not None else ""
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and _public(item.name):
                name, line = item.name, _signature(item)
            else:
                continue
            if name not in seen:
                seen.add(name)
                lines.append(f"{cls.__name__}.{name}: {line}")
    return lines


def _describe(package: str, name: str) -> list[str]:
    node = _top_level(_source_module(package, name), name)
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        marks = "".join(f"@{ast.unparse(d)} " for d in node.decorator_list)
        head = f"{name}: {marks}class {name}({bases})" if bases else f"{name}: {marks}class {name}"
        return [head, *_members(getattr(importlib.import_module(package), name))]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [f"{name}: {_signature(node)}"]
    return [f"{name}: {ast.unparse(node)}"]


def surface() -> str:
    lines = []
    for package in PACKAGES:
        lines.append(f"[{package}]")
        lines += [f"{package}.{line}" for name in sorted(_exports(package)) for line in _describe(package, name)]
    return "\n".join(lines) + "\n"


def test_the_public_surface_matches_the_snapshot():
    current = surface()
    if os.environ.get("WCL_UPDATE_SURFACE"):
        SNAPSHOT.write_text(current, encoding="utf-8")
    recorded = SNAPSHOT.read_text(encoding="utf-8")
    removed = sorted(set(recorded.splitlines()) - set(current.splitlines()))
    diff = "\n".join(
        difflib.unified_diff(recorded.splitlines(), current.splitlines(), "recorded", "current", lineterm="")
    )
    assert current == recorded, (
        "the public API changed; if that is intended, run WCL_UPDATE_SURFACE=1 pytest tests/test_api_contract.py"
        + (f"\nBREAKING, these lines are gone: {removed}" if removed else "")
        + f"\n{diff}"
    )


def _test_sources() -> str:
    skip = {Path(__file__).resolve()}
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(TESTS.rglob("*.py")) if p.resolve() not in skip)


def _service_methods() -> list[str]:
    """``wcl_app.<Service>.<method>`` and ``RaidRepository.<method>`` for each public method a host calls."""
    import wcl_app
    from wcl_store import RaidRepository

    owners = [getattr(wcl_app, n) for n in wcl_app.__all__ if n.endswith("Service")] + [RaidRepository]
    return [
        f"{owner.__name__}.{name}"
        for owner in owners
        for name, value in vars(owner).items()
        if not name.startswith("_") and (inspect.isfunction(value) or isinstance(value, (classmethod, staticmethod)))
    ]


def test_every_export_is_named_by_a_test():
    """ESI.ts's export coverage: a public name no test mentions is one nothing checks."""
    tests = _test_sources()
    unused = [f"{p}.{n}" for p in PACKAGES for n in _exports(p) if not re.search(rf"\b{re.escape(n)}\b", tests)]
    assert unused == [], "add a test that uses these: " + ", ".join(unused)


def test_every_service_and_repository_method_is_called_by_a_test():
    tests = _test_sources()
    uncalled = [m for m in _service_methods() if not re.search(rf"\.{re.escape(m.split('.')[1])}\b", tests)]
    assert uncalled == [], "add a test that calls these: " + ", ".join(uncalled)


@pytest.mark.parametrize("package", PACKAGES)
def test_every_export_is_defined_where_the_package_says(package):
    for name in _exports(package):
        assert _describe(package, name), name
