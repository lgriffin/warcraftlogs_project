"""Tests for OAuth2 Authorization Code flow (user_auth module)."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import urlopen

import pytest
import requests
from pydantic import SecretStr

from warcraftlogs_client.common.errors import AuthenticationError
from warcraftlogs_client.user_auth import (
    OAuthCallbackServer,
    UserTokenManager,
)


class TestUserTokenManager:
    def test_not_authenticated_initially(self, tmp_path):
        tm = UserTokenManager(token_path=str(tmp_path / "token.json"))
        assert not tm.is_authenticated()

    def test_save_and_load_token(self, tmp_path):
        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = SecretStr("test_access")
        tm._refresh_token = SecretStr("test_refresh")
        tm._expires_at = time.time() + 3600
        tm._save()

        tm2 = UserTokenManager(token_path=path)
        assert tm2.is_authenticated()
        assert tm2._access_token.get_secret_value() == "test_access"
        assert tm2._refresh_token.get_secret_value() == "test_refresh"

    def test_get_token_returns_valid(self, tmp_path):
        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = SecretStr("valid_token")
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
        tm._access_token = SecretStr("test")
        tm._refresh_token = SecretStr("test")
        tm._expires_at = time.time() + 3600
        tm._save()
        assert Path(path).exists()

        tm.revoke()
        assert not tm.is_authenticated()
        assert not Path(path).exists()

    def test_is_authenticated_with_refresh_token_only(self, tmp_path):
        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = None
        tm._refresh_token = SecretStr("refresh_only")
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

        assert tm._access_token.get_secret_value() == "new_access"
        assert tm._refresh_token.get_secret_value() == "new_refresh"
        assert tm.is_authenticated()

        with Path(path).open() as f:
            saved = json.load(f)
        assert saved["access_token"] == "new_access"

    @patch("warcraftlogs_client.user_auth.requests.post")
    @patch("warcraftlogs_client.config.load_config")
    def test_refresh_updates_token(self, mock_config, mock_post, tmp_path):
        mock_config.return_value = {
            "client_id": "cid",
            "client_secret": "csec",
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
        tm._access_token = SecretStr("expired")
        tm._refresh_token = SecretStr("old_refresh")
        tm._expires_at = time.time() - 100  # expired
        tm._save()

        token = tm.get_token()
        assert token == "refreshed_access"

    @patch("warcraftlogs_client.user_auth.requests.post")
    @patch("warcraftlogs_client.config.load_config")
    def test_refresh_failure_revokes(self, mock_config, mock_post, tmp_path):
        mock_config.return_value = {
            "client_id": "cid",
            "client_secret": "csec",
        }
        mock_post.return_value = MagicMock(status_code=401)

        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = SecretStr("expired")
        tm._refresh_token = SecretStr("bad_refresh")
        tm._expires_at = time.time() - 100
        tm._save()

        with pytest.raises(AuthenticationError, match="refresh failed"):
            tm.get_token()
        assert not tm.is_authenticated()

    @patch("warcraftlogs_client.user_auth.requests.post")
    @patch("warcraftlogs_client.config.load_config")
    def test_refresh_connection_error(self, mock_config, mock_post, tmp_path):
        mock_config.return_value = {"client_id": "cid", "client_secret": "csec"}
        mock_post.side_effect = requests.ConnectionError("offline")

        path = str(tmp_path / "token.json")
        tm = UserTokenManager(token_path=path)
        tm._access_token = SecretStr("expired")
        tm._refresh_token = SecretStr("old_refresh")
        tm._expires_at = time.time() - 100
        tm._save()

        with pytest.raises(AuthenticationError, match="Cannot reach"):
            tm.get_token()

    @patch("warcraftlogs_client.user_auth.requests.post")
    def test_complete_auth_connection_error(self, mock_post, tmp_path):
        mock_post.side_effect = requests.ConnectionError("offline")

        tm = UserTokenManager(token_path=str(tmp_path / "token.json"))
        with pytest.raises(AuthenticationError, match="Cannot reach"):
            tm.complete_auth("code", "client_id", "client_secret")

    @patch("warcraftlogs_client.user_auth.requests.post")
    def test_complete_auth_timeout(self, mock_post, tmp_path):
        mock_post.side_effect = requests.Timeout("slow")

        tm = UserTokenManager(token_path=str(tmp_path / "token.json"))
        with pytest.raises(AuthenticationError, match="timed out"):
            tm.complete_auth("code", "client_id", "client_secret")

    @patch("warcraftlogs_client.user_auth.requests.post")
    def test_complete_auth_malformed_json(self, mock_post, tmp_path):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(side_effect=ValueError("not json")),
            text="<html>error</html>",
            headers={},
        )

        tm = UserTokenManager(token_path=str(tmp_path / "token.json"))
        with pytest.raises(AuthenticationError, match="invalid response"):
            tm.complete_auth("code", "client_id", "client_secret")

    @patch("warcraftlogs_client.user_auth._get_base_url", return_value="https://www.warcraftlogs.com")
    def test_build_authorize_url(self, _mock_base):
        url = UserTokenManager.build_authorize_url("my_client_id", "my_state", 8764)
        assert "warcraftlogs.com/oauth/authorize" in url
        assert "client_id=my_client_id" in url
        assert "state=my_state" in url
        assert "response_type=code" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8764%2Fcallback" in url

    def test_corrupted_token_file(self, tmp_path):
        path = str(tmp_path / "token.json")
        with Path(path).open("w") as f:
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


# ── Tokens a host stores (the Toads Hub) ──


def _hosted(expires_at, refresh="refresh-1", on_refresh=None, now=1_000.0):
    from wcl_core.user_auth import HostedUserToken, UserToken

    token = UserToken(SecretStr("access-1"), SecretStr(refresh) if refresh else None, expires_at)
    return HostedUserToken(
        token, "cid", "csecret", "https://fresh.warcraftlogs.com/oauth/token", on_refresh, lambda: now
    )


def _token_response(status=200, body=None):
    response = MagicMock(status_code=status)
    response.json.return_value = body if body is not None else {"access_token": "access-2", "expires_in": 3600}
    return response


class TestHostedUserToken:
    @patch("wcl_core.user_auth.requests.post")
    def test_a_fresh_token_is_used_as_is(self, post):
        assert _hosted(expires_at=2_000).get_token() == "access-1"
        post.assert_not_called()

    @patch("wcl_core.user_auth.requests.post")
    def test_an_expired_token_is_refreshed_and_handed_to_the_host(self, post):
        post.return_value = _token_response(body={"access_token": "access-2", "refresh_token": "r2", "expires_in": 600})
        saved = []
        tokens = _hosted(expires_at=900, on_refresh=saved.append)

        assert tokens.get_token() == "access-2"
        assert post.call_args.kwargs["data"]["grant_type"] == "refresh_token"
        assert post.call_args.kwargs["data"]["refresh_token"] == "refresh-1"
        [new] = saved
        assert new.refresh_token.get_secret_value() == "r2" and new.expires_at == 1_000 + 600 - 60
        assert tokens.token is new

    @patch("wcl_core.user_auth.requests.post")
    def test_the_refresh_token_is_kept_when_none_comes_back(self, post):
        post.return_value = _token_response()
        tokens = _hosted(expires_at=0)
        tokens.get_token()
        assert tokens.token.refresh_token.get_secret_value() == "refresh-1"

    @pytest.mark.parametrize(
        "outcome",
        [
            _token_response(status=400),
            _token_response(body={"nope": 1}),
            requests.ConnectionError("down"),
        ],
    )
    @patch("wcl_core.user_auth.requests.post")
    def test_a_failed_refresh_asks_for_a_new_sign_in(self, post, outcome):
        if isinstance(outcome, Exception):
            post.side_effect = outcome
        else:
            post.return_value = outcome
        with pytest.raises(AuthenticationError):
            _hosted(expires_at=0).get_token()

    def test_no_refresh_token_means_sign_in_again(self):
        with pytest.raises(AuthenticationError, match="sign in again"):
            _hosted(expires_at=0, refresh=None).get_token()


def test_user_and_token_urls_follow_the_client_api_site():
    from wcl_core.user_auth import token_url_for, user_api_url

    assert user_api_url("https://fresh.warcraftlogs.com/api/v2/client") == "https://fresh.warcraftlogs.com/api/v2/user"
    assert token_url_for("https://fresh.warcraftlogs.com/api/v2/client") == "https://fresh.warcraftlogs.com/oauth/token"
    assert user_api_url("") == "https://www.warcraftlogs.com/api/v2/user"
