"""The specification stays in EARS form and every requirement marked Enforced names a check that exists.

Two sources hold requirements: the Gherkin scenarios in ``tests/features/`` and the requirements table in
``guides/identity_and_profiles.md``. This audit (phase Q in that guide) reads both. Each rule has a test of its own on
a small source, so a rule that stops matching fails here.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

TESTS = Path(__file__).parent
ROOT = TESTS.parent
FEATURES = TESTS / "features"
STEP_DEFS = TESTS / "step_defs"
GUIDE = ROOT / "guides" / "identity_and_profiles.md"

# The EARS pattern a scenario's tag names, and the word its requirement opens with (None: none of these).
EARS_OPENERS = {
    "ears_ubiquitous": None,
    "ears_event_driven": "When",
    "ears_state_driven": "While",
    "ears_unwanted_behavior": "If",
    "ears_optional": "Where",
}
OPENERS = {o for o in EARS_OPENERS.values() if o}
REQ_ID = re.compile(r"[A-Z]+(?:-[A-Z0-9]+)+")
STATUSES = {"Enforced", "Practised", "Gap"}
SHALL = re.compile(r"\bshall\b", re.IGNORECASE)
# Enforced requirements proved outside tests/features/, and why. The list only shrinks.
NO_SCENARIO = {
    "PROF-09": "a desktop widget requirement; the PySide6 tests in tests/gui/ prove it",
    "ARCH-P1": "a layering rule over the source tree; test_architecture.py and lint-imports prove it",
    "ARCH-P2": "a rule for how storage changes land; the contract and migration tests prove it",
    "ARCH-P3": "a rule over the source tree; test_single_host_config.py proves it",
}
# Evidence that names a test: a test function or class, or a path under tests/.
EVIDENCE = re.compile(r"`((?:tests/[\w/.-]+\.py)(?:::\w+)?|test_\w+|Test\w+)`")


@dataclass(frozen=True)
class Scenario:
    feature: str
    line: int
    title: str
    tags: tuple[str, ...]

    @property
    def requirement(self) -> str:
        """The title without a leading requirement ID."""
        first, _, rest = self.title.partition(" ")
        return rest if REQ_ID.fullmatch(first) else self.title


def scenarios(name: str, text: str) -> Iterator[Scenario]:
    lines = text.splitlines()
    for n, line in enumerate(lines):
        match = re.match(r"\s*Scenario(?: Outline)?:\s*(.+)", line)
        if not match:
            continue
        tags: list[str] = []
        above = n - 1
        while above >= 0 and lines[above].strip().startswith("@"):
            tags += [t.lstrip("@") for t in lines[above].split()]
            above -= 1
        yield Scenario(name, n + 1, match.group(1).strip(), tuple(tags))


def ears_problems(scenario: Scenario) -> list[str]:
    """Why a scenario is not one EARS requirement: its shall count, its pattern tag, its opening word."""
    problems = []
    shalls = len(SHALL.findall(scenario.requirement))
    if shalls != 1:
        problems.append(f"has {shalls} 'shall', needs one")
    patterns = [t for t in scenario.tags if t.startswith("ears_")]
    if len(patterns) != 1 or patterns[0] not in EARS_OPENERS:
        problems.append(f"needs one EARS tag ({', '.join(sorted(EARS_OPENERS))}), has {patterns or 'none'}")
        return problems
    opener = EARS_OPENERS[patterns[0]]
    first = scenario.requirement.split(" ", 1)[0].rstrip(",")
    if opener is None and first in OPENERS:
        problems.append(f"is tagged ubiquitous but opens with {first!r}")
    elif opener is not None and first != opener:
        problems.append(f"is tagged {patterns[0]} but opens with {first!r}, not {opener!r}")
    return problems


@dataclass(frozen=True)
class Requirement:
    id: str
    text: str
    status: str
    evidence: str


TABLE_HEADER = "| ID | Requirement | Status | Evidence |"


def requirements(guide: str) -> list[Requirement]:
    """Every data row of the guide's requirements table, whatever its ID looks like; an Enforced row whose evidence
    is 'see below' takes the '<ID> evidence:' sentence after the table."""
    lines = guide.splitlines()
    start = next((n for n, line in enumerate(lines) if line.strip() == TABLE_HEADER), None)
    rows = []
    for line in lines[start + 2 :] if start is not None else []:
        if not line.strip().startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cells += [""] * (4 - len(cells))
        rows.append(Requirement(cells[0], cells[1], cells[2], " | ".join(cells[3:])))
    resolved = []
    for row in rows:
        evidence = row.evidence
        if evidence.lower().startswith("see below"):
            match = re.search(
                rf"{re.escape(row.id)} evidence:(.*?)(?=\b[A-Z]+-[A-Z0-9]+ evidence:|\n\n|$)", guide, re.S
            )
            evidence = match.group(1) if match else ""
        resolved.append(Requirement(row.id, row.text, row.status, evidence))
    return resolved


def requirement_problems(row: Requirement, known: set[str]) -> list[str]:
    """Why a table row is not a sound requirement: its shall count, its status, its evidence."""
    problems = []
    if not REQ_ID.fullmatch(row.id):
        problems.append("has a malformed ID, expected one like PROF-01")
    shalls = len(SHALL.findall(row.text))
    if shalls != 1:
        problems.append(f"has {shalls} 'shall', needs one")
    if row.status not in STATUSES:
        problems.append(f"has status {row.status!r}, not one of {', '.join(sorted(STATUSES))}")
    if row.status == "Enforced":
        named = EVIDENCE.findall(row.evidence)
        if not named:
            problems.append("is Enforced but names no test")
        problems += [f"names {name}, which does not exist" for name in named if name not in known]
    return problems


def evidence_in(rel: str, source: str) -> set[str]:
    """The evidence one module offers: its test functions and classes, each as ``path::name``, and the path itself
    when it holds at least one of them (a fixture or helper module proves nothing)."""
    names = {
        node.name
        for node in ast.walk(ast.parse(source))
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"))
        or (isinstance(node, ast.ClassDef) and node.name.startswith("Test"))
    }
    return names | {f"{rel}::{name}" for name in names} | ({rel} if names else set())


def known_tests() -> set[str]:
    known: set[str] = set()
    for path in TESTS.rglob("*.py"):
        known |= evidence_in(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
    return known


def bound_features(source: str) -> set[str]:
    """Feature files a step module binds with an executed ``scenarios(...)`` or ``scenario(...)`` call."""
    return {
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and _call_name(node) in {"scenarios", "scenario"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _call_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def scenario_problems(rows: list[Requirement], titles: set[str]) -> list[str]:
    """Why the scenarios and the requirements table disagree: an Enforced requirement with no scenario worded
    exactly as the table words it, a scenario carrying a table ID with other words, or a stale NO_SCENARIO entry."""
    expected = {row.id: f"{row.id} {row.text.rstrip('.')}" for row in rows}
    problems = []
    for row in rows:
        if row.status == "Enforced" and row.id not in NO_SCENARIO and expected[row.id] not in titles:
            problems.append(f"{row.id} is Enforced but no scenario is titled {expected[row.id]!r}")
    for title in sorted(titles):
        req_id = title.split(" ", 1)[0]
        if req_id in expected and title != expected[req_id]:
            problems.append(f"the {req_id} scenario is worded {title!r}, the guide {expected[req_id]!r}")
    problems += [
        f"{req_id} is in NO_SCENARIO but has a scenario" for req_id in NO_SCENARIO if expected.get(req_id) in titles
    ]
    problems += [
        f"{req_id} is in NO_SCENARIO but is not an Enforced requirement"
        for req_id in NO_SCENARIO
        if not any(r.id == req_id and r.status == "Enforced" for r in rows)
    ]
    return problems


def _features() -> list[tuple[str, str]]:
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(FEATURES.glob("*.feature"))]


def test_every_scenario_is_one_ears_requirement():
    found = [
        f"{s.feature}:{s.line} {problem}"
        for name, text in _features()
        for s in scenarios(name, text)
        for problem in ears_problems(s)
    ]
    assert found == [], "\n".join(found)


def test_every_feature_file_is_bound_to_step_definitions():
    """pytest-bdd runs a feature only when a step module calls scenarios() on it; an unbound one never fails."""
    bound = set().union(*(bound_features(p.read_text(encoding="utf-8")) for p in STEP_DEFS.glob("*.py")))
    assert {name for name, _ in _features()} - bound == set()


def test_every_enforced_requirement_has_its_scenario():
    rows = requirements(GUIDE.read_text(encoding="utf-8"))
    titles = {s.title for name, text in _features() for s in scenarios(name, text)}
    assert scenario_problems(rows, titles) == []


def test_the_scenario_rule_matches_titles_to_the_table_word_for_word():
    rows = [
        Requirement("A-01", "The app shall start.", "Enforced", "`test_a`"),
        Requirement("A-02", "The app shall stop.", "Enforced", "`test_b`"),
        Requirement("A-03", "The app shall fly.", "Gap", "Phase 9"),
        Requirement("PROF-09", "The desktop shall switch.", "Enforced", "`test_c`"),
    ]
    titles = {"A-01 The app shall start", "A-02 The app shall halt", "REQ-X-001 Other things shall work"}
    assert scenario_problems(rows, titles) == [
        "A-02 is Enforced but no scenario is titled 'A-02 The app shall stop'",
        "the A-02 scenario is worded 'A-02 The app shall halt', the guide 'A-02 The app shall stop'",
        "ARCH-P1 is in NO_SCENARIO but is not an Enforced requirement",
        "ARCH-P2 is in NO_SCENARIO but is not an Enforced requirement",
        "ARCH-P3 is in NO_SCENARIO but is not an Enforced requirement",
    ]
    titles.add("PROF-09 The desktop shall switch")
    assert "PROF-09 is in NO_SCENARIO but has a scenario" in scenario_problems(rows, titles)


def test_the_ears_tags_are_the_registered_markers():
    """``--strict-markers`` rejects a tag pytest does not know, so the audit's patterns must be pytest's."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert set(re.findall(r'"(ears_\w+):', pyproject)) == set(EARS_OPENERS)


