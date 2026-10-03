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


def clock_reads(source: str) -> list[str]:
    """Each place *source* reads the system clock, as ``line: what``."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and ast.unparse(node) in SYSTEM_CLOCK:
            found.append(f"{node.lineno}: {ast.unparse(node)}")
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


def test_use_restores_the_clock_before_it():
    outer, inner = FakeClock(), FakeClock(datetime(2027, 1, 1))
    with outer.install(), inner.install():
        assert clock.now() == datetime(2027, 1, 1)
    with outer.install():
        with pytest.raises(RuntimeError), inner.install():
            raise RuntimeError
        assert clock.now() == outer.now()
