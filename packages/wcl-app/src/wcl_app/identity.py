"""Whose app is this: the Discord identity linked to this instance of the analyzer.

``IdentityService`` wraps ``wcl_core.discord_auth``: read the linked identity, link one through the browser
sign-in, unlink it. It answers *who*, never *what they may do*; permission checks stay in each frontend, and a
headless host (the Toads Hub) passes the member it already signed in instead of using this at all.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wcl_core.common.errors import AuthenticationError
from wcl_core.discord_auth import (
    DEFAULT_REDIRECT_PORT,
    DiscordIdentity,
    DiscordIdentityStore,
    discord_client_id,
    start_oauth_flow,
)

# Starts the browser flow; returns (server, state, pkce). Swappable so tests and hosts can drive the callback.
FlowStarter = Callable[[str, int, bool], tuple]


class DiscordNotConfigured(Exception):
    """No Discord application id: set ``discord_client_id`` in config or ``DISCORD_CLIENT_ID``."""


class IdentityService:
    def __init__(
        self,
        store: DiscordIdentityStore | None = None,
        config: dict[str, Any] | None = None,
        *,
        flow: FlowStarter = start_oauth_flow,
        redirect_port: int = DEFAULT_REDIRECT_PORT,
    ):
        self.store = store if store is not None else DiscordIdentityStore()
        self.config = config or {}
        self._flow = flow
        self._redirect_port = redirect_port

    def current(self) -> DiscordIdentity | None:
        return self.store.identity

    def is_linked(self) -> bool:
        return self.store.is_linked()

    def client_id(self) -> str | None:
        return discord_client_id(self.config)

    def link(self, *, open_browser: bool = True, timeout: float | None = None) -> DiscordIdentity:
        """Sign in with Discord in the browser and keep who it was."""
        client_id = self.client_id()
        if not client_id:
            raise DiscordNotConfigured("Set discord_client_id in config.json or DISCORD_CLIENT_ID to sign in")
        server, state, pkce = self._flow(client_id, self._redirect_port, open_browser)
        try:
            result = server.wait(timeout)
        finally:
            server.shutdown()
        if not result:
            raise AuthenticationError("Discord sign-in timed out — the browser never came back")
        if result.get("error"):
            raise AuthenticationError(f"Discord sign-in failed: {result['error']}")
        if result.get("state") != state:
            raise AuthenticationError("Discord sign-in returned the wrong state; try again")
        return self.store.complete_auth(result["code"], client_id, pkce.verifier, self._redirect_port)

    def unlink(self) -> None:
        self.store.unlink()