def test_the_binding_rule_counts_only_executed_calls():
    source = """
from pytest_bdd import scenario, scenarios
scenarios("a.feature")
# scenarios("b.feature")
TEXT = 'scenarios("c.feature")'
@scenario("d.feature", "D")
def test_d(): pass
"""
    assert bound_features(source) == {"a.feature", "d.feature"}


def test_every_requirement_in_the_guide_is_sound():
    rows = requirements(GUIDE.read_text(encoding="utf-8"))
    assert len(rows) >= 10, "the requirements table was not found"
    assert len({r.id for r in rows}) == len(rows), "a requirement ID is used twice"
    known = known_tests()
    found = [f"{row.id} {problem}" for row in rows for problem in requirement_problems(row, known)]
    assert found == [], "\n".join(found)


def test_the_ears_rule_checks_shall_tag_and_opening_word():
    source = """Feature: F
  @ears_event_driven
  Scenario: When a raid is imported, the store shall keep it
  @ears_ubiquitous @database
  Scenario: REQ-X-001 The store shall keep raids
  @ears_unwanted_behavior
  Scenario Outline: If <x> fails, then the client shall raise
  @ears_event_driven
  Scenario: The store shall keep raids
  @ears_ubiquitous
  Scenario: When a raid is imported, the store shall keep it
  @ears_state_driven
  Scenario: While signed in, the app shall show the name and shall show the avatar
  @database
  Scenario: The store shall keep raids
  @ears_ubiquitous @ears_event_driven
  Scenario: When asked, the store shall answer
  Scenario: The store keeps raids
  @ears_optional
  Scenario: Where Postgres is installed, the store shall use it
  @ears_event_driven @ears_evnt_driven
  Scenario: When asked, the store shall answer
"""
    found = {s.line: ears_problems(s) for s in scenarios("f.feature", source)}
    assert [line for line, problems in found.items() if not problems] == [3, 5, 7, 20]
    assert "opens with 'The', not 'When'" in found[9][0]
    assert "tagged ubiquitous but opens with 'When'" in found[11][0]
    assert found[13] == ["has 2 'shall', needs one"]
    assert "needs one EARS tag" in found[15][0] and "needs one EARS tag" in found[17][0]
    assert found[18][0] == "has 0 'shall', needs one" and len(found[18]) == 2
    assert "needs one EARS tag" in found[22][0]


