"""scripts/dev.py is the one list of checks: CI, pre-commit and `make` call its tasks, so they must stay valid."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

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


def _jobs(text: str) -> dict[str, str]:
    """Each top-level job in a workflow with the text of its block."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):[ \t]*$", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _needs(block: str) -> set[str]:
    listed = re.search(r"^    needs:\n((?:      - .+\n)+)", block, flags=re.MULTILINE)
    assert listed, "the gate lists its needs one per line"
    return {line.strip()[2:] for line in listed.group(1).splitlines()}


def test_the_gate_waits_on_every_job():
    """ESI.ts `ci-success`: one required check that needs every job, so a dropped job cannot pass silently."""
    jobs = _jobs(CI)
    assert _needs(jobs[GATE]) == set(jobs) - {GATE}


def test_only_the_gate_has_a_job_level_if():
    """A job-level `if:` can skip a job, and the gate counts skipped as failed; only the gate itself may have one."""
    conditional = {job for job, block in _jobs(CI).items() if re.search(r"^    if:", block, flags=re.MULTILINE)}
    assert conditional == {GATE}
    assert re.search(r"^    if: always\(\)$", _jobs(CI)[GATE], flags=re.MULTILINE)


def test_every_job_runs_a_dev_task_or_says_why_not():
    """`check:local` parity: a CI job either runs scripts/dev.py tasks or is listed in OUTSIDE_DEV with a reason."""
    jobs = _jobs(CI)
    runs_dev = {job for job, block in jobs.items() if "scripts/dev.py" in block}
    assert runs_dev | set(OUTSIDE_DEV) == set(jobs)
    assert not runs_dev & set(OUTSIDE_DEV), "a job listed as outside dev.py now runs it; drop it from OUTSIDE_DEV"


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
