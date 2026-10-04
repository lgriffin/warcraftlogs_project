"""Tests for API client rate limiting and retry logic, on a fake clock so nothing waits."""

import pytest
import requests
from wcl_core.testing import FakeClock, FakeWarcraftLogs, status

from warcraftlogs_client.client import WarcraftLogsClient


@pytest.fixture
def wcl():
    fake = FakeWarcraftLogs()
    with fake.install():
        yield fake


@pytest.fixture
def fake_clock():
    with FakeClock().install() as fake:
        yield fake


@pytest.fixture
def client(wcl):
    c = wcl.client()
    c.MIN_REQUEST_INTERVAL = 0.5
    return c


class TestThrottle:
    def test_first_call_no_delay(self, wcl, client, fake_clock):
        wcl.answer("test", {"ok": True})
        client.run_query("{ test }")
        assert fake_clock.sleeps == []

    def test_enforces_interval(self, client, fake_clock):
        fake_clock.advance(10)
        client._last_request_time = 9.8
        client._throttle()
        assert fake_clock.sleeps == [pytest.approx(0.3)]

    def test_back_to_back_queries_are_spaced(self, wcl, client, fake_clock):
        wcl.answer("test", {"ok": True})
        client.run_query("{ test }")
        client.run_query("{ test }")
        assert fake_clock.sleeps == [pytest.approx(0.5)]
        assert WarcraftLogsClient.MIN_REQUEST_INTERVAL > 0


class TestRetryOn429:
    @pytest.mark.parametrize("code", [429, 500])
    def test_retries_then_succeeds(self, wcl, client, fake_clock, code):
        wcl.answer("test", status(code), {"ok": True})
        assert client.run_query("{ test }") == {"data": {"ok": True}}
        assert len(wcl.queries) == 2

    def test_exponential_backoff(self, wcl, client, fake_clock):
        wcl.answer("test", status(429), status(429), {})
        client.run_query("{ test }")
        assert fake_clock.sleeps == [1, 2]

    def test_max_retries_exhausted_raises(self, wcl, client, fake_clock):
        wcl.answer("test", status(429))
        with pytest.raises(requests.HTTPError):
            client.run_query("{ test }")
        assert len(wcl.queries) == client.MAX_RETRIES


class TestNoRetryOnClientError:
    def test_400_raises_immediately(self, wcl, client, fake_clock):
        wcl.answer("test", status(400))
        with pytest.raises(requests.HTTPError):
            client.run_query("{ test }")
        assert len(wcl.queries) == 1
