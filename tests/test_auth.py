"""Tests for TokenManager — OAuth2 client credentials flow."""

import time
from unittest.mock import MagicMock, patch

import pytest

from warcraftlogs_client.auth import TokenManager


@pytest.fixture
def tm():
    return TokenManager("test_id", "test_secret")


class TestIsTokenValid:
    def test_no_token(self, tm):
        assert not tm._is_token_valid()

    def test_valid_token(self, tm):
        tm.access_token = "tok123"
        tm.token_expiry = time.time() + 3600
        assert tm._is_token_valid() is True

    def test_expired_token(self, tm):
        tm.access_token = "tok123"
        tm.token_expiry = time.time() - 10
        assert tm._is_token_valid() is False


class TestGetNewToken:
    @patch("warcraftlogs_client.auth.requests.post")
    def test_requests_token(self, mock_post, tm):
        mock_post.return_value = MagicMock(
            json=lambda: {"access_token": "new_tok", "expires_in": 3600},
            raise_for_status=lambda: None,
        )
        tm._get_new_token()
        assert tm.access_token == "new_tok"
        assert tm.token_expiry > time.time()
        mock_post.assert_called_once()

    @patch("warcraftlogs_client.auth.requests.post")
    def test_auth_header_encoding(self, mock_post, tm):
        mock_post.return_value = MagicMock(
            json=lambda: {"access_token": "tok", "expires_in": 3600},
            raise_for_status=lambda: None,
        )
        tm._get_new_token()
        call_kwargs = mock_post.call_args
        auth_header = call_kwargs[1]["headers"]["Authorization"]
        assert auth_header.startswith("Basic ")

    @patch("warcraftlogs_client.auth.requests.post")
    def test_expiry_safety_margin(self, mock_post, tm):
        mock_post.return_value = MagicMock(
            json=lambda: {"access_token": "tok", "expires_in": 3600},
            raise_for_status=lambda: None,
        )
        before = time.time()
        tm._get_new_token()
        expected_max = before + 3600 - 60
        assert tm.token_expiry <= expected_max + 1


class TestGetToken:
    @patch("warcraftlogs_client.auth.requests.post")
    def test_caches_token(self, mock_post, tm):
        mock_post.return_value = MagicMock(
            json=lambda: {"access_token": "cached", "expires_in": 3600},
            raise_for_status=lambda: None,
        )
        t1 = tm.get_token()
        t2 = tm.get_token()
        assert t1 == t2 == "cached"
        assert mock_post.call_count == 1

    @patch("warcraftlogs_client.auth.requests.post")
    def test_refreshes_expired(self, mock_post, tm):
        mock_post.return_value = MagicMock(
            json=lambda: {"access_token": "first", "expires_in": 3600},
            raise_for_status=lambda: None,
        )
        tm.get_token()
        tm.token_expiry = time.time() - 10
        mock_post.return_value = MagicMock(
            json=lambda: {"access_token": "second", "expires_in": 3600},
            raise_for_status=lambda: None,
        )
        result = tm.get_token()
        assert result == "second"
        assert mock_post.call_count == 2

    @patch("warcraftlogs_client.auth.requests.post")
    def test_http_error_propagates(self, mock_post, tm):
        from requests.exceptions import HTTPError
        mock_post.return_value = MagicMock(
            raise_for_status=MagicMock(side_effect=HTTPError("401")),
        )
        with pytest.raises(HTTPError):
            tm.get_token()
