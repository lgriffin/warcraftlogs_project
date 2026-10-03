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


def _name(node: ast.AST) -> str:
    """The last part of a dotted name: ``pytest.mark.skip`` -> ``skip``."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _is_pytest(node: ast.AST, *path: str) -> bool:
    return ast.unparse(node) == ".".join(("pytest", *path))


def unexplained_skips(tree: ast.AST) -> Iterator[int]:
    """Lines of skip/xfail marks and pytest.skip/xfail/fail calls that do not say why."""
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _name(node.func)
            keywords = {k.arg for k in node.keywords}
            if name in SKIP_MARKS and _is_pytest(node.func, "mark", name):
                if "reason" not in keywords and not (name == "skip" and node.args):
                    yield node.lineno
            elif (
                name in SKIP_CALLS
                and _is_pytest(node.func, name)
                and not node.args
                and not keywords & {"reason", "msg"}
            ):
                yield node.lineno
        elif isinstance(node, ast.Attribute) and id(node) not in called:
            if node.attr in SKIP_MARKS and _is_pytest(node, "mark", node.attr):
                yield node.lineno


def _checks(node: ast.AST, helpers: set[str]) -> bool:
    for child in ast.walk(node):
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
            body = ast.Module(body=node.body, type_ignores=[])
            raises = any(isinstance(n, ast.Raise) for n in ast.walk(body))
            keeps = node.name is not None and any(isinstance(n, ast.Name) and n.id == node.name for n in ast.walk(body))
            if not raises and not keeps:
                yield node.lineno
        elif isinstance(node, ast.Call) and _name(node.func) == "suppress":
            if any(_name(a) in BROAD for a in node.args):
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


def _lines(rule, source: str) -> list:
    return list(rule(ast.parse(source)))


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
"""
    assert _lines(unexplained_skips, source) == [2, 4, 6, 9]


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
"""
    assert _lines(assertion_free_tests, source) == [(6, "test_bare"), (7, "test_builds_only")]


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
"""
    assert _lines(swallowed_exceptions, source) == [3, 5, 7, 8]
