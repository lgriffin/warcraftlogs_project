"""One entry point for every check CI runs, so a local run and CI run the same commands.

    python scripts/dev.py check      # everything the blocking CI jobs run, fastest first
    python scripts/dev.py fix        # apply Ruff's fixes and formatting
    python scripts/dev.py <task>...  # any tasks below, in order

CI calls these tasks too, so the commands are defined once. Stdlib only, so it runs before `pip install`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The code under analysis. The GUI is excluded from mypy, vulture and coverage (see pyproject.toml).
SOURCES = [
    "warcraftlogs_client/",
    "packages/wcl-core/src/",
    "packages/wcl-store/src/",
    "packages/wcl-app/src/",
]
COVERAGE = ["--cov=warcraftlogs_client", "--cov=wcl_core", "--cov=wcl_store", "--cov=wcl_app"]

TASKS: dict[str, tuple[str, list[list[str]]]] = {
    "format": ("Ruff format check", [["ruff", "format", "--check", "."]]),
    "lint": ("Ruff lint, security rules and complexity", [["ruff", "check", "."]]),
    "spelling": ("codespell", [["codespell", *SOURCES, "tests/"]]),
    "deadcode": (
        "vulture dead code",
        [
            [
                "vulture",
                *SOURCES,
                "vulture_whitelist.py",
                "--min-confidence",
                "80",
                "--exclude",
                "warcraftlogs_client/gui/",
            ]
        ],
    ),
    "imports": ("import-linter package contracts", [["lint-imports"]]),
    "types": ("mypy", [["mypy", *SOURCES, "--exclude", "gui/"]]),
    "security": (
        "bandit and security tests",
        [
            ["bandit", "-q", "-c", "pyproject.toml", "-r", *SOURCES],
            ["pytest", "-q", "--tb=short", "tests/test_security.py"],
        ],
    ),
    "audit": ("pip-audit (needs network)", [["pip-audit", "--skip-editable", "--desc", "on"]]),
    "test": (
        "unit and BDD tests with coverage",
        [
            [
                "pytest",
                "-q",
                "--tb=short",
                "-rs",
                *COVERAGE,
                "--cov-report=term-missing:skip-covered",
                "--cov-config=pyproject.toml",
                "--ignore=tests/gui",
                "--ignore=tests/integration/test_live_api.py",
            ]
        ],
    ),
    "fuzz": ("hypothesis fuzz tests", [["pytest", "-q", "--tb=short", "tests/fuzz/"]]),
    "gui": ("GUI tests (needs the gui extra and a display)", [["pytest", "-q", "--tb=short", "tests/gui/"]]),
}

# What `check` runs: every CI check that needs no network or services, cheapest first so it fails fast.
# `test` already collects tests/fuzz (as CI's test job does, for coverage), so `fuzz` stays a separate task.
CHECK = ["format", "lint", "spelling", "imports", "deadcode", "types", "security", "test"]

FIX = [["ruff", "check", "--fix", "."], ["ruff", "format", "."]]


def _run(commands: list[list[str]]) -> bool:
    for command in commands:
        if shutil.which(command[0]) is None:
            print(f'  {command[0]} is not installed; run: pip install -e ".[dev]"', file=sys.stderr)
            return False
        if subprocess.run(command, cwd=ROOT, check=False).returncode != 0:
            return False
    return True


def run_tasks(names: list[str], keep_going: bool) -> int:
    failed = []
    for name in names:
        label, commands = TASKS[name]
        print(f"\n==> {name}: {label}", flush=True)
        started = time.monotonic()
        ok = _run(commands)
        print(f"<== {name}: {'ok' if ok else 'FAILED'} ({time.monotonic() - started:.1f}s)", flush=True)
        if not ok:
            failed.append(name)
            if not keep_going:
                break
    if failed:
        print(f"\nFailed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"\nAll passed: {', '.join(names)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "tasks",
        nargs="*",
        metavar="task",
        help=f"check, fix, or any of: {', '.join(TASKS)} (default: check)",
    )
    parser.add_argument("-k", "--keep-going", action="store_true", help="run every task even after one fails")
    args = parser.parse_args(argv)

    tasks = args.tasks or ["check"]
    unknown = sorted(set(tasks) - {"check", "fix", *TASKS})
    if unknown:
        parser.error(f"unknown task: {', '.join(unknown)}")
    if tasks == ["fix"]:
        return 0 if _run(FIX) else 1
    names = [name for task in tasks for name in (CHECK if task == "check" else [task])]
    if "fix" in names:
        parser.error("run fix on its own")
    return run_tasks(names, args.keep_going)


if __name__ == "__main__":
    sys.exit(main())
