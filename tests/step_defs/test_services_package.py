"""Step definitions for the services-package feature (the wcl-app requirement in services_package.feature).

A child interpreter plays the headless host: an import hook makes the desktop app, Qt and sqlite3 unimportable,
then it imports every wcl_app module and runs RaidService with its own client and an in-memory repository.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import wcl_app
from pytest_bdd import given, scenarios, then, when

scenarios("services_package.feature")

REQUIREMENT = "-".join(("REQ", "CORE", "APP", "001"))
BLOCKED = ("warcraftlogs_client", "PySide6", "sqlite3", "_sqlite3")

HOST = """
import importlib, importlib.abc, json, pkgutil, sys
from unittest.mock import MagicMock, patch

BLOCKED = set(sys.argv[1].split(","))


class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"{name} is not installed on this host")
        return None


sys.meta_path.insert(0, Block())
for mod in [m for m in sys.modules if m.split(".")[0] in BLOCKED]:
    del sys.modules[mod]

import wcl_app

for module in pkgutil.walk_packages(wcl_app.__path__, "wcl_app."):
    importlib.import_module(module.name)
from wcl_app import AppContext, RaidService


class Repo:
    saved = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_role_overrides_for_report(self, code):
        return {"Holy": "tank"}

    def import_raid(self, analysis, source="guild"):
        self.saved = [analysis.metadata.report_id, source]


repo, client = Repo(), MagicMock(name="host client")
ctx = AppContext.headless(client, storage=lambda: repo)
fake = MagicMock()
fake.metadata.report_id = "raidReport000001"
with patch("wcl_app.raids.analyze_raid", return_value=fake) as analyze:
    RaidService(ctx).analyze_and_save("raidReport000001")
print(json.dumps({
    "client_is_host": analyze.call_args.args[0] is client,
    "overrides": analyze.call_args.kwargs["role_overrides"],
    "saved": repo.saved,
    "loaded": sorted({m.split(".")[0] for m in sys.modules} & BLOCKED),
}))
"""


@given("a Python process where the desktop app, Qt and sqlite3 cannot be imported", target_fixture="host")
def host_process():
    return [sys.executable, "-c", HOST, ",".join(BLOCKED)]


@when(
    "a host imports every wcl_app module and analyses a raid with its own client and storage",
    target_fixture="host_run",
)
def run_host(host):
    run = subprocess.run(
        host,
        cwd=Path(wcl_app.__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode != 0:
        pytest.fail(f"{REQUIREMENT}: headless host failed\n{run.stdout}{run.stderr}")
    return json.loads(run.stdout.strip().splitlines()[-1])


@then("the analysis should use the host's client and the saved role overrides")
def used_host_client(host_run):
    assert host_run["client_is_host"]
    assert host_run["overrides"] == {"Holy": "tank"}


@then("the raid should be stored through the host's storage")
def stored_by_host(host_run):
    assert host_run["saved"] == ["raidReport000001", "guild"]


@then("no desktop app, Qt or sqlite3 module should have been loaded")
def nothing_blocked_loaded(host_run):
    assert host_run["loaded"] == []
