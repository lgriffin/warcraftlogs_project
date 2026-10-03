"""scripts/mutate.py: the mutation runner behind the wcl_core floors (phase Q)."""

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("mutate", ROOT / "scripts" / "mutate.py")
mutate = importlib.util.module_from_spec(_spec)
sys.modules["mutate"] = mutate  # its dataclasses look their module up there
_spec.loader.exec_module(mutate)

SOURCE = '''
"""Module docstring."""
__all__ = ["f"]
LIMIT: int = 3


def f(x: int, flag: bool = True) -> int:
    """Doc."""
    logger.info("x=%d", x + 1)
    if x > LIMIT and not flag:
        return x * 2
    return "a" + "b"
'''


def test_every_site_is_numbered_and_annotations_docstrings_logs_and_all_are_left_alone():
    changes = [(m.line, m.change) for m in mutate.mutants(SOURCE)]
    assert changes == [
        (4, "3 -> 4"),
        (7, "True -> False"),
        (10, "Gt -> LtE"),
        (10, "drop not"),
        (10, "And -> Or"),
        (11, "2 -> 3"),
        (11, "Mult -> Div"),
        (11, "return None"),
        (10, "negate if"),
        (12, "return None"),
    ]


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (2, "if x <= LIMIT and (not flag):"),
        (3, "if x > LIMIT and flag:"),
        (4, "if x > LIMIT or not flag:"),
        (6, "return x / 2"),
        (7, "return None"),
        (8, "if not (x > LIMIT and (not flag)):"),
    ],
)
def test_each_mutant_changes_exactly_its_site(index, expected):
    mutated = mutate.mutate(SOURCE, index)
    assert expected in mutated
    assert ast.dump(ast.parse(mutated)) != ast.dump(ast.parse(SOURCE))
    assert '"""Doc."""' in mutated or "'Doc.'" in mutated  # docstrings survive


def test_a_module_with_nothing_to_mutate_scores_full_marks():
    assert mutate.mutants('"""Only a docstring."""\n') == []
    assert mutate.Result("empty", 0, []).score == 1.0
    assert mutate.Result("half", 4, [mutate.Mutant(0, 1, "x")] * 2).score == 0.5


def test_every_target_has_tests_and_a_floor_that_exist():
    config = mutate._config()
    assert config["targets"], "no mutation targets"
    for module, tests in config["targets"].items():
        assert (mutate.CORE_SRC / "wcl_core" / f"{module}.py").is_file(), module
        assert tests and all((ROOT / t).is_file() for t in tests), module
        assert 0 < config["floors"][module] <= 1, f"{module} needs a floor in [tool.wcl.mutation.floors]"
    assert set(config["floors"]) == set(config["targets"])


def test_an_unknown_module_is_refused():
    with pytest.raises(SystemExit, match="not a mutation target"):
        list(mutate._selected(mutate._config(), ["nope"]))


def test_class_decorators_are_mutated_like_function_decorators():
    source = "@dataclass(frozen=True)\nclass C:\n    x: int\n"
    assert [m.change for m in mutate.mutants(source)] == ["True -> False"]
    assert "frozen=False" in mutate.mutate(source, 0)


def test_the_default_worker_count_is_capped():
    assert 1 <= mutate.DEFAULT_JOBS <= 4


def test_a_failing_baseline_prints_pytest_output(capsys):
    assert not mutate._pytest(["tests/no_such_test_file.py"], mutate.CORE_SRC, timeout=60, show_failure=True)
    assert "no_such_test_file.py" in capsys.readouterr().err
