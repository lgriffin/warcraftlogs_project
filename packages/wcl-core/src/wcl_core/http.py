"""The one HTTP seam in wcl-core: every request to Warcraft Logs or Discord goes through ``post`` or ``get`` here.

By default they are ``requests.post`` and ``requests.get``, looked up when called, so a test that patches
``requests.post`` still sees every call. ``use(transport)`` swaps in another transport for a block; the fake in
``wcl_core.testing`` is the one tests use. Callers keep catching ``requests`` exceptions, which a transport raises too.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import requests


class Response(Protocol):
    """What wcl-core reads from a response."""

    status_code: int
    text: str

    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


class Transport(Protocol):
    def post(self, url: str, *, timeout: float, **kwargs: Any) -> Response: ...

    def get(self, url: str, *, timeout: float, **kwargs: Any) -> Response: ...


_transport: Transport | None = None


def post(url: str, *, timeout: float, **kwargs: Any) -> Response:
    """POST *url*; every request names its timeout."""
    if _transport is None:
        return requests.post(url, timeout=timeout, **kwargs)
    return _transport.post(url, timeout=timeout, **kwargs)


def get(url: str, *, timeout: float, **kwargs: Any) -> Response:
    """GET *url*; every request names its timeout."""
    if _transport is None:
        return requests.get(url, timeout=timeout, **kwargs)
    return _transport.get(url, timeout=timeout, **kwargs)


@contextmanager
def use(transport: Transport) -> Iterator[Transport]:
    """Send every request in the block through *transport*; the one in place before comes back afterwards."""
    global _transport
    before, _transport = _transport, transport
    try:
        yield transport
    finally:
        _transport = before
