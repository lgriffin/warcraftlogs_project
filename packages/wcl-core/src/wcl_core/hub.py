"""The Toads Hub link: a desktop or CLI analyzer redeems a one-time code from the Toads bot and becomes "Leigh's app".

The member asks the bot for a code in Discord (the bot knows who they are); the app sends the code to the Hub, which
answers with an app id, an app token and the member it belongs to. The app keeps that in ``hub_link.json`` and uses
the token to publish its raid profiles, so the bot can resolve a Discord user to their profile. The wire contract is
``guides/hub_bridge.md``; ``wcl_core.testing.FakeHub`` serves it in tests and ``TOADS_HUB_URL`` points at any Hub.

Every request goes through ``wcl_core.http``. The token is a ``SecretStr`` and never logged; the Hub URL must be
``https`` unless it is this machine, so the token never crosses the network in clear.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from pydantic import SecretStr

from . import http, paths
from .common.errors import AuthenticationError, ConfigurationError, WarcraftLogsError

logger = logging.getLogger(__name__)

__all__ = [
    "HubError",
    "HubLink",
    "HubLinkStore",
    "HubMember",
    "hub_url",
    "link_code",
    "publish_profiles",
    "redeem",
    "revoke",
]

# A code as the bot shows it: eight letters and digits, in two groups of four. Typed with or without the hyphen,
# spaces or lower case; I, L, O and U are never issued (Crockford base 32), so nothing reads as 1 or 0.
_CODE = re.compile(r"[0-9A-HJKMNP-TV-Z]{8}")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TIMEOUT = 30
_OWNER_ONLY = 0o600  # hub_link.json holds a bearer token


class HubError(WarcraftLogsError):
    """The Hub could not be reached or answered with something other than the contract."""


def link_code(text: str) -> str:
    """The code in its canonical ``XXXX-XXXX`` form, or ValueError when *text* is not one."""
    compact = re.sub(r"[\s-]", "", text or "").upper()
    if not _CODE.fullmatch(compact):
        raise ValueError("A link code is eight letters and digits, like 7KQ2-M9XD; ask the Toads bot for one")
    return f"{compact[:4]}-{compact[4:]}"


def hub_url(config: dict[str, Any] | None = None) -> str:
    """The Hub: ``TOADS_HUB_URL``, else ``toads_hub_url`` in config. ``https`` only, except on this machine."""
    value = os.environ.get("TOADS_HUB_URL") or (config or {}).get("toads_hub_url")
    if not value:
        raise ConfigurationError("Set toads_hub_url in config.json or TOADS_HUB_URL to link with the Toads Hub")
    url = str(value).rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS):
        return url
    raise ConfigurationError(f"The Toads Hub URL must be https (or http on this machine), not {url!r}")


@dataclass(frozen=True)
class HubMember:
    """The Discord user the Hub says the code belongs to."""

    discord_id: str
    username: str
    display_name: str | None = None

    @property
    def name(self) -> str:
        return self.display_name or self.username


@dataclass(frozen=True)
class HubLink:
    """This app's registration with a Hub."""

    hub_url: str
    app_id: str
    token: SecretStr
    member: HubMember

    @classmethod
    def from_reply(cls, hub: str, data: Any) -> HubLink:
        try:
            member = data["member"]
            return cls(
                hub_url=hub,
                app_id=str(data["app_id"]),
                token=SecretStr(str(data["token"])),
                member=HubMember(
                    discord_id=str(member["discord_id"]),
                    username=str(member["username"]),
                    display_name=member.get("display_name") or None,
                ),
            )
        except (KeyError, TypeError, AttributeError) as e:
            raise HubError("The Toads Hub sent an unreadable link", details=str(e)) from e

    def to_dict(self) -> dict[str, Any]:
        return {
            "hub_url": self.hub_url,
            "app_id": self.app_id,
            "token": self.token.get_secret_value(),
            "member": {
                "discord_id": self.member.discord_id,
                "username": self.member.username,
                "display_name": self.member.display_name,
            },
        }


class HubLinkStore:
    """The link in ``hub_link.json`` next to the Discord identity; no link means no file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else paths.get_hub_link_path()
        self.link: HubLink | None = None
        with contextlib.suppress(OSError, ValueError, HubError):  # a missing or damaged file is no link
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("hub_url"), str):
                self.link = HubLink.from_reply(data["hub_url"], data)

    @property
    def path(self) -> Path:
        return self._path

    def save(self, link: HubLink) -> None:
        """Write the link owner-only: the token lets anyone who reads it publish as this member."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _OWNER_ONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if hasattr(os, "fchmod"):  # also a file an earlier version left readable; Windows keeps its own ACLs
                os.fchmod(f.fileno(), _OWNER_ONLY)
            f.write(json.dumps(link.to_dict(), indent=2))
        self.link = link

    def forget(self) -> None:
        """Delete the link file. If it cannot be deleted the OSError propagates and the link stays, so a restart
        never finds a link the user was told is gone."""
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()
        self.link = None


def _post(url: str, what: str, **kwargs: Any) -> http.Response:
    logger.info("Toads Hub: POST %s", url)  # never the code, the token or a reply body
    try:
        return http.post(url, timeout=TIMEOUT, **kwargs)
    except requests.ConnectionError as e:
        raise HubError(f"Cannot reach the Toads Hub to {what}") from e
    except requests.Timeout as e:
        raise HubError(f"The Toads Hub timed out while trying to {what}") from e


def _bearer(link: HubLink) -> dict[str, str]:
    return {"Authorization": f"Bearer {link.token.get_secret_value()}"}


def redeem(hub: str, code: str, app_name: str, app_version: str) -> HubLink:
    """``POST /api/apps/link``: trade a one-time code for this app's registration."""
    response = _post(
        f"{hub}/api/apps/link",
        "link this app",
        json={"code": link_code(code), "app": {"name": app_name, "version": app_version}},
    )
    if response.status_code in (400, 404, 410):
        raise AuthenticationError("The Toads Hub did not accept that code; it may have expired. Ask the bot again")
    if response.status_code not in (200, 201):
        raise HubError(f"The Toads Hub refused the link (HTTP {response.status_code})")
    try:
        body = response.json()
    except ValueError as e:
        raise HubError("The Toads Hub sent an unreadable link", details=str(e)) from e
    return HubLink.from_reply(hub, body)


def publish_profiles(link: HubLink, profiles: dict[str, Any]) -> None:
    """``POST /api/apps/profiles``: replace the member's profiles on the Hub with this app's ``ProfileSet``."""
    response = _post(f"{link.hub_url}/api/apps/profiles", "publish profiles", json=profiles, headers=_bearer(link))
    if response.status_code == 401:
        raise AuthenticationError("The Toads Hub no longer knows this app; link it again with a new code")
    if response.status_code not in (200, 204):
        raise HubError(f"The Toads Hub refused the profiles (HTTP {response.status_code})")


def revoke(link: HubLink) -> None:
    """``POST /api/apps/unlink``: ask the Hub to forget this app. An app it already forgot is fine."""
    response = _post(f"{link.hub_url}/api/apps/unlink", "unlink this app", headers=_bearer(link))
    if response.status_code not in (200, 204, 401):
        raise HubError(f"The Toads Hub refused the unlink (HTTP {response.status_code})")
