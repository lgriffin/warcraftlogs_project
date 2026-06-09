"""Tests for OAuth2 Authorization Code flow (user_auth module)."""

import json
import os
import time
import threading
from unittest.mock import patch, MagicMock
from urllib.request import urlopen

import pytest

from warcraftlogs_client.user_auth import (
    UserTokenManager,
    OAuthCallbackServer,
    AUTHORIZE_URL,
    DEFAULT_REDIRECT_PORT,
)


class TestUserTokenManager:
    def test_not_authenticated_initially(self, tmp_path):
        tm = UserTokenManager(token_path=str(tmp_path / "token.json"))
        assert not tm.is_authenticated()

    def test_save_and_load_token(self, tmp_path):
        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = "test_access"
        tm._refresh_token = "test_refresh"
        tm._expires_at = time.time() + 3600
        tm._save()

        tm2 = UserTokenManager(token_path=path)
        assert tm2.is_authenticated()
        assert tm2._access_token == "test_access"
        assert tm2._refresh_token == "test_refresh"

    def test_get_token_returns_valid(self, tmp_path):
        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = "valid_token"
        tm._expires_at = time.time() + 3600
        tm._save()

        tm2 = UserTokenManager(token_path=path)
        assert tm2.get_token() == "valid_token"

    def test_get_token_raises_when_not_authenticated(self, tmp_path):
        tm = UserTokenManager(token_path=str(tmp_path / "token.json"))
        with pytest.raises(RuntimeError, match="Not authenticated"):
            tm.get_token()

    def test_revoke_clears_token(self, tmp_path):
        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = "test"
        tm._refresh_token = "test"
        tm._expires_at = time.time() + 3600
        tm._save()
        assert os.path.exists(path)

        tm.revoke()
        assert not tm.is_authenticated()
        assert not os.path.exists(path)

    def test_is_authenticated_with_refresh_token_only(self, tmp_path):
        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = None
        tm._refresh_token = "refresh_only"
        tm._expires_at = 0
        tm._save()

        tm2 = UserTokenManager(token_path=path)
        assert tm2.is_authenticated()

    @patch("warcraftlogs_client.user_auth.requests.post")
    def test_complete_auth_saves_token(self, mock_post, tmp_path):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "access_token": "new_access",
                "refresh_token": "new_refresh",
                "expires_in": 3600,
            },
        )
        mock_post.return_value.raise_for_status = MagicMock()

        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm.complete_auth("test_code", "client_id", "client_secret")

        assert tm._access_token == "new_access"
        assert tm._refresh_token == "new_refresh"
        assert tm.is_authenticated()

        with open(path) as f:
            saved = json.load(f)
        assert saved["access_token"] == "new_access"

    @patch("warcraftlogs_client.user_auth.requests.post")
    @patch("warcraftlogs_client.config.load_config")
    def test_refresh_updates_token(self, mock_config, mock_post, tmp_path):
        mock_config.return_value = {
            "client_id": "cid", "client_secret": "csec",
        }
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "access_token": "refreshed_access",
                "refresh_token": "refreshed_refresh",
                "expires_in": 3600,
            },
        )

        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = "expired"
        tm._refresh_token = "old_refresh"
        tm._expires_at = time.time() - 100  # expired
        tm._save()

        token = tm.get_token()
        assert token == "refreshed_access"

    @patch("warcraftlogs_client.user_auth.requests.post")
    @patch("warcraftlogs_client.config.load_config")
    def test_refresh_failure_revokes(self, mock_config, mock_post, tmp_path):
        mock_config.return_value = {
            "client_id": "cid", "client_secret": "csec",
        }
        mock_post.return_value = MagicMock(status_code=401)

        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = "expired"
        tm._refresh_token = "bad_refresh"
        tm._expires_at = time.time() - 100
        tm._save()

        with pytest.raises(RuntimeError, match="refresh failed"):
            tm.get_token()
        assert not tm.is_authenticated()

    def test_build_authorize_url(self):
        url = UserTokenManager.build_authorize_url("my_client_id", "my_state", 8764)
        assert AUTHORIZE_URL in url
        assert "client_id=my_client_id" in url
        assert "state=my_state" in url
        assert "response_type=code" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8764%2Fcallback" in url

    def test_corrupted_token_file(self, tmp_path):
        path = str(tmp_path / "token.json")
        with open(path, "w") as f:
            f.write("not valid json{{{")

        tm = UserTokenManager(token_path=path)
        assert not tm.is_authenticated()


class TestOAuthCallbackServer:
    def test_server_receives_callback(self):
        server = OAuthCallbackServer(port=0)
        server._server = None

        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        server = OAuthCallbackServer(port=port, timeout=5)
        server.start()

        try:
            resp = urlopen(
                f"http://127.0.0.1:{port}/callback?code=test_code&state=test_state",
                timeout=3,
            )
            assert resp.status == 200
        except Exception:
            pass

        result = server.wait(timeout=5)
        server.shutdown()

        assert result is not None
        assert result["code"] == "test_code"
        assert result["state"] == "test_state"

    def test_server_handles_error(self):
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        server = OAuthCallbackServer(port=port, timeout=5)
        server.start()

        try:
            urlopen(
                f"http://127.0.0.1:{port}/callback?error=access_denied",
                timeout=3,
            )
        except Exception:
            pass

        result = server.wait(timeout=5)
        server.shutdown()

        assert result is not None
        assert result["error"] == "access_denied"
