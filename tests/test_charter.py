"""guides/CHARTER.md is audited like the specification (charter DOC-01).

Every ``#### ID · Pattern · Status`` block is a requirement: its first paragraph holds one ``shall`` in the form its
EARS pattern names, and an Enforced block's **Verified by** names at least one mechanism that exists. Every path,
test, ``dev.py`` task and CI job a Verified-by names must exist, whatever the status, so the charter cannot point at
something that was renamed. Each rule has a test of its own on a small source.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CHARTER = ROOT / "guides" / "CHARTER.md"

PATTERNS = {"Ubiquitous": None, "Event-driven": "When", "State-driven": "While", "Optional": "Where", "Unwanted": "If"}
OPENERS = {o for o in PATTERNS.values() if o}
STATUSES = {"Enforced", "Practised", "Partial", "Gap"}
PREFIXES = {"ARCH", "DES", "TEST", "GATE", "SEC", "DOC", "REL", "PROC"}
REQ_ID = re.compile(r"([A-Z]+)-\d{2}")
SHALL = re.compile(r"\bshall\b", re.IGNORECASE)
WRONG_OBLIGATION = re.compile(r"\b(should|must|will|may)\b", re.IGNORECASE)
VAGUE = re.compile(
    r"\b(appropriate(ly)?|as needed|if possible|user-friendly|robust|fast|easy|easily|etc|and/or|some|several)\b",
    re.IGNORECASE,
)
# Mechanisms GitHub holds in its settings rather than in a file.
EXTERNAL = {"branch protection"}
HEADER = re.compile(r"^####\s+(.+?)\s*$")
TICKED = re.compile(r"`([^`]+)`")
DEV_TASK = re.compile(r"python scripts/dev\.py ([a-z]+)")


@dataclass(frozen=True)
class Block:
    id: str
    pattern: str
    status: str
    fields: int
    line: int
    text: str
    verified_by: str


def parse(markdown: str) -> list[Block]:
    """Every requirement block, in order: its header fields, its first paragraph and its Verified-by bullet."""
    lines = markdown.splitlines()
    blocks = []
    for n, line in enumerate(lines):
        header = HEADER.match(line)
        if not header:
            continue
        fields = [f.strip() for f in header.group(1).split("·")]
        end = next((i for i in range(n + 1, len(lines)) if re.match(r"#{1,6}\s|-{3,}\s*$", lines[i])), len(lines))
        body = lines[n + 1 : end]
        paragraph: list[str] = []
        for text in body:
            if not text.strip():
                if paragraph:
                    break
                continue
            if text.lstrip().startswith("- "):
                break
            paragraph.append(text.strip())
        verified = _bullet(body, "**Verified by:**")
        padded = [*fields, "", "", ""]
        blocks.append(Block(padded[0], padded[1], padded[2], len(fields), n + 1, " ".join(paragraph), verified))
    return blocks


def _bullet(body: list[str], label: str) -> str:
    """A ``- label`` bullet with its continuation lines, without the label."""
    out: list[str] = []
    for text in body:
        if out and (text.lstrip().startswith("- ") or not text.strip()):
            break
        if out:
            out.append(text.strip())
        elif text.lstrip().startswith(f"- {label}"):
            out.append(text.strip()[len(f"- {label}") :].strip())
    return " ".join(out)


def form_problems(block: Block) -> list[str]:
    """Why a block's header or requirement sentence is not one sound EARS requirement."""
    problems = []
    match = REQ_ID.fullmatch(block.id)
    if not match or match.group(1) not in PREFIXES:
        problems.append(f"has ID {block.id!r}, expected PREFIX-NN with a prefix from Part 0")
    if block.fields != 3:
        problems.append(f"has {block.fields} header fields, expected ID · Pattern · Status")
    if block.pattern not in PATTERNS:
        problems.append(f"has pattern {block.pattern!r}, not one of {', '.join(PATTERNS)}")
    if block.status not in STATUSES:
        problems.append(f"has status {block.status!r}, not one of {', '.join(sorted(STATUSES))}")
    text = block.text.replace("*", "").replace("_", " ")
    if (shalls := len(SHALL.findall(text))) != 1:
        problems.append(f"has {shalls} 'shall', needs one")
    if wrong := WRONG_OBLIGATION.findall(TICKED.sub("", text)):
        problems.append(f"uses {', '.join(sorted({w.lower() for w in wrong}))} where it means shall")
    if vague := VAGUE.findall(TICKED.sub("", text)):
        problems.append(f"uses vague words: {', '.join(sorted({v[0].lower() for v in vague}))}")
    first = text.split(" ", 1)[0].rstrip(",")
    if first.lower() == "it":
        problems.append("opens with 'It'; name the system")
    opener = PATTERNS.get(block.pattern)
    if block.pattern in PATTERNS:
        if opener is None and first in OPENERS:
            problems.append(f"is Ubiquitous but opens with {first!r}")
        elif opener is not None and first != opener:
            problems.append(f"is {block.pattern} but opens with {first!r}, not {opener!r}")
        if block.pattern == "Unwanted" and not re.search(r",\s*then\b", text):
            problems.append("is Unwanted but has no ', then'")
    return problems


