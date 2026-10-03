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
    "ears_optional_feature": "Where",
}
OPENERS = {o for o in EARS_OPENERS.values() if o}
REQ_ID = re.compile(r"[A-Z]+(?:-[A-Z0-9]+)+")
STATUSES = {"Enforced", "Practised", "Gap"}
SHALL = re.compile(r"\bshall\b", re.IGNORECASE)
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
    patterns = [t for t in scenario.tags if t in EARS_OPENERS]
    if len(patterns) != 1:
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


def requirements(guide: str) -> list[Requirement]:
    """Rows of the guide's requirements table; an Enforced row whose evidence is 'see below' takes the
    '<ID> evidence:' sentence after the table."""
    rows = []
    for line in guide.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and REQ_ID.fullmatch(cells[0]):
            rows.append(Requirement(*cells))
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


def known_tests() -> set[str]:
    """Every test path, test function and test class under tests/, and each path::name pair."""
    known: set[str] = set()
    for path in TESTS.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        known.add(rel)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                known.add(node.name)
                known.add(f"{rel}::{node.name}")
    return known


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
    bound = {
        match
        for path in STEP_DEFS.glob("*.py")
        for match in re.findall(r"\bscenarios?\(\s*[\"']([\w./-]+\.feature)", path.read_text(encoding="utf-8"))
    }
    assert {name for name, _ in _features()} - bound == set()


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
"""
    found = {s.line: ears_problems(s) for s in scenarios("f.feature", source)}
    assert [line for line, problems in found.items() if not problems] == [3, 5, 7]
    assert "opens with 'The', not 'When'" in found[9][0]
    assert "tagged ubiquitous but opens with 'When'" in found[11][0]
    assert found[13] == ["has 2 'shall', needs one"]
    assert "needs one EARS tag" in found[15][0] and "needs one EARS tag" in found[17][0]
    assert found[18][0] == "has 0 'shall', needs one" and len(found[18]) == 2


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