def test_the_requirement_rule_checks_shall_status_and_evidence():
    guide = """| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| A-01 | The app shall start. | Enforced | `test_starts`, `tests/test_app.py::test_starts` |
| A-02 | The app shall stop and shall restart. | Enforced | `test_stops` |
| A-03 | The app shall sing. | Enforced | it works |
| A-04 | The app shall dance. | Enforced | `test_dances_badly` |
| A-05 | The app shall fly. | Gap | Phase 9 |
| A-06 | The app shall swim. | Done | `test_swims` |
| A-07 | The app shall rest. | Enforced | see below |
| A-08 | The app shall wake. | Enforced | see below |
| A_09 | The app shall sleep. | Enforced | `test_starts` |
| A-10 | The app shall log. | Enforced | `tests/conftest.py` |

A-07 evidence: `test_rests` and `tests/test_app.py`. A-08 evidence: `test_dances_badly`.
"""
    rows = {r.id: r for r in requirements(guide)}
    known = {"test_starts", "tests/test_app.py", "tests/test_app.py::test_starts", "test_stops", "test_swims"}
    known |= {"test_rests"}
    found = {key: requirement_problems(row, known) for key, row in rows.items()}
    assert found["A-01"] == [] and found["A-05"] == [] and found["A-07"] == []
    assert found["A-02"] == ["has 2 'shall', needs one"]
    assert found["A-03"] == ["is Enforced but names no test"]
    assert found["A-04"] == ["names test_dances_badly, which does not exist"]
    assert found["A-06"] == ["has status 'Done', not one of Enforced, Gap, Practised"]
    assert found["A-08"] == ["names test_dances_badly, which does not exist"]
    assert found["A_09"] == ["has a malformed ID, expected one like PROF-01"]
    assert found["A-10"] == ["names tests/conftest.py, which does not exist"]


def test_only_modules_holding_tests_count_as_evidence():
    assert evidence_in("tests/conftest.py", "def build(): ...\nclass Helper: ...\n") == set()
    module = "def test_a(): ...\nclass TestB: ...\ndef helper(): ...\n"
    assert evidence_in("tests/test_x.py", module) == {
        "test_a",
        "TestB",
        "tests/test_x.py::test_a",
        "tests/test_x.py::TestB",
        "tests/test_x.py",
    }
