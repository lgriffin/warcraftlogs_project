"""Step definitions for the storage contract feature (REQ-CORE-STORE-001).

The scenarios run tests/test_store_contract.py itself, unchanged, in a child pytest per backend, so the
requirement is checked against the real contract module rather than a copy of its assertions.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.conftest import PG_URL_ENV

scenarios("storage.feature")

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "tests/test_store_contract.py"


def _run_contract(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", CONTRACT, "-q", "-p", "no:cacheprovider", *args],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )


@given(parsers.parse("the {backend} storage backend is available"))
def backend_available(backend):
    if backend == "postgres":
        if not os.environ.get(PG_URL_ENV):
            pytest.skip(f"Postgres backend not tested: set {PG_URL_ENV} to a Postgres URL to run it")
        for module in ("sqlalchemy", "psycopg", "alembic"):
            pytest.importorskip(module, reason=f"Postgres backend not tested: {module} missing, install .[postgres]")


@when(
    parsers.parse("the storage contract test module runs against the {backend} backend"),
    target_fixture="contract_run",
)
def run_against(backend):
    # Test ids end in [sqlite] or [postgres]; the cross-backend test carries the postgres marker.
    return _run_contract("-k", backend)


@when(
    "the same raids, player pages and role overrides are written to both backends",
    target_fixture="contract_run",
)
def run_side_by_side():
    return _run_contract("-k", "test_both_backends_return_the_same_results")


def _assert_all_passed(run: subprocess.CompletedProcess) -> None:
    summary = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
    assert run.returncode == 0, run.stdout + run.stderr
    assert re.search(r"\d+ passed", summary), summary
    assert not re.search(r"skipped|failed|error", summary), summary


@then("every contract test should pass with none skipped")
def all_passed(contract_run):
    _assert_all_passed(contract_run)


@then("every read method should return the same rows on both")
def same_rows(contract_run):
    _assert_all_passed(contract_run)