@dataclass(frozen=True)
class Known:
    files: frozenset[str]
    tests: frozenset[str]  # path::name for every test function and class
    tasks: frozenset[str]
    jobs: frozenset[str]


def mechanisms(verified_by: str, known: Known) -> tuple[list[str], list[str]]:
    """The mechanisms a Verified-by names that exist, and those it names that do not."""
    found, missing = [], []
    for task in DEV_TASK.findall(verified_by):
        (found if task in known.tasks else missing).append(f"dev.py {task}")
    for token in TICKED.findall(verified_by):
        if token.startswith("python scripts/dev.py"):
            continue
        name = _mechanism(token, known)
        if name is True:
            found.append(token)
        elif name is False:
            missing.append(token)
    return found, missing


def _mechanism(token: str, known: Known) -> bool | None:
    """True for a mechanism that exists, False for one that looks like a mechanism and does not, None for prose."""
    if token in EXTERNAL or token in known.jobs:
        return True
    path, _, test = token.partition("::")
    if test:
        return token in known.tests
    if "/" in path or re.search(r"\.(py|ya?ml|md|toml|txt|cfg)$", path):
        return path.rstrip("/") in known.files
    return None


def charter_problems(blocks: list[Block], known: Known) -> list[str]:
    problems = []
    seen: set[str] = set()
    for block in blocks:
        where = f"{block.id or '?'} (line {block.line})"
        if block.id in seen:
            problems.append(f"{where} repeats an ID")
        seen.add(block.id)
        problems += [f"{where} {p}" for p in form_problems(block)]
        found, missing = mechanisms(block.verified_by, known)
        if not block.verified_by:
            problems.append(f"{where} has no Verified by")
        if block.status == "Enforced" and not found:
            problems.append(f"{where} is Enforced but names no mechanism that exists")
        problems += [f"{where} names {m}, which does not exist" for m in missing]
    return problems


@cache
def _known() -> Known:
    files = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if ".git" not in p.parts}
    tests = set()
    for path in (ROOT / "tests").rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                tests.add(f"{rel}::{node.name}")
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    dev_source = (ROOT / "scripts" / "dev.py").read_text(encoding="utf-8")
    tasks = set(re.findall(r'^    "([a-z]+)": \(', dev_source, re.M))
    return Known(frozenset(files), frozenset(tests), frozenset(tasks), frozenset(workflow["jobs"]))


def test_the_charter_is_sound():
    blocks = parse(CHARTER.read_text(encoding="utf-8"))
    assert len(blocks) >= 30, "the parser found too few requirement blocks"
    assert charter_problems(blocks, _known()) == []


def test_every_status_and_prefix_is_used_as_declared():
    blocks = parse(CHARTER.read_text(encoding="utf-8"))
    assert {b.status for b in blocks} <= STATUSES
    assert {b.id.split("-")[0] for b in blocks} == PREFIXES


def test_the_known_mechanisms_are_read_from_the_repository():
    known = _known()
    assert {"lint", "test", "mutation", "imports"} <= known.tasks
    assert {"ci-success", "gitleaks", "storage-postgres"} <= known.jobs
    assert "tests/test_charter.py::test_the_charter_is_sound" in known.tests
    assert "guides/CHARTER.md" in known.files


SAMPLE = """\
#### ARCH-01 · Ubiquitous · Enforced

The analyzer **shall** do one thing.

- **Why:** reasons.
- **Verified by:** `tests/test_x.py::test_y` and
  `python scripts/dev.py lint`.

#### SEC-02 · Unwanted · Gap

If a token leaks, then the analyzer **shall** mask it.

- **Verified by:** none yet.
"""
KNOWN = Known(
    files=frozenset({"tests/test_x.py", "guides/a.md"}),
    tests=frozenset({"tests/test_x.py::test_y"}),
    tasks=frozenset({"lint"}),
    jobs=frozenset({"lint", "ci-success"}),
)


