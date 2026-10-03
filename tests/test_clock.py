"""wcl_core.clock is the one clock in the shared packages, and wcl_core.testing.FakeClock stands in for it.

The lint (phase Q in ``guides/identity_and_profiles.md``, ESI.ts's "time only through a clock module") fails on any
other read of the system clock in ``packages/``: the Toads Hub and the bot run this code, and a test of it should
never wait or depend on the day it runs.
"""

from __future__ import annotations

import ast
import time
from datetime import date, datetime
from pathlib import Path

import pytest
from wcl_core import clock
from wcl_core.testing import FakeClock

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"
CLOCK = PACKAGES / "wcl-core" / "src" / "wcl_core" / "clock.py"
# Reading these, called or passed as a default, reads the system clock.
SYSTEM_CLOCK = {
    "time.time",
    "time.time_ns",
    "time.monotonic",
    "time.monotonic_ns",
    "time.perf_counter",
    "time.sleep",
    "datetime.now",
    "datetime.utcnow",
    "datetime.today",
    "date.today",
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
    "datetime.datetime.today",
    "datetime.date.today",
}
TIME_NAMES = {name.split(".")[1] for name in SYSTEM_CLOCK if name.startswith("time.")}


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local names for the time and datetime modules and classes: ``import time as t`` gives ``{"t": "time"}``."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases |= {a.asname: a.name for a in node.names if a.asname and a.name in {"time", "datetime"}}
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            aliases |= {a.asname: a.name for a in node.names if a.asname and a.name in {"date", "datetime"}}
    return aliases


def _resolved(node: ast.Attribute, aliases: dict[str, str]) -> str:
    """The dotted name *node* reads, with an aliased first part put back: ``t.sleep`` -> ``time.sleep``."""
    first, _, rest = ast.unparse(node).partition(".")
    return f"{aliases.get(first, first)}.{rest}"


def clock_reads(source: str) -> list[str]:
    """Each place *source* reads the system clock, as ``line: what``."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and (name := _resolved(node, aliases)) in SYSTEM_CLOCK:
            found.append(f"{node.lineno}: {name}")
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            found += [f"{node.lineno}: from time import {a.name}" for a in node.names if a.name in TIME_NAMES]
    return found


def _package_sources() -> list[Path]:
    return [p for p in sorted(PACKAGES.glob("*/src/**/*.py")) if p != CLOCK and "migrations" not in p.parts]


def test_the_packages_read_the_time_only_through_wcl_core_clock():
    reads = {
        str(path.relative_to(ROOT)): hits
        for path in _package_sources()
        if (hits := clock_reads(path.read_text(encoding="utf-8")))
    }
    assert not reads, f"use wcl_core.clock instead: {reads}"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import time\ntime.sleep(1)\n", ["2: time.sleep"]),
        ("import time\nx = time.time() + 5\n", ["2: time.time"]),
        ("from datetime import datetime\ndef f(now=datetime.now): ...\n", ["2: datetime.now"]),
        ("import datetime\nd = datetime.date.today()\n", ["2: datetime.date.today"]),
        ("from time import monotonic, strftime\n", ["1: from time import monotonic"]),
        ("from time import sleep as nap\n", ["1: from time import sleep"]),
        ("import time as t\nt.sleep(1)\n", ["2: time.sleep"]),
        ("from datetime import datetime as dt\nx = dt.now()\n", ["2: datetime.now"]),
        ("from datetime import date as d\nx = d.today()\n", ["2: date.today"]),
        ("import datetime as dtm\nx = dtm.datetime.utcnow()\n", ["2: datetime.datetime.utcnow"]),
        ("from datetime import datetime\nd = datetime.strptime('2026', '%Y')\n", []),
    ],
)
def test_the_lint_sees_each_way_of_reading_the_clock(source, expected):
    assert clock_reads(source) == expected


def test_the_lint_reads_real_files():
    sources = _package_sources()
    assert any(p.name == "client.py" for p in sources)
    assert CLOCK not in sources


def test_by_default_it_is_the_system_clock():
    before = time.time()
    assert before <= clock.time() <= time.time()
    assert clock.monotonic() <= time.monotonic()
    assert abs((clock.now() - datetime.now()).total_seconds()) < 5
    assert clock.today() in {date.today(), datetime.now().date()}
    clock.sleep(0)


def test_a_fake_clock_is_a_clock():
    assert isinstance(FakeClock(), clock.Clock)
    assert not isinstance(object(), clock.Clock)


def test_a_fake_clock_moves_only_when_told():
    fake = FakeClock(datetime(2026, 11, 3, 23, 59, 30))
    with fake.install():
        start = clock.time()
        assert clock.monotonic() == 0.0
        clock.sleep(45)
        assert fake.sleeps == [45]
        assert clock.time() - start == 45
        assert clock.now() == datetime(2026, 11, 4, 0, 0, 15)
        assert clock.today() == date(2026, 11, 4)
        assert clock.monotonic() == 45
        fake.advance(15)
        assert clock.monotonic() == 60
    assert clock.monotonic() != 60  # the system clock is back


def test_a_fake_clock_never_goes_back():
    with pytest.raises(ValueError, match="does not go back"):
        FakeClock().advance(-1)
    fake = FakeClock()
    fake.sleep(-3)
    assert (fake.sleeps, fake.elapsed) == ([-3], 0.0)


def test_blocks_on_two_threads_may_end_in_any_order():
    first, second = FakeClock(), FakeClock(datetime(2027, 1, 1))
    first_block, second_block = first.install(), second.install()
    first_block.__enter__()
    second_block.__enter__()  # another thread's test starts while the first is still running
    first_block.__exit__(None, None, None)
    assert clock.now() == datetime(2027, 1, 1)  # the second test keeps its clock
    second_block.__exit__(None, None, None)
    assert abs((clock.now() - datetime.now()).total_seconds()) < 5  # and no fake is left behind


def test_use_restores_the_clock_before_it():
    outer, inner = FakeClock(), FakeClock(datetime(2027, 1, 1))
    with outer.install(), inner.install():
        assert clock.now() == datetime(2027, 1, 1)
    with outer.install():
        with pytest.raises(RuntimeError), inner.install():
            raise RuntimeError
        assert clock.now() == outer.now()
