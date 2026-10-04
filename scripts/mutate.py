"""Mutation testing for wcl-core: plant one small bug at a time and check the tests catch it.

    python scripts/mutate.py                    # every module in [tool.wcl.mutation], checked against its floor
    python scripts/mutate.py game_version -v    # one module, listing the mutants that survived

Each target module is copied into a scratch directory with its package, one site is changed (a comparison, an
operator, a boolean, a constant, a return value, an ``if``), and the module's tests run against the copy through
``PYTHONPATH``. A mutant is killed when the tests fail or time out. The score is killed / total, and a module below
its floor in ``pyproject.toml`` fails the run. Floors only go up: raise one when a run beats it.
Stdlib only (plus ``tomli`` on Python 3.10), so it runs anywhere the tests run.
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent
CORE_SRC = ROOT / "packages" / "wcl-core" / "src"
# Each worker is a pytest process with its own package copy; past a few, contention only stretches runs toward
# the timeout. -j overrides it.
DEFAULT_JOBS = min(os.cpu_count() or 1, 4)

SWAPS: dict[type, type] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
    ast.FloorDiv: ast.Mult,
    ast.And: ast.Or,
    ast.Or: ast.And,
}


@dataclass(frozen=True)
class Mutant:
    index: int
    line: int
    change: str


class _Mutator(ast.NodeTransformer):
    """Walks a module numbering every mutable site; with ``target`` set, changes only that site."""

    def __init__(self, target: int | None = None) -> None:
        self.target = target
        self.sites: list[Mutant] = []

    def _site(self, node: ast.AST, change: str) -> bool:
        index = len(self.sites)
        self.sites.append(Mutant(index, getattr(node, "lineno", 0), change))
        return index == self.target

    # Annotations, docstrings and __all__ are not behaviour.
    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        if node.value is not None:
            node.value = self.visit(node.value)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.args = self.visit(node.args)
        node.body = _docstring(node.body) + [self.visit(s) for s in _without_docstring(node.body)]
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        return node

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.body = _docstring(node.body) + [self.visit(s) for s in _without_docstring(node.body)]
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        return node

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return node
        return self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> ast.AST:
        # A logging or print call changes no result the tests can see; leave it alone.
        if isinstance(node.value, ast.Call) and _logs(node.value):
            return node
        return self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        for i, op in enumerate(node.ops):
            swap = SWAPS.get(type(op))
            if swap and self._site(node, f"{type(op).__name__} -> {swap.__name__}"):
                node.ops[i] = swap()
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        swap = SWAPS.get(type(node.op))
        if swap and not _is_string(node) and self._site(node, f"{type(node.op).__name__} -> {swap.__name__}"):
            node.op = swap()
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        swap = SWAPS[type(node.op)]
        if self._site(node, f"{type(node.op).__name__} -> {swap.__name__}"):
            node.op = swap()
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self._site(node, "drop not"):
            return node.operand
        return node

    def visit_If(self, node: ast.If) -> ast.AST:
        self.generic_visit(node)
        if self._site(node, "negate if"):
            node.test = ast.UnaryOp(ast.Not(), node.test)
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, bool):
            if self._site(node, f"{node.value} -> {not node.value}"):
                return ast.Constant(not node.value)
        elif isinstance(node.value, int) and self._site(node, f"{node.value} -> {node.value + 1}"):
            return ast.Constant(node.value + 1)
        return node

    def visit_Return(self, node: ast.Return) -> ast.AST:
        self.generic_visit(node)
        if node.value is not None and not _is_none(node.value) and self._site(node, "return None"):
            node.value = ast.Constant(None)
        return node


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """The body with its docstring left as it is and everything after it visited."""
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return body


def _docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    return body[: len(body) - len(_without_docstring(body))]


def _logs(call: ast.Call) -> bool:
    func = ast.unparse(call.func)
    return func == "print" or func.startswith(("logger.", "logging.", "log."))


def _is_string(node: ast.BinOp) -> bool:
    return any(
        isinstance(side, (ast.Constant, ast.JoinedStr)) and isinstance(getattr(side, "value", ""), str)
        for side in (node.left, node.right)
    )


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def mutants(source: str) -> list[Mutant]:
    mutator = _Mutator()
    mutator.visit(ast.parse(source))
    return mutator.sites


def mutate(source: str, index: int) -> str:
    tree = _Mutator(index).visit(ast.parse(source))
    return ast.unparse(ast.fix_missing_locations(tree))


@dataclass
class Result:
    module: str
    total: int
    survivors: list[Mutant]

    @property
    def score(self) -> float:
        return 1.0 if not self.total else (self.total - len(self.survivors)) / self.total


def _config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["wcl"]["mutation"]


def _env(src: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(src), os.environ.get("PYTHONPATH", "")]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _imports_the_copy(src: Path) -> bool:
    """The copy in ``src`` shadows the installed wcl_core; otherwise every mutant would run against the original."""
    probe = [sys.executable, "-c", "import wcl_core; print(wcl_core.__file__)"]
    run = subprocess.run(probe, cwd=ROOT, env=_env(src), capture_output=True, text=True, check=False)
    return run.returncode == 0 and src.resolve() in Path(run.stdout.strip()).resolve().parents


def _pytest(tests: list[str], src: Path, timeout: float, *, show_failure: bool = False) -> bool:
    """True when the tests pass against the package copy in ``src``; ``show_failure`` prints pytest's output."""
    env = _env(src)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-x",
        "-q",
        "-p",
        "no:cacheprovider",
        "--no-header",
        "-o",
        "addopts=",
        *tests,
    ]
    try:
        run = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        if show_failure:
            print(f"pytest timed out after {timeout:.0f}s", file=sys.stderr)
        return False
    if run.returncode and show_failure:
        sys.stderr.write(run.stdout.decode(errors="replace") + run.stderr.decode(errors="replace"))
    return run.returncode == 0