def test_the_parser_reads_headers_requirements_and_wrapped_bullets():
    first, second = parse(SAMPLE)
    assert (first.id, first.pattern, first.status, first.line) == ("ARCH-01", "Ubiquitous", "Enforced", 1)
    assert first.text == "The analyzer **shall** do one thing."
    assert first.verified_by == "`tests/test_x.py::test_y` and `python scripts/dev.py lint`."
    assert (second.id, second.pattern, second.verified_by) == ("SEC-02", "Unwanted", "none yet.")
    assert charter_problems([first, second], KNOWN) == []


def _block(text: str, pattern: str = "Ubiquitous", id_: str = "DOC-01", fields: int = 3) -> Block:
    return Block(id_, pattern, "Gap", fields, 1, text, "none yet.")


def test_the_form_rule_checks_shall_words_and_pattern():
    assert form_problems(_block("The app **shall** log.")) == []
    assert "has 2 'shall', needs one" in form_problems(_block("The app shall log and shall store."))
    assert "has 0 'shall', needs one" in form_problems(_block("The app logs."))
    assert "uses must where it means shall" in form_problems(_block("The app must log and shall store."))
    assert "uses vague words: appropriate" in form_problems(_block("The app shall log as appropriate."))
    assert "opens with 'It'; name the system" in form_problems(_block("It shall log."))
    assert "is Ubiquitous but opens with 'When'" in form_problems(_block("When asked, the app shall log."))
    assert "is Event-driven but opens with 'The', not 'When'" in form_problems(
        _block("The app shall log.", "Event-driven")
    )
    assert "is Unwanted but has no ', then'" in form_problems(_block("If it fails the app shall log.", "Unwanted"))
    assert form_problems(_block("If it fails, then the app shall log.", "Unwanted")) == []
    assert form_problems(_block("The `must` flag **shall** be read.")) == []  # code spans are not words


def test_the_form_rule_checks_the_header():
    assert form_problems(_block("The app shall log.", id_="DOC-1"))[0].startswith("has ID 'DOC-1'")
    assert form_problems(_block("The app shall log.", id_="FOO-01"))[0].startswith("has ID 'FOO-01'")
    assert "has 2 header fields, expected ID · Pattern · Status" in form_problems(
        _block("The app shall log.", fields=2)
    )
    assert form_problems(_block("The app shall log.", "Sometimes")) == [
        "has pattern 'Sometimes', not one of Ubiquitous, Event-driven, State-driven, Optional, Unwanted"
    ]


def test_an_enforced_block_needs_a_mechanism_that_exists():
    def enforced(verified_by: str) -> list[str]:
        return charter_problems(
            [Block("TEST-01", "Ubiquitous", "Enforced", 3, 1, "The app shall log.", verified_by)], KNOWN
        )

    assert enforced("`tests/test_x.py::test_y`") == []
    assert enforced("the `ci-success` job") == []
    assert enforced("`branch protection`") == []
    assert enforced("`python scripts/dev.py lint`") == []
    assert enforced("review.") == ["TEST-01 (line 1) is Enforced but names no mechanism that exists"]
    assert enforced("`tests/test_x.py::test_gone`") == [
        "TEST-01 (line 1) is Enforced but names no mechanism that exists",
        "TEST-01 (line 1) names tests/test_x.py::test_gone, which does not exist",
    ]
    assert enforced("`python scripts/dev.py nope` and `guides/a.md`") == [
        "TEST-01 (line 1) names dev.py nope, which does not exist"
    ]
    assert enforced("`guides/gone.md` and `guides/a.md`") == [
        "TEST-01 (line 1) names guides/gone.md, which does not exist"
    ]
    assert enforced("`RaidRepository` in `guides/a.md`") == []  # a bare name is prose, not a mechanism


def test_ids_are_unique_and_every_block_says_how_it_is_verified():
    block = Block("GATE-01", "Ubiquitous", "Practised", 3, 1, "The app shall log.", "")
    assert charter_problems([block, block], KNOWN) == [
        "GATE-01 (line 1) has no Verified by",
        "GATE-01 (line 1) repeats an ID",
        "GATE-01 (line 1) has no Verified by",
    ]
