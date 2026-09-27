"""scripts/dev.py is the one list of checks: CI, pre-commit and `make` call its tasks, so they must stay valid."""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_dev():
    spec = importlib.util.spec_from_file_location("dev_tasks", ROOT / "scripts" / "dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dev = _load_dev()


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
    ci = _task_calls((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert set(dev.CHECK) <= ci


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