def run_module(module: str, tests: list[str], jobs: int) -> Result:
    path = CORE_SRC / "wcl_core" / f"{module}.py"
    source = path.read_text(encoding="utf-8")
    sites = mutants(source)
    jobs = max(1, min(jobs, len(sites)))
    with tempfile.TemporaryDirectory() as scratch:
        copies = []
        for worker in range(jobs):
            copy = Path(scratch) / str(worker)
            shutil.copytree(CORE_SRC / "wcl_core", copy / "wcl_core", ignore=shutil.ignore_patterns("__pycache__"))
            copies.append(copy)
        if not _imports_the_copy(copies[0]):
            raise SystemExit("the installed wcl_core shadows the mutated copy; check PYTHONPATH")
        start = time.monotonic()
        if not _pytest(tests, copies[0], timeout=600, show_failure=True):
            raise SystemExit(f"{module}: the tests fail before any mutation: {' '.join(tests)}")
        timeout = max(10.0, 3 * (time.monotonic() - start))

        def survives(work: tuple[int, Mutant]) -> Mutant | None:
            worker, site = work
            target = copies[worker] / "wcl_core" / f"{module}.py"
            target.write_text(mutate(source, site.index), encoding="utf-8")
            try:
                return site if _pytest(tests, copies[worker], timeout) else None
            finally:
                target.write_text(source, encoding="utf-8")

        batches = [[(w, s) for s in sites[w::jobs]] for w in range(jobs)]
        with ThreadPoolExecutor(jobs) as pool:
            found = pool.map(lambda batch: [survives(item) for item in batch], batches)
            survivors = sorted((s for batch in found for s in batch if s), key=lambda s: s.index)
    return Result(module, len(sites), survivors)


def _selected(config: dict, names: list[str]) -> Iterator[tuple[str, list[str]]]:
    targets = config["targets"]
    for name in names or sorted(targets):
        if name not in targets:
            raise SystemExit(f"{name} is not a mutation target; add it to [tool.wcl.mutation.targets]")
        yield name, targets[name]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("modules", nargs="*", help="wcl_core modules to mutate (default: every target)")
    parser.add_argument("-v", "--verbose", action="store_true", help="list surviving mutants")
    parser.add_argument("-j", "--jobs", type=int, default=DEFAULT_JOBS, help="parallel test runs")
    args = parser.parse_args(argv)
    config = _config()
    below = []
    for module, tests in _selected(config, args.modules):
        result = run_module(module, tests, max(1, args.jobs))
        floor = config["floors"].get(module, 0.0)
        verdict = "below floor" if result.score < floor else "ok"
        print(
            f"{module}: {result.score:.0%} killed ({result.total - len(result.survivors)}/{result.total}), "
            f"floor {floor:.0%}: {verdict}",
            flush=True,
        )
        if args.verbose:
            for site in result.survivors:
                print(f"  survived: wcl_core/{module}.py:{site.line} {site.change}")
        if result.score < floor:
            below.append(module)
    if below:
        print("below their floor: " + ", ".join(below))
    return 1 if below else 0


if __name__ == "__main__":
    sys.exit(main())
