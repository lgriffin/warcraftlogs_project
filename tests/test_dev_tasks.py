"""scripts/dev.py is the one list of checks: CI, pre-commit and `make` call its tasks, so they must stay valid."""

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dev = _load("dev_tasks", "dev.py")
gate = _load("ci_gate", "ci_gate.py")
CI = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
GATE = "ci-success"
# The scripts/dev.py tasks each CI job runs. A job that drops or swaps a task fails the parity test.
JOB_TASKS = {
    "lint": {"lint", "format", "spelling", "deadcode", "imports"},
    "test": {"test", "diffcov"},
    "storage-postgres": {"pgcov"},
    "gui-test": {"gui"},
    "fuzz": {"fuzz"},
    "mutation": {"mutation"},
    "type-check": {"types"},
    "security": {"security", "audit"},
}
# CI jobs that run no scripts/dev.py task, each with the reason `check` cannot run it locally.
OUTSIDE_DEV = {
    "gitleaks": "a third-party action that scans the whole git history",
    "wcl-core-package": "builds the wcl-core wheel alone in a fresh environment, without the desktop app",
    "wcl-store-package": "builds the wcl-core and wcl-store wheels alone in a fresh environment",
    "wcl-app-package": "builds the three package wheels alone and runs a raid headless",
    GATE: "the fan-in gate over the other jobs (scripts/ci_gate.py)",
}


def _task_calls(text: str) -> set[str]:
    return {task for line in re.findall(r"scripts/dev\.py ([a-z -]+)", text) for task in line.split()}


def test_check_runs_only_known_tasks():
    assert set(dev.CHECK) <= set(dev.TASKS)


@pytest.mark.parametrize("path", [".github/workflows/ci.yml", ".pre-commit-config.yaml", "Makefile"])
def test_every_caller_names_a_real_task(path):
    calls = _task_calls((ROOT / path).read_text(encoding="utf-8"))
    assert calls, f"{path} no longer calls scripts/dev.py"
    assert calls <= {"check", "fix", *dev.TASKS}


def test_ci_runs_every_check_task():
    ci = _task_calls(CI)
    assert set(dev.CHECK) <= ci


def _workflow() -> dict:
    return yaml.safe_load(CI)


def _jobs() -> dict[str, dict]:
    return _workflow()["jobs"]


def _tasks_run_by(job: dict) -> set[str]:
    """The scripts/dev.py tasks a job's steps run (only `run:` commands, not comments or names)."""
    return {task for step in job.get("steps", []) for task in _task_calls(str(step.get("run", "")))}


def test_the_gate_waits_on_every_job():
    """ESI.ts `ci-success`: one required check that needs every job, so a dropped job cannot pass silently."""
    jobs = _jobs()
    assert set(jobs[GATE]["needs"]) == set(jobs) - {GATE}


def test_only_the_gate_has_a_job_level_if():
    """A job-level `if:` can skip a job, and the gate counts skipped as failed; only the gate itself may have one."""
    jobs = _jobs()
    assert {job for job, spec in jobs.items() if "if" in spec} == {GATE}
    assert jobs[GATE]["if"] == "always()"


def test_each_job_runs_its_dev_tasks():
    """`check:local` parity: each job runs exactly its tasks, so a job cannot quietly stop running one."""
    run = {job: _tasks_run_by(spec) for job, spec in _jobs().items()}
    assert {job: tasks for job, tasks in run.items() if tasks} == JOB_TASKS
    assert {job for job, tasks in run.items() if not tasks} == set(OUTSIDE_DEV)


def test_the_parser_sees_quoted_job_ids_and_swapped_tasks():
    """The checks above read the real YAML: a quoted job id is a job, and a run step names its exact task."""
    workflow = yaml.safe_load(
        'jobs:\n  "release-check":\n    steps:\n      - run: python scripts/dev.py lint\n'
        "      - name: python scripts/dev.py gui\n"
    )
    assert set(workflow["jobs"]) == {"release-check"}
    assert _tasks_run_by(workflow["jobs"]["release-check"]) == {"lint"}


def _needs_json(**results: str) -> dict[str, str]:
    return {"NEEDS_JSON": json.dumps({job: {"result": result} for job, result in results.items()})}


def test_the_gate_passes_only_when_every_job_succeeded():
    assert gate.main(_needs_json(lint="success", test="success")) == 0
    for bad in ("failure", "cancelled", "skipped"):
        assert gate.main(_needs_json(lint="success", test=bad)) == 1


def test_the_gate_fails_without_jobs_or_results():
    assert gate.main({}) == 1
    assert gate.main({"NEEDS_JSON": "not json"}) == 1
    assert gate.main({"NEEDS_JSON": "{}"}) == 1
    assert gate.failures({"lint": {}}) == {"lint": "missing"}


def test_unknown_task_is_rejected():
    with pytest.raises(SystemExit):
        dev.main(["no-such-task"])


def test_fix_must_run_alone():
    with pytest.raises(SystemExit):
        dev.main(["fix", "lint"])


def test_stops_at_the_first_failure(monkeypatch):
    ran = []
    monkeypatch.setattr(dev, "_run", lambda commands: ran.append(commands) or False)
    assert dev.run_tasks(["lint", "types"], keep_going=False) == 1
    assert len(ran) == 1


def test_keep_going_runs_everything(monkeypatch):
    ran = []
    monkeypatch.setattr(dev, "_run", lambda commands: ran.append(commands) or False)
    assert dev.run_tasks(["lint", "types"], keep_going=True) == 1
    assert len(ran) == 2
