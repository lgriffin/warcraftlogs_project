"""The test suite keeps itself honest: every skip says why, every test checks something, no test hides a failure.

A lint over ``tests/`` (phase Q in ``guides/identity_and_profiles.md``). Each rule has a test of its own on a small
source, so a rule that stops matching fails here rather than letting the suite rot quietly.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

TESTS = Path(__file__).parent

# pytest.mark.<name>(...) needs reason=; skip may give it as its first argument instead.
SKIP_MARKS = {"skip", "skipif", "xfail"}
# pytest.<name>(...) inside a test needs a message.
SKIP_CALLS = {"skip", "xfail", "fail"}
# Calls that check something without a bare assert: pytest's context managers, pytest-qt's signal waits.
CHECKING_CALLS = {"raises", "warns", "deprecated_call", "waitSignal", "waitSignals", "waitUntil", "assertNotEmitted"}
BROAD = {"Exception", "BaseException"}
# Step definitions mock only at the HTTP seam: wcl_core.testing's fakes, never unittest.mock or a patched ``requests``.
# This list may only shrink; each entry says what it still mocks.
MOCK_MODULES = {"unittest.mock", "mock"}
SERVICE_MODULES = ("wcl_app", "warcraftlogs_client.services")
KNOWN_STEP_MOCKS = {
    "conftest.py": "the 'a mock WCL client' step behind encounter_analysis.feature",
    "test_raid_analysis.py": "a MagicMock client for analyze_raid",
    "test_services_package.py": "its headless host script patches wcl_app.raids.analyze_raid",
    "test_updater.py": "GitHub releases and subprocess.Popen, not Warcraft Logs",
}


def _name(node: ast.AST) -> str:
    """The last part of a dotted name: ``pytest.mark.skip`` -> ``skip``."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _is_pytest(node: ast.AST, *path: str) -> bool:
    return ast.unparse(node) == ".".join(("pytest", *path))


def _says_why(node: ast.AST | None) -> bool:
    """A reason is given and is not a blank string literal."""
    if node is None:
        return False
    return not (isinstance(node, ast.Constant) and isinstance(node.value, str) and not node.value.strip())


def _reason(call: ast.Call, *keywords: str, positional: bool) -> ast.AST | None:
    given = next((k.value for k in call.keywords if k.arg in keywords), None)
    if given is None and positional and call.args:
        given = call.args[0]
    return given


def unexplained_skips(tree: ast.AST) -> Iterator[int]:
    """Lines of skip/xfail marks and pytest.skip/xfail/fail calls that do not say why."""
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _name(node.func)
            if name in SKIP_MARKS and _is_pytest(node.func, "mark", name):
                if not _says_why(_reason(node, "reason", positional=name == "skip")):
                    yield node.lineno
            elif name in SKIP_CALLS and _is_pytest(node.func, name):
                if not _says_why(_reason(node, "reason", "msg", positional=True)):
                    yield node.lineno
        elif isinstance(node, ast.Attribute) and id(node) not in called:
            if node.attr in SKIP_MARKS and _is_pytest(node, "mark", node.attr):
                yield node.lineno


def _runs(statements: list[ast.stmt]) -> Iterator[ast.AST]:
    """The nodes these statements execute: like ``ast.walk``, but not into a nested def, lambda or class,
    whose body runs only if something calls it."""
    stack: list[ast.AST] = list(statements)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _checks(func: ast.FunctionDef | ast.AsyncFunctionDef, helpers: set[str]) -> bool:
    for child in _runs(func.body):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Call):
            name = _name(child.func)
            if name in CHECKING_CALLS or name.startswith("assert_") or name in helpers:
                return True
    return False


