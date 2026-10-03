"""
OAuth2 Authorization Code flow for WarcraftLogs user-level API access.

The Client Credentials flow (/api/v2/client) only exposes public data.
To access detailed event/table data for reports the user doesn't own,
we need a user-scoped token via the Authorization Code flow (/api/v2/user).
"""

import contextlib
import json
import logging
import secrets
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from pydantic import SecretStr

from . import clock, http, paths
from .common.errors import AuthenticationError
from .config import as_secret

logger = logging.getLogger(__name__)

DEFAULT_REDIRECT_PORT = 8764


def _get_base_url() -> str:
    """Derive the WCL domain from the configured API URL."""
    from .config import load_config

    try:
        api_url = load_config().get("wcl_api_url", "")
        parsed = urlparse(api_url)
        if parsed.hostname:
            return f"{parsed.scheme}://{parsed.hostname}"
    except Exception:  # noqa: BLE001, S110 - no readable config means the default domain
        pass
    return "https://www.warcraftlogs.com"


def get_authorize_url() -> str:
    return f"{_get_base_url()}/oauth/authorize"


def get_token_url() -> str:
    return f"{_get_base_url()}/oauth/token"


class UserTokenManager:
    """Manages OAuth2 user tokens with persistence and refresh."""

    def __init__(self, token_path: str | None = None) -> None:
        self._token_path = token_path or str(paths.get_user_token_path())
        self._access_token: SecretStr | None = None
        self._refresh_token: SecretStr | None = None
        self._expires_at: float = 0
        self._load()

    def _load(self) -> None:
        try:
            with Path(self._token_path).open() as f:
                data = json.load(f)
            self._access_token = _optional_secret(data.get("access_token"))
            self._refresh_token = _optional_secret(data.get("refresh_token"))
            self._expires_at = data.get("expires_at", 0)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def _save(self) -> None:
        data = {
            "access_token": _reveal(self._access_token),
            "refresh_token": _reveal(self._refresh_token),
            "expires_at": self._expires_at,
        }
        with Path(self._token_path).open("w") as f:
            json.dump(data, f, indent=2)

    def is_authenticated(self) -> bool:
        return bool(self._access_token or self._refresh_token)

    def get_token(self) -> str:
        if self._access_token and clock.time() < self._expires_at:
            return self._access_token.get_secret_value()
        if self._refresh_token:
            self._refresh()
            if self._access_token:
                return self._access_token.get_secret_value()
        raise RuntimeError("Not authenticated — user must complete OAuth flow first")

    def _refresh(self) -> None:
        from .config import load_config

        config = load_config()
        client_id = config["client_id"]
        client_secret = as_secret(config["client_secret"])

        token_url = get_token_url()
        try:
            response = http.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": _reveal(self._refresh_token),
                    "client_id": client_id,
                    "client_secret": client_secret.get_secret_value(),
                },
                timeout=30,
            )
        except requests.ConnectionError as e:
            raise AuthenticationError("Cannot reach WarcraftLogs — check your internet connection") from e
        except requests.Timeout as e:
            raise AuthenticationError("WarcraftLogs authentication timed out — try again later") from e

        if response.status_code != 200:
            self.revoke()
            raise AuthenticationError("Token refresh failed — please re-authenticate")

        try:
            token_data = response.json()
            self._access_token = SecretStr(token_data["access_token"])
        except (ValueError, KeyError) as e:
            self.revoke()
            raise AuthenticationError("Received invalid response during token refresh", details=str(e)) from e

        self._refresh_token = _optional_secret(token_data.get("refresh_token")) or self._refresh_token
        self._expires_at = clock.time() + token_data.get("expires_in", 3600) - 60
        self._save()

    def complete_auth(
        self,
        code: str,
        client_id: str,
        client_secret: str | SecretStr,
        redirect_port: int = DEFAULT_REDIRECT_PORT,
    ) -> None:
        client_secret = as_secret(client_secret)
        redirect_uri = f"http://localhost:{redirect_port}/callback"
        token_url = get_token_url()
        # Never log the client secret, the authorization code, or anything from the token response.
        logger.info("Token exchange: POST %s (redirect_uri=%s)", token_url, redirect_uri)

        try:
            response = http.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret.get_secret_value(),
                },
                timeout=30,
            )
        except requests.ConnectionError as e:
            raise AuthenticationError("Cannot reach WarcraftLogs — check your internet connection") from e
        except requests.Timeout as e:
            raise AuthenticationError("WarcraftLogs authentication timed out — try again later") from e

        logger.info("Token response: %d", response.status_code)

        if response.status_code != 200:
            raise AuthenticationError(f"Token exchange failed (HTTP {response.status_code})", details=response.text)

        try:
            token_data = response.json()
            self._access_token = SecretStr(token_data["access_token"])
        except (ValueError, KeyError) as e:
            raise AuthenticationError("Received invalid response during token exchange", details=str(e)) from e

        self._refresh_token = _optional_secret(token_data.get("refresh_token"))
        self._expires_at = clock.time() + token_data.get("expires_in", 3600) - 60
        self._save()
        logger.info("Token exchange successful, token saved.")

    def revoke(self) -> None:
        self._access_token = None
        self._refresh_token = None
        self._expires_at = 0
        with contextlib.suppress(OSError):
            Path(self._token_path).unlink()

    @staticmethod
    def build_authorize_url(client_id: str, state: str, redirect_port: int = DEFAULT_REDIRECT_PORT) -> str:
        params = {
            "client_id": client_id,
            "redirect_uri": f"http://localhost:{redirect_port}/callback",
            "response_type": "code",
            "state": state,
        }
        return f"{get_authorize_url()}?{urlencode(params)}"


