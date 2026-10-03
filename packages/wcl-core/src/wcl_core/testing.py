"""Fake Warcraft Logs and Discord for tests: they answer at the HTTP seam and record every request.

Tests use them in place of patching ``requests`` or a service method, so the real client, token manager and
analysis code all run. Shipped in wcl-core so the desktop app, the Toads Hub and the bot test against one fake::

    wcl = FakeWarcraftLogs()
    wcl.answer("reportData", {"reportData": {"report": {"title": "Kara", "owner": {"name": "Toad"}, "startTime": 0}}})
    with wcl.install():
        raid = wcl.client().get_report_metadata("abc")
    assert raid.title == "Kara" and wcl.queries[0].variables == {"code": "abc"}

``FakeClock`` stands in for the system clock the same way: ``with FakeClock().install() as clock`` makes token
expiry, retry backoff and "today" deterministic, and ``clock.sleeps`` records every wait instead of waiting.

A reply is a dict (the JSON body; for ``answer`` the GraphQL ``data``), a ``FakeResponse``, an exception to raise
(``requests.ConnectionError``, ``requests.Timeout``), or for ``answer`` a callable taking the query and variables and
returning the data. Given several replies, each request takes the next and the last one repeats. A request nothing
answers raises ``UnexpectedRequest``, so a test never quietly reaches the network.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import requests

from . import clock, discord_auth, http
from .auth import TokenManager
from .client import DEFAULT_API_URL, WarcraftLogsClient

__all__ = [
    "FakeClock",
    "FakeDiscord",
    "FakeResponse",
    "FakeWarcraftLogs",
    "Request",
    "UnexpectedRequest",
    "grant",
    "invalid_json",
    "status",
]

_NO_BODY = object()

Reply = Any  # dict | FakeResponse | BaseException | Callable[[str, dict], Any]


class UnexpectedRequest(AssertionError):
    """A request the fake has no answer for."""


class FakeResponse:
    """A response with what wcl-core reads: status, JSON body, text and ``raise_for_status``."""

    def __init__(self, status_code: int = 200, body: Any = _NO_BODY, text: str | None = None) -> None:
        self.status_code = status_code
        self._body = body
        if text is not None:
            self.text = text
        else:
            self.text = "" if body is _NO_BODY else json.dumps(body)

    def json(self) -> Any:
        if self._body is _NO_BODY:
            raise ValueError(f"not JSON: {self.text[:80]!r}")
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeClock:
    """A clock that moves only when told: ``sleep`` and ``advance`` move it on, and ``sleeps`` records every wait."""

    def __init__(self, start: datetime = datetime(2026, 11, 3, 20, 0)) -> None:
        self.start = start
        self.elapsed = 0.0
        self.sleeps: list[float] = []

    @contextmanager
    def install(self) -> Iterator[FakeClock]:
        """Read every wcl-core, wcl-store and wcl-app time from this clock for the block."""
        with clock.use(self):
            yield self

    def advance(self, seconds: float) -> FakeClock:
        if seconds < 0:
            raise ValueError("a clock does not go back")
        self.elapsed += seconds
        return self

    def time(self) -> float:
        return self.start.timestamp() + self.elapsed

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.elapsed)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(max(0.0, seconds))


def grant(access_token: str, expires_in: int = 3600, **extra: Any) -> dict:
    """A token endpoint reply granting *access_token* for *expires_in* seconds."""
    return {"access_token": access_token, "token_type": "Bearer", "expires_in": expires_in, **extra}


def status(code: int, text: str = "") -> FakeResponse:
    """A reply with HTTP *code* and no JSON body."""
    return FakeResponse(code, text=text)


def invalid_json(text: str = "<html>not json</html>") -> FakeResponse:
    """A 200 whose body is not JSON."""
    return FakeResponse(200, text=text)


@dataclass
class Request:
    """One request the fake received."""

    method: str
    url: str
    timeout: float
    headers: dict = field(default_factory=dict)
    data: dict | None = None
    json: dict | None = None

    @property
    def query(self) -> str:
        return (self.json or {}).get("query", "")

    @property
    def variables(self) -> dict:
        return (self.json or {}).get("variables") or {}


class _Script:
    """Replies taken in order; the last one repeats."""

    def __init__(self, replies: tuple[Reply, ...]) -> None:
        if not replies:
            raise ValueError("give at least one reply")
        self._replies = list(replies)

    def next(self) -> Reply:
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]


def _respond(reply: Reply) -> FakeResponse:
    if isinstance(reply, BaseException):
        raise reply
    if isinstance(reply, FakeResponse):
        return reply
    return FakeResponse(200, reply)


class _FakeHost:
    """A transport that records every request and hands it to ``_route``; anything it does not route fails loudly."""

    def __init__(self) -> None:
        self.requests: list[Request] = []

    @contextmanager
    def install(self) -> Iterator[Any]:
        """Route every wcl-core request through this fake for the block."""
        with http.use(self):
            yield self

    def post(self, url: str, *, timeout: float, **kwargs: Any) -> FakeResponse:
        return self._handle("POST", url, timeout, kwargs)

    def get(self, url: str, *, timeout: float, **kwargs: Any) -> FakeResponse:
        return self._handle("GET", url, timeout, kwargs)

    def _handle(self, method: str, url: str, timeout: float, kwargs: dict) -> FakeResponse:
        request = Request(method, url, timeout, kwargs.get("headers") or {}, kwargs.get("data"), kwargs.get("json"))
        self.requests.append(request)
        return self._route(request)

    def _route(self, request: Request) -> FakeResponse:
        raise NotImplementedError


class FakeWarcraftLogs(_FakeHost):
    """Warcraft Logs at the HTTP seam: ``/oauth/token`` and ``/api/v2/`` on any ``warcraftlogs.com`` host."""

    def __init__(self) -> None:
        super().__init__()
        self._token = _Script((grant("fake-token"),))
        self._answers: list[tuple[str, _Script]] = []

    def token(self, *replies: Reply) -> FakeWarcraftLogs:
        """How the token endpoint answers, in order. By default it grants ``fake-token`` for an hour."""
        self._token = _Script(replies)
        return self

    def answer(self, contains: str, *replies: Reply) -> FakeWarcraftLogs:
        """Answer GraphQL queries containing *contains*; the first registered match wins."""
        self._answers.append((contains, _Script(replies)))
        return self

    @property
    def token_requests(self) -> list[Request]:
        return [r for r in self.requests if _is_token(r.url)]

    @property
    def queries(self) -> list[Request]:
        return [r for r in self.requests if not _is_token(r.url)]

    def client(self, api_url: str = DEFAULT_API_URL) -> WarcraftLogsClient:
        """A real client against this fake: no response cache, no throttle."""
        client = WarcraftLogsClient(TokenManager("fake-id", "fake-secret"), cache_enabled=False, api_url=api_url)
        client.MIN_REQUEST_INTERVAL = 0
        return client

    def _route(self, request: Request) -> FakeResponse:
        host = urlparse(request.url).hostname or ""
        if not (host == "warcraftlogs.com" or host.endswith(".warcraftlogs.com")):
            raise UnexpectedRequest(f"{request.method} {request.url}: not Warcraft Logs")
        if request.method == "POST" and _is_token(request.url):
            return _respond(self._token.next())
        if request.method == "POST" and "/api/v2/" in urlparse(request.url).path:
            return self._graphql(request)
        raise UnexpectedRequest(f"{request.method} {request.url}: no such Warcraft Logs endpoint")

    def _graphql(self, request: Request) -> FakeResponse:
        for contains, script in self._answers:
            if contains in request.query:
                reply = script.next()
                if callable(reply) and not isinstance(reply, (BaseException, FakeResponse)):
                    return FakeResponse(200, {"data": reply(request.query, request.variables)})
                if isinstance(reply, dict):
                    return FakeResponse(200, {"data": reply})
                return _respond(reply)
        raise UnexpectedRequest(f"no answer for query: {request.query[:200]}")


class FakeDiscord(_FakeHost):
    """Discord's OAuth token and ``/users/@me`` endpoints at ``discord_auth.oauth_base_url()``."""

    def __init__(self) -> None:
        super().__init__()
        self._token = _Script(({**grant("fake-discord-token", 604_800), "refresh_token": "fake-discord-refresh"},))
        self._user = _Script(({"id": "123456789", "username": "toad"},))

    def token(self, *replies: Reply) -> FakeDiscord:
        """How ``/api/oauth2/token`` answers, in order. By default it grants a week-long token."""
        self._token = _Script(replies)
        return self

    def user(self, *replies: Reply) -> FakeDiscord:
        """How ``/api/users/@me`` answers, in order. By default it is ``toad``, id ``123456789``."""
        self._user = _Script(replies)
        return self

    def _route(self, request: Request) -> FakeResponse:
        base = discord_auth.oauth_base_url()
        if request.method == "POST" and request.url == f"{base}/api/oauth2/token":
            return _respond(self._token.next())
        if request.method == "GET" and request.url == f"{base}/api/users/@me":
            return _respond(self._user.next())
        raise UnexpectedRequest(f"{request.method} {request.url}: no such Discord endpoint")


def _is_token(url: str) -> bool:
    return urlparse(url).path.rstrip("/").endswith("/oauth/token")