def _is_scenario(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """pytest-bdd binds a scenario to a test function whose body is empty; its steps hold the asserts."""
    return any(_name(d.func if isinstance(d, ast.Call) else d) == "scenario" for d in func.decorator_list)


def assertion_free_tests(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """Test functions with no assert, no checking call and no call to a module helper that asserts."""
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    helpers = {f.name for f in functions if not f.name.startswith("test") and _checks(f, set())}
    for func in functions:
        if func.name.startswith("test") and not _is_scenario(func) and not _checks(func, helpers):
            yield func.lineno, func.name


def _broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(_name(t) in BROAD for t in types)


def swallowed_exceptions(tree: ast.AST) -> Iterator[int]:
    """Lines that catch every exception and drop it: a broad except that neither re-raises nor keeps the
    exception, or ``contextlib.suppress(Exception)``. Such a block also swallows a failing assert."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _broad(node):
            raises = any(isinstance(n, ast.Raise) for n in _runs(node.body))
            keeps = node.name is not None and any(
                isinstance(n, ast.Name) and n.id == node.name and isinstance(n.ctx, ast.Load) for n in _runs(node.body)
            )
            if not raises and not keeps:
                yield node.lineno
        elif isinstance(node, ast.Call) and _name(node.func) == "suppress":
            if any(_name(a) in BROAD for a in node.args):
                yield node.lineno


def _imported_names(tree: ast.AST) -> dict[str, str]:
    """The module path each imported name stands for: ``from wcl_app import raids as r`` gives ``r -> wcl_app.raids``."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _patch_target(call: ast.Call, imported: dict[str, str]) -> str:
    """The dotted path a ``patch(...)``, ``patch.object(...)`` or ``monkeypatch.setattr(...)`` call replaces in."""
    name = _name(call.func)
    if name not in {"patch", "object", "setattr"} or not call.args:
        return ""
    if name == "object" and not (isinstance(call.func, ast.Attribute) and _name(call.func.value) == "patch"):
        return ""
    target = call.args[0]
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        return target.value
    head, _, rest = ast.unparse(target).partition(".")
    resolved = imported.get(head, head)
    return f"{resolved}.{rest}" if rest else resolved


def _uses_mock(node: ast.AST) -> bool:
    if isinstance(node, ast.ImportFrom):
        return node.module in MOCK_MODULES or (node.module == "unittest" and any(a.name == "mock" for a in node.names))
    if isinstance(node, ast.Import):
        return any(alias.name in MOCK_MODULES for alias in node.names)
    if isinstance(node, ast.Attribute):
        return ast.unparse(node) == "unittest.mock"
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and "unittest.mock" in node.value


def mocks_past_the_seam(tree: ast.AST) -> Iterator[int]:
    """Lines that mock somewhere other than the HTTP seam: ``unittest.mock`` (imported, or in a script a test runs),
    or patching ``requests`` or a ``wcl_app`` service, however the target was imported."""
    imported = _imported_names(tree)
    for node in ast.walk(tree):
        if _uses_mock(node):
            yield node.lineno
        elif isinstance(node, ast.Call):
            target = _patch_target(node, imported)
            if "requests" in target.split(".") or target.startswith(SERVICE_MODULES):
                yield node.lineno


def _sources() -> Iterator[tuple[str, ast.AST]]:
    for path in sorted(TESTS.rglob("*.py")):
        yield path.relative_to(TESTS).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def test_every_skip_and_xfail_says_why():
    found = [f"{path}:{line}" for path, tree in _sources() for line in unexplained_skips(tree)]
    assert found == [], "give these a reason=: " + ", ".join(found)


def test_every_test_checks_something():
    found = [f"{path}:{line} {name}" for path, tree in _sources() for line, name in assertion_free_tests(tree)]
    assert found == [], "these tests assert nothing: " + ", ".join(found)


def test_no_test_swallows_every_exception():
    found = [f"{path}:{line}" for path, tree in _sources() for line in swallowed_exceptions(tree)]
    assert found == [], "catch the exception you expect, or keep it to assert on: " + ", ".join(found)


def test_step_definitions_mock_only_at_the_http_seam():
    """Phase Q's ``lint:bdd-seam``: BDD steps run the real client against ``wcl_core.testing``'s fakes."""
    steps = TESTS / "step_defs"
    found = {
        path.name
        for path in sorted(steps.glob("*.py"))
        if any(mocks_past_the_seam(ast.parse(path.read_text(encoding="utf-8"))))
    }
    new = sorted(found - KNOWN_STEP_MOCKS.keys())
    assert new == [], "use wcl_core.testing's FakeWarcraftLogs or FakeDiscord instead of mocking: " + ", ".join(new)
    gone = sorted(KNOWN_STEP_MOCKS.keys() - found)
    assert gone == [], "these no longer mock; drop them from KNOWN_STEP_MOCKS: " + ", ".join(gone)


def _lines(rule, source: str) -> list:
    return sorted(rule(ast.parse(source)))


def test_the_skip_rule_wants_a_reason_on_marks_and_calls():
    source = """
@pytest.mark.skip
def test_a(): ...
@pytest.mark.skipif(sys.platform == "win32")
def test_b(): ...
@pytest.mark.xfail(strict=True)
def test_c(): ...
def test_d():
    pytest.skip()
@pytest.mark.skip("flaky upstream")
@pytest.mark.skipif(True, reason="needs Postgres")
@pytest.mark.xfail(reason="bug 12")
def test_e():
    pytest.skip("no network")
    pytest.fail(msg="boom")
    pytest.skip(reason=f"needs {thing}")
@pytest.mark.skip(reason="")
@pytest.mark.xfail(reason="  ")
def test_f():
    pytest.skip("")
"""
    assert _lines(unexplained_skips, source) == [2, 4, 6, 9, 17, 18, 20]


def test_the_check_rule_accepts_asserts_checking_calls_and_asserting_helpers():
    source = """
def _holy(x):
    assert x
def _build():
    return 1
def test_bare(): run()
def test_builds_only(): _build()
def test_assert(): assert run()
def test_raises():
    with pytest.raises(ValueError): run()
def test_mock(m): m.assert_called_once_with(1)
def test_signal(qtbot, w):
    with qtbot.waitSignal(w.done): run()
def test_helper(): _holy(1)
@scenario("a.feature", "A")
def test_bdd(): pass
def test_defines_but_never_calls():
    def inner(): assert run()
    lambda: _holy(1)
    class Probe:
        def check(self): assert run()
def test_calls_a_nested_helper():
    def _seen(x): assert x
    _seen(run())
"""
    assert _lines(assertion_free_tests, source) == [
        (6, "test_bare"),
        (7, "test_builds_only"),
        (17, "test_defines_but_never_calls"),
    ]


def test_the_swallow_rule_flags_broad_catches_that_drop_the_exception():
    source = """
try: run()
except Exception: pass
try: run()
except: pass
try: run()
except (OSError, BaseException): log()
with contextlib.suppress(Exception): run()
try: run()
except ValueError: pass
try: run()
except Exception as e: error = e
try: run()
except Exception: raise
with contextlib.suppress(KeyError): run()
try: run()
except Exception:
    def later(): raise
try: run()
except Exception as e: e = None
try: run()
except Exception as e: del e
"""
    assert _lines(swallowed_exceptions, source) == [3, 5, 7, 8, 17, 20, 22]


def test_the_seam_rule_flags_mock_imports_and_patched_requests_or_services():
    source = """
from unittest.mock import MagicMock
import unittest.mock
HOST = "from unittest.mock import patch"
patch("requests.post")
patch("warcraftlogs_client.client.requests.post")
monkeypatch.setattr(discord_auth.requests, "post", post)
monkeypatch.setattr("wcl_app.raids.analyze_raid", fake)
patch.object(updater.requests, "get")
from unittest import mock as m
x = unittest.mock.MagicMock()
monkeypatch.setattr(RaidService, "analyze_and_save", fake)
monkeypatch.setattr(svc, "load", fake)
monkeypatch.setattr(http, "get", fake)
monkeypatch.setattr(webbrowser, "open", browser)
monkeypatch.setattr(config, "load_config", load)
monkeypatch.setenv("DISCORD_OAUTH_URL", url)
with wcl.install(): run()
other.object(requests, "get")
from wcl_app import RaidService
import wcl_app.characters as svc
from wcl_core import config, http
"""
    assert _lines(mocks_past_the_seam, source) == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