def user_api_url(api_url: str) -> str:
    """The user-scoped API next to a client API URL: ``.../api/v2/client`` -> ``.../api/v2/user``."""
    parsed = urlparse(api_url)
    host = f"{parsed.scheme}://{parsed.hostname}" if parsed.hostname else "https://www.warcraftlogs.com"
    return f"{host}/api/v2/user"


def token_url_for(api_url: str) -> str:
    """The OAuth token endpoint on the same Warcraft Logs site as ``api_url``."""
    parsed = urlparse(api_url)
    host = f"{parsed.scheme}://{parsed.hostname}" if parsed.hostname else "https://www.warcraftlogs.com"
    return f"{host}/oauth/token"


@dataclass(frozen=True)
class UserToken:
    """A user's Warcraft Logs token as a host keeps it. ``expires_at`` is epoch seconds."""

    access_token: SecretStr
    refresh_token: SecretStr | None
    expires_at: float


class HostedUserToken:
    """A user token the host stores (the Toads Hub keeps it encrypted in its database), refreshed when it expires.

    Reads no config or token file, unlike ``UserTokenManager``. ``on_refresh`` receives each new token so the host
    can store it; Warcraft Logs may rotate the refresh token. A refused refresh raises ``AuthenticationError``, and
    the host should then ask for a new sign-in.
    """

    def __init__(
        self,
        token: UserToken,
        client_id: str,
        client_secret: str | SecretStr,
        token_url: str,
        on_refresh: Callable[[UserToken], None] | None = None,
        clock: Callable[[], float] = clock.time,
    ) -> None:
        self._token = token
        self._client_id = client_id
        self._client_secret = as_secret(client_secret)
        self._token_url = token_url
        self._on_refresh = on_refresh
        self._clock = clock

    @property
    def token(self) -> UserToken:
        return self._token

    def get_token(self) -> str:
        if self._clock() < self._token.expires_at:
            return self._token.access_token.get_secret_value()
        if self._token.refresh_token is None:
            raise AuthenticationError("The Warcraft Logs sign-in has expired; sign in again")
        self._token = self._refresh(self._token.refresh_token)
        if self._on_refresh is not None:
            self._on_refresh(self._token)
        return self._token.access_token.get_secret_value()

    def _refresh(self, refresh_token: SecretStr) -> UserToken:
        try:
            response = http.post(
                self._token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token.get_secret_value(),
                    "client_id": self._client_id,
                    "client_secret": self._client_secret.get_secret_value(),
                },
                timeout=30,
            )
        except requests.RequestException as e:
            raise AuthenticationError("Cannot reach Warcraft Logs to refresh the sign-in") from e
        if response.status_code != 200:
            raise AuthenticationError(f"Warcraft Logs refused the sign-in refresh (HTTP {response.status_code})")
        try:
            data = response.json()
            access = SecretStr(data["access_token"])
            expires_in = float(data.get("expires_in", 3600))
        except (ValueError, KeyError, TypeError) as e:
            raise AuthenticationError("Warcraft Logs sent an unreadable token") from e
        return UserToken(
            access_token=access,
            refresh_token=_optional_secret(data.get("refresh_token")) or refresh_token,
            expires_at=self._clock() + expires_in - 60,
        )


def _optional_secret(value: str | None) -> SecretStr | None:
    return SecretStr(value) if value else None


def _reveal(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


class _CallbackServer(HTTPServer):
    """The callback server; the handler leaves the redirect's parameters in ``auth_result``."""

    auth_result: dict[str, Any] | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth redirect callback."""

    server: _CallbackServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if error:
            self.wfile.write(
                b"<html><body><h2>Authorization failed</h2><p>You can close this window.</p></body></html>"
            )
            self.server.auth_result = {"error": error}
        elif code:
            self.wfile.write(
                b"<html><body><h2>Authorization successful!</h2>"
                b"<p>You can close this window and return to the app.</p></body></html>"
            )
            self.server.auth_result = {"code": code, "state": state}
        else:
            self.wfile.write(b"<html><body><h2>Unexpected response</h2><p>You can close this window.</p></body></html>")
            self.server.auth_result = {"error": "no_code"}

    def log_message(self, *args: Any) -> None:
        pass


class OAuthCallbackServer:
    """Local HTTP server that waits for the OAuth callback."""

    def __init__(self, port: int = DEFAULT_REDIRECT_PORT, timeout: int = 120) -> None:
        self._port = port
        self._timeout = timeout
        self._server: _CallbackServer | None = None
        self._thread: Thread | None = None
        self.result: dict | None = None

    def start(self) -> None:
        server = _CallbackServer(("127.0.0.1", self._port), _CallbackHandler)
        server.timeout = self._timeout
        self._server = server

        def serve() -> None:
            server.handle_request()
            self.result = server.auth_result

        self._thread = Thread(target=serve, daemon=True)
        self._thread.start()

    def wait(self, timeout: float | None = None) -> dict | None:
        if self._thread:
            self._thread.join(timeout=timeout or self._timeout + 5)
        return self.result

    def shutdown(self) -> None:
        if self._server:
            self._server.server_close()


def start_oauth_flow(client_id: str, redirect_port: int = DEFAULT_REDIRECT_PORT) -> tuple:
    """Start the full OAuth flow: launch callback server, open browser.

    Returns (server, state) — caller should server.wait() then
    call UserTokenManager.complete_auth() with the code.
    """
    state = secrets.token_urlsafe(32)
    server = OAuthCallbackServer(port=redirect_port)
    server.start()

    url = UserTokenManager.build_authorize_url(client_id, state, redirect_port)
    webbrowser.open(url)

    return server, state
