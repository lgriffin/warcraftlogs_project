"""The one clock in the shared packages: wcl-core, wcl-store and wcl-app read the time and sleep only through here.

By default these are the system clock (``time.time``, ``time.monotonic``, ``time.sleep``, ``datetime.now``).
``use(clock)`` swaps in another clock for a block, process-wide like ``wcl_core.http.use`` so worker threads see it
too. The newest clock still in use wins, and blocks may end in any order (two test threads, say) without leaving a
clock behind. ``wcl_core.testing.FakeClock`` is the one tests use, so token expiry, retry backoff and "this week"
run without waiting or depending on the day. ``tests/test_clock.py`` fails on any other clock read in the packages.
"""

from __future__ import annotations

import threading
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


_clocks: list[Clock] = []  # every clock in use, newest last
_lock = threading.Lock()


def _current() -> Clock | None:
    clocks = _clocks
    return clocks[-1] if clocks else None


def time() -> float:
    clock = _current()
    return _time.time() if clock is None else clock.time()


def monotonic() -> float:
    clock = _current()
    return _time.monotonic() if clock is None else clock.monotonic()


def now() -> datetime:
    clock = _current()
    return datetime.now() if clock is None else clock.now()


def today() -> date:
    return now().date()


def sleep(seconds: float) -> None:
    clock = _current()
    if clock is None:
        _time.sleep(seconds)
    else:
        clock.sleep(seconds)


@contextmanager
def use(clock: Clock) -> Iterator[Clock]:
    """Read the time from *clock* in the block; afterwards the newest clock still in use, or the system's."""
    global _clocks
    with _lock:
        _clocks = [*_clocks, clock]
    try:
        yield clock
    finally:
        with _lock:
            # Drop this block's entry, wherever it now sits: another thread's block may have ended first.
            for i in range(len(_clocks) - 1, -1, -1):
                if _clocks[i] is clock:
                    _clocks = _clocks[:i] + _clocks[i + 1 :]
                    break
