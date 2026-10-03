"""Discord sign-in for a desktop or CLI instance of the analyzer: who does this app belong to?

Authorization Code with PKCE for a *public* Discord application (no client secret on the user's machine), a
loopback redirect served by ``user_auth.OAuthCallbackServer``, and the ``identify`` scope only. The result is a
``DiscordIdentity`` (id, username, display name, avatar) kept next to the Warcraft Logs user token.

Identity says who, never what they may do: permission checks stay in each frontend (``guides/identity_and_profiles.md``).
The Toads Hub does the same dance server-side with its own sessions; ``DISCORD_OAUTH_URL`` points this flow at its
fake Discord (``FAKE_DISCORD_I_AM_DEV=1``) so both share one development login.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import secrets
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from pydantic import SecretStr

from . import http, paths
from .common.errors import AuthenticationError
from .user_auth import OAuthCallbackServer, _optional_secret, _reveal

logger = logging.getLogger(__name__)

DEFAULT_OAUTH_URL = "https://discord.com"
DEFAULT_REDIRECT_PORT = 8765
SCOPES = "identify"


def oauth_base_url() -> str:
    """Discord, or the fake Discord ``DISCORD_OAUTH_URL`` names for development."""
    return os.environ.get("DISCORD_OAUTH_URL", DEFAULT_OAUTH_URL).rstrip("/")


def discord_client_id(config: dict[str, Any] | None = None) -> str | None:
    """The Discord application id: ``DISCORD_CLIENT_ID``, else ``discord_client_id`` in config."""
    value = os.environ.get("DISCORD_CLIENT_ID") or (config or {}).get("discord_client_id")
    return str(value) if value else None


@dataclass(frozen=True)
class DiscordIdentity:
    """A Discord user, as ``/users/@me`` describes them."""

    id: str
    username: str
    global_name: str | None = None
    avatar: str | None = None

    @property
    def display_name(self) -> str:
        return self.global_name or self.username

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> DiscordIdentity:
        try:
            return cls(
                id=str(data["id"]),
                username=str(data["username"]),
                global_name=data.get("global_name") or None,
                avatar=data.get("avatar") or None,
            )
        except (KeyError, TypeError) as e:
            raise AuthenticationError("Discord sent an unreadable user", details=str(e)) from e


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str

    @classmethod
    def generate(cls) -> PkcePair:
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return cls(verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"))


def build_authorize_url(client_id: str, state: str, challenge: str, redirect_port: int = DEFAULT_REDIRECT_PORT) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": f"http://127.0.0.1:{redirect_port}/callback",
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "none",
    }
    return f"{oauth_base_url()}/oauth2/authorize?{urlencode(params)}"


class DiscordIdentityStore:
    """The linked identity and its tokens in ``discord_identity.json``; nothing linked means no file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else paths.get_discord_identity_path()
        self.identity: DiscordIdentity | None = None
        self._access_token: SecretStr | None = None
        self._refresh_token: SecretStr | None = None
        self._expires_at: float = 0
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            user = data.get("user") or {}
            self.identity = DiscordIdentity.from_api(user) if user else None
            self._access_token = _optional_secret(data.get("access_token"))
            self._refresh_token = _optional_secret(data.get("refresh_token"))
            self._expires_at = float(data.get("expires_at", 0) or 0)
        except (OSError, ValueError, AuthenticationError):
            self.identity = None

    def save(self) -> None:
        data = {
            "user": asdict(self.identity) if self.identity else None,
            "access_token": _reveal(self._access_token),
            "refresh_token": _reveal(self._refresh_token),
            "expires_at": self._expires_at,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def is_linked(self) -> bool:
        return self.identity is not None

    def unlink(self) -> None:
        self.identity = None
        self._access_token = None
        self._refresh_token = None
        self._expires_at = 0
        with contextlib.suppress(OSError):
            self._path.unlink()

    def complete_auth(
        self, code: str, client_id: str, verifier: str, redirect_port: int = DEFAULT_REDIRECT_PORT
    ) -> DiscordIdentity:
        """Exchange the authorization code, read ``/users/@me`` and keep the result."""
        token_url = f"{oauth_base_url()}/api/oauth2/token"
        # Never log the code or anything from the token response.
        logger.info("Discord token exchange: POST %s", token_url)
        try:
            response = http.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"http://127.0.0.1:{redirect_port}/callback",
                    "client_id": client_id,
                    "code_verifier": verifier,
                },
                timeout=30,
            )
        except requests.ConnectionError as e:
            raise AuthenticationError("Cannot reach Discord — check your internet connection") from e
        except requests.Timeout as e:
            raise AuthenticationError("Discord sign-in timed out — try again later") from e
        if response.status_code != 200:
            raise AuthenticationError(f"Discord token exchange failed (HTTP {response.status_code})")
        try:
            token_data = response.json()
            access = SecretStr(token_data["access_token"])
        except (ValueError, KeyError, TypeError) as e:
            raise AuthenticationError("Received invalid response from Discord", details=str(e)) from e

        self._access_token = access
        self._refresh_token = _optional_secret(token_data.get("refresh_token"))
        self._expires_at = time.time() + float(token_data.get("expires_in", 604800)) - 60
        self.identity = fetch_identity(access)
        self.save()
        return self.identity


def fetch_identity(access_token: SecretStr) -> DiscordIdentity:
    """``GET /users/@me`` with a user token."""
    try:
        response = http.get(
            f"{oauth_base_url()}/api/users/@me",
            headers={"Authorization": f"Bearer {access_token.get_secret_value()}"},
            timeout=30,
        )
    except requests.RequestException as e:
        raise AuthenticationError("Cannot reach Discord to read who signed in") from e
    if response.status_code != 200:
        raise AuthenticationError(f"Discord refused the identity request (HTTP {response.status_code})")
    try:
        return DiscordIdentity.from_api(response.json())
    except ValueError as e:
        raise AuthenticationError("Discord sent an unreadable user", details=str(e)) from e


def start_oauth_flow(client_id: str, redirect_port: int = DEFAULT_REDIRECT_PORT, open_browser: bool = True) -> tuple:
    """Start the callback server and open the browser.

    Returns ``(server, state, pkce)``; the caller waits on the server, checks ``state`` and calls
    ``DiscordIdentityStore.complete_auth(code, client_id, pkce.verifier)``.
    """
    state = secrets.token_urlsafe(32)
    pkce = PkcePair.generate()
    server = OAuthCallbackServer(port=redirect_port)
    server.start()
    url = build_authorize_url(client_id, state, pkce.challenge, redirect_port)
    if open_browser:
        webbrowser.open(url)
    return server, state, pkce
