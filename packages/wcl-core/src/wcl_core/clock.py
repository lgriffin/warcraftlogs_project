"""The one clock in the shared packages: wcl-core, wcl-store and wcl-app read the time and sleep only through here.

By default these are the system clock (``time.time``, ``time.monotonic``, ``time.sleep``, ``datetime.now``).
``use(clock)`` swaps in another clock for a block, process-wide like ``wcl_core.http.use`` so worker threads see it
too; ``wcl_core.testing.FakeClock`` is the one tests use, so token expiry, retry backoff and "this week" run without
waiting or depending on the day. ``tests/test_suite_health.py`` fails on any other clock read in the packages.
"""

from __future__ import annotations

import time as _time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "monotonic", "now", "sleep", "time", "today", "use"]


@runtime_checkable
class Clock(Protocol):
    def time(self) -> float:
        """Seconds since the epoch, for expiry times that are stored or compared with stored ones."""
        ...

    def monotonic(self) -> float:
        """Seconds on a clock that never goes back, for intervals."""
        ...

    def now(self) -> datetime:
        """The local wall-clock time, naive like ``datetime.now()``."""
        ...

    def sleep(self, seconds: float) -> None: ...


_clock: Clock | None = None


def time() -> float:
    return _time.time() if _clock is None else _clock.time()


def monotonic() -> float:
    return _time.monotonic() if _clock is None else _clock.monotonic()


def now() -> datetime:
    return datetime.now() if _clock is None else _clock.now()


def today() -> date:
    return now().date()


def sleep(seconds: float) -> None:
    if _clock is None:
        _time.sleep(seconds)
    else:
        _clock.sleep(seconds)


@contextmanager
def use(clock: Clock) -> Iterator[Clock]:
    """Read the time from *clock* in the block; the one in place before comes back afterwards."""
    global _clock
    before, _clock = _clock, clock
    try:
        yield clock
    finally:
        _clock = before
