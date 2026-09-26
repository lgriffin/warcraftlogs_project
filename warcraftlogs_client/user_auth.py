"""
OAuth2 Authorization Code flow for WarcraftLogs user-level API access.

The Client Credentials flow (/api/v2/client) only exposes public data.
To access detailed event/table data for reports the user doesn't own,
we need a user-scoped token via the Authorization Code flow (/api/v2/user).
"""

import json
import logging
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from pydantic import SecretStr
from wcl_core import paths
from wcl_core.common.errors import AuthenticationError
from wcl_core.config import as_secret

logger = logging.getLogger(__name__)

DEFAULT_REDIRECT_PORT = 8764


def _get_base_url() -> str:
    """Derive the WCL domain from the configured API URL."""
    from wcl_core.config import load_config

    try:
        api_url = load_config().get("wcl_api_url", "")
        parsed = urlparse(api_url)
        if parsed.hostname:
            return f"{parsed.scheme}://{parsed.hostname}"
    except Exception:
        pass
    return "https://www.warcraftlogs.com"


def get_authorize_url() -> str:
    return f"{_get_base_url()}/oauth/authorize"


def get_token_url() -> str:
    return f"{_get_base_url()}/oauth/token"


class UserTokenManager:
    """Manages OAuth2 user tokens with persistence and refresh."""

    def __init__(self, token_path: str | None = None):
        self._token_path = token_path or str(paths.get_user_token_path())
        self._access_token: SecretStr | None = None
        self._refresh_token: SecretStr | None = None
        self._expires_at: float = 0
        self._load()

    def _load(self):
        try:
            with open(self._token_path) as f:
                data = json.load(f)
            self._access_token = _optional_secret(data.get("access_token"))
            self._refresh_token = _optional_secret(data.get("refresh_token"))
            self._expires_at = data.get("expires_at", 0)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def _save(self):
        data = {
            "access_token": _reveal(self._access_token),
            "refresh_token": _reveal(self._refresh_token),
            "expires_at": self._expires_at,
        }
        with open(self._token_path, "w") as f:
            json.dump(data, f, indent=2)

    def is_authenticated(self) -> bool:
        return bool(self._access_token or self._refresh_token)

    def get_token(self) -> str:
        if self._access_token and time.time() < self._expires_at:
            return self._access_token.get_secret_value()
        if self._refresh_token:
            self._refresh()
            if self._access_token:
                return self._access_token.get_secret_value()
        raise RuntimeError("Not authenticated — user must complete OAuth flow first")

    def _refresh(self):
        from wcl_core.config import load_config

        config = load_config()
        client_id = config["client_id"]
        client_secret = as_secret(config["client_secret"])

        token_url = get_token_url()
        try:
            response = requests.post(
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
        self._expires_at = time.time() + token_data.get("expires_in", 3600) - 60
        self._save()

    def complete_auth(
        self,
        code: str,
        client_id: str,
        client_secret: str | SecretStr,
        redirect_port: int = DEFAULT_REDIRECT_PORT,
    ):
        client_secret = as_secret(client_secret)
        redirect_uri = f"http://localhost:{redirect_port}/callback"
        token_url = get_token_url()
        # Never log the client secret, the authorization code, or anything from the token response.
        logger.info("Token exchange: POST %s (redirect_uri=%s)", token_url, redirect_uri)

        try:
            response = requests.post(
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
        self._expires_at = time.time() + token_data.get("expires_in", 3600) - 60
        self._save()
        logger.info("Token exchange successful, token saved.")

    def revoke(self):
        self._access_token = None
        self._refresh_token = None
        self._expires_at = 0
        try:
            import os

            os.remove(self._token_path)
        except OSError:
            pass

    @staticmethod
    def build_authorize_url(client_id: str, state: str, redirect_port: int = DEFAULT_REDIRECT_PORT) -> str:
        params = {
            "client_id": client_id,
            "redirect_uri": f"http://localhost:{redirect_port}/callback",
            "response_type": "code",
            "state": state,
        }
        return f"{get_authorize_url()}?{urlencode(params)}"


def _optional_secret(value: str | None) -> SecretStr | None:
    return SecretStr(value) if value else None


def _reveal(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth redirect callback."""

    def do_GET(self):
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

    def log_message(self, *args):
        pass


class OAuthCallbackServer:
    """Local HTTP server that waits for the OAuth callback."""

    def __init__(self, port: int = DEFAULT_REDIRECT_PORT, timeout: int = 120):
        self._port = port
        self._timeout = timeout
        self._server: HTTPServer | None = None
        self._thread: Thread | None = None
        self.result: dict | None = None

    def start(self):
        self._server = HTTPServer(("127.0.0.1", self._port), _CallbackHandler)
        self._server.timeout = self._timeout
        self._server.auth_result = None

        def serve():
            self._server.handle_request()
            self.result = self._server.auth_result

        self._thread = Thread(target=serve, daemon=True)
        self._thread.start()

    def wait(self, timeout: float | None = None) -> dict | None:
        if self._thread:
            self._thread.join(timeout=timeout or self._timeout + 5)
        return self.result

    def shutdown(self):
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
