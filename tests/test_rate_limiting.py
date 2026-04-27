"""Tests for API client rate limiting and retry logic."""

import time
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from warcraftlogs_client.client import WarcraftLogsClient


@pytest.fixture
def client():
    tm = MagicMock()
    tm.get_token.return_value = "test_token"
    c = WarcraftLogsClient(tm, cache_enabled=False)
    c.MIN_REQUEST_INTERVAL = 0.01
    return c


class TestThrottle:
    def test_first_call_no_delay(self, client):
        client._last_request_time = 0.0
        start = time.monotonic()
        client._throttle()
        assert time.monotonic() - start < 0.1

    def test_enforces_interval(self, client):
        client.MIN_REQUEST_INTERVAL = 0.1
        client._last_request_time = time.monotonic()
        start = time.monotonic()
        client._throttle()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05


class TestRetryOn429:
    @patch("warcraftlogs_client.client.requests.post")
    @patch("warcraftlogs_client.client.time.sleep")
    def test_retries_on_429(self, mock_sleep, mock_post, client):
        rate_limited = MagicMock(status_code=429)
        success = MagicMock(
            status_code=200,
            json=lambda: {"data": {}},
            raise_for_status=lambda: None,
        )
        mock_post.side_effect = [rate_limited, success]

        result = client.run_query("{ test }")
        assert result == {"data": {}}
        assert mock_post.call_count == 2

    @patch("warcraftlogs_client.client.requests.post")
    @patch("warcraftlogs_client.client.time.sleep")
    def test_retries_on_500(self, mock_sleep, mock_post, client):
        server_error = MagicMock(status_code=500)
        success = MagicMock(
            status_code=200,
            json=lambda: {"data": {"ok": True}},
            raise_for_status=lambda: None,
        )
        mock_post.side_effect = [server_error, success]

        result = client.run_query("{ test }")
        assert result == {"data": {"ok": True}}
        assert mock_post.call_count == 2

    @patch("warcraftlogs_client.client.requests.post")
    @patch("warcraftlogs_client.client.time.sleep")
    def test_exponential_backoff(self, mock_sleep, mock_post, client):
        error = MagicMock(status_code=429)
        success = MagicMock(
            status_code=200,
            json=lambda: {"data": {}},
            raise_for_status=lambda: None,
        )
        mock_post.side_effect = [error, error, success]

        client.run_query("{ test }")

        backoff_calls = [c for c in mock_sleep.call_args_list if c[0][0] >= 1]
        assert len(backoff_calls) == 2
        assert backoff_calls[0] == call(1)
        assert backoff_calls[1] == call(2)

    @patch("warcraftlogs_client.client.requests.post")
    @patch("warcraftlogs_client.client.time.sleep")
    def test_max_retries_exhausted_raises(self, mock_sleep, mock_post, client):
        error_response = MagicMock(status_code=429)
        error_response.raise_for_status.side_effect = requests.HTTPError("429")
        mock_post.return_value = error_response

        with pytest.raises(requests.HTTPError):
            client.run_query("{ test }")
        assert mock_post.call_count == client.MAX_RETRIES


class TestNoRetryOnClientError:
    @patch("warcraftlogs_client.client.requests.post")
    @patch("warcraftlogs_client.client.time.sleep")
    def test_400_raises_immediately(self, mock_sleep, mock_post, client):
        bad_request = MagicMock(status_code=400)
        bad_request.raise_for_status.side_effect = requests.HTTPError("400")
        mock_post.return_value = bad_request

        with pytest.raises(requests.HTTPError):
            client.run_query("{ test }")
        assert mock_post.call_count == 1
