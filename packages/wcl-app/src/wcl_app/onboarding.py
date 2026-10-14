"""First-run setup: the Warcraft Logs API keys, then the guild whose raids the app imports.

A new user has two things to find on Warcraft Logs before the app can do anything: an API client (its id and
secret) and their guild's id. ``OnboardingService`` checks the keys against Warcraft Logs before they are saved, and
finds the guild from whatever the user has to hand: a link to the guild's page, a link to one of its reports, or its
name, server and region. Nothing is written until ``save``. Once setup is done, the welcome tour is offered once
(``tour_due``, ``mark_tour_seen``).

The desktop keeps the answers in config.json (``JsonConfigStore``); ``MemoryConfigStore`` is for tests and hosts
without a config file.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

import requests
from pydantic import SecretStr
from wcl_core.auth import TokenManager
from wcl_core.client import DEFAULT_API_URL, WarcraftLogsClient
from wcl_core.common.errors import AuthenticationError, WarcraftLogsError
from wcl_core.config import AppConfig, as_secret, configured_api_url
from wcl_core.game_version import GAME_VERSIONS, api_url_for, game_version_for_url, host_for
from wcl_core.user_auth import DEFAULT_REDIRECT_PORT

from wcl_app.player_page import server_slug

__all__ = [
    "KEYS_URL",
    "REDIRECT_URL",
    "REGIONS",
    "TOUR_SEEN_KEY",
    "GuildMatch",
    "JsonConfigStore",
    "MemoryConfigStore",
    "OnboardingService",
    "SetupError",
    "is_placeholder",
]

# Where a Warcraft Logs account creates and lists its API clients.
KEYS_URL = "https://www.warcraftlogs.com/api/clients/"
# The redirect URL the client needs for the app's "Authenticate" sign-in (``wcl_core.user_auth``).
REDIRECT_URL = f"http://localhost:{DEFAULT_REDIRECT_PORT}/callback"
REGIONS: tuple[str, ...] = ("eu", "us", "kr", "tw", "cn")
# Set in config once the welcome tour has been offered, taken or skipped, so it is offered only once.
TOUR_SEEN_KEY = "welcome_tour_seen"

# config.example.json ships "YOUR_CLIENT_ID_HERE" and friends; a first run copies it into place.
_PLACEHOLDER_PREFIX = "YOUR_"
_GUILD_ID_URL_RE = re.compile(r"/guild/(?:[a-z-]+/)?(\d+)(?:[/?#]|$)")
_GUILD_NAME_URL_RE = re.compile(rf"/guild/({'|'.join(REGIONS)})/([^/?#]+)/([^/?#]+)")
_REPORT_URL_RE = re.compile(r"/reports/([A-Za-z0-9]{16})(?:[/?#]|$)")
_REPORT_CODE_RE = re.compile(r"^(?=.*\d)[A-Za-z0-9]{16}$")  # guild names have no digits; report codes do
# The site imports use when config names none (``wcl_core.config`` fills it in on load).
_DEFAULT_SITE_API_URL = AppConfig.wcl_api_url
_API_ERRORS = (WarcraftLogsError, requests.RequestException, KeyError, TypeError, ValueError)


class SetupError(Exception):
    """A step of setup that cannot go on, with a message to show the user as it is."""


def is_placeholder(value: Any) -> bool:
    """True for a missing or blank setting, or the template's ``YOUR_..._HERE`` stand-in."""
    text = value.get_secret_value() if isinstance(value, SecretStr) else str(value or "")
    return not text.strip() or text.strip().upper().startswith(_PLACEHOLDER_PREFIX)


@dataclass(frozen=True)
class GuildMatch:
    """A guild found on Warcraft Logs, and the site (game version) it was found on."""

    id: int
    name: str
    server: str
    region: str
    game_version: str

    @property
    def label(self) -> str:
        """How the guild reads in the app: ``Amicable on Gehennas (EU)``."""
        where = f" on {self.server}" if self.server else ""
        return f"{self.name}{where} ({self.region.upper()})" if self.region else f"{self.name}{where}"

    @property
    def url(self) -> str:
        """The guild's page on its Warcraft Logs site."""
        return f"{host_for(self.game_version) or 'https://www.warcraftlogs.com'}/guild/id/{self.id}"


class ConfigStore(Protocol):
    def read(self) -> dict[str, Any]: ...

    def update(self, values: dict[str, Any]) -> None: ...


class MemoryConfigStore:
    """Settings in memory, for tests and hosts without a config file."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = dict(config or {})

    def read(self) -> dict[str, Any]:
        return dict(self.config)

    def update(self, values: dict[str, Any]) -> None:
        self.config.update(values)


class JsonConfigStore:
    """config.json: ``update`` keeps every setting it is not given, and the config manager re-reads the file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise SetupError(f"Could not read {self.path.name}: {e}") from e
        return data if isinstance(data, dict) else {}

    def update(self, values: dict[str, Any]) -> None:
        from wcl_core.config import get_config_manager

        config = {**self.read(), **values}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_suffix(".json.partial")
        try:
            partial.write_text(json.dumps(config, indent=4), encoding="utf-8")
            partial.replace(self.path)
        except OSError as e:
            raise SetupError(f"Could not save {self.path.name}: {e}") from e
        get_config_manager(str(self.path))  # the next load_config reads what was just written


@dataclass(frozen=True)
class _GuildQuery:
    guild_id: int | None = None
    report_code: str | None = None
    name: str = ""
    server_slug: str = ""
    region: str = ""
    game_version: str | None = None  # the site a pasted link points at


def _parse_guild_query(text: str, server: str, region: str) -> _GuildQuery:
    """What the user typed: a guild or report link, a report code, a guild id, or a guild name."""
    text = (text or "").strip()
    if not text:
        raise SetupError("Paste a link to your guild's Warcraft Logs page, or type its name.")
    url = text if "://" in text else f"https://{text}"
    host = (urlparse(url).hostname or "").lower()
    if host == "warcraftlogs.com" or host.endswith(".warcraftlogs.com"):
        version = game_version_for_url(url)
        path = urlparse(url).path
        if match := _GUILD_ID_URL_RE.search(path):
            return _GuildQuery(guild_id=int(match.group(1)), game_version=version)
        if match := _GUILD_NAME_URL_RE.search(path):
            region_part, server_part, name_part = match.groups()
            return _GuildQuery(
                name=unquote(name_part).replace("+", " "),
                server_slug=server_part.lower(),
                region=region_part,
                game_version=version,
            )
        if match := _REPORT_URL_RE.search(path):
            return _GuildQuery(report_code=match.group(1), game_version=version)
        raise SetupError("That link is not a Warcraft Logs guild or report page.")
    if "/" in text:
        raise SetupError("That is not a Warcraft Logs link. Paste your guild's page from warcraftlogs.com.")
    if text.isdigit():
        return _GuildQuery(guild_id=int(text))
    if _REPORT_CODE_RE.match(text):
        return _GuildQuery(report_code=text)
    region = (region or "").strip().lower()
    if not server.strip() or region not in REGIONS:
        raise SetupError("To search by name, give the guild's server and region too.")
    return _GuildQuery(name=text, server_slug=server_slug(server), region=region)


class OnboardingService:
    """Checks API keys, finds the user's guild and saves both."""

    def __init__(self, store: ConfigStore) -> None:
        self.store = store

    @classmethod
    def desktop(cls) -> OnboardingService:
        from wcl_core.paths import get_config_path

        return cls(JsonConfigStore(get_config_path()))

    def needs_setup(self) -> bool:
        """True until there are API keys, in config or the ``WARCRAFTLOGS_CLIENT_*`` environment variables."""
        config = self._config()
        client_id = os.environ.get("WARCRAFTLOGS_CLIENT_ID") or config.get("client_id")
        secret = os.environ.get("WARCRAFTLOGS_CLIENT_SECRET") or config.get("client_secret")
        return is_placeholder(client_id) or is_placeholder(secret)

    def tour_due(self) -> bool:
        """True until the welcome tour has been offered once."""
        return self._config().get(TOUR_SEEN_KEY) is not True

    def mark_tour_seen(self) -> None:
        """Remember the welcome tour was offered, so it is not offered again (Settings can still start it)."""
        self.store.update({TOUR_SEEN_KEY: True})

    def saved_keys(self) -> tuple[str, str]:
        """The client id and secret config holds, blank for the template's stand-ins."""
        config = self._config()
        values = (config.get("client_id"), config.get("client_secret"))
        return tuple("" if is_placeholder(v) else str(v).strip() for v in values)  # type: ignore[return-value]

    def site(self) -> str:
        """The game version (Warcraft Logs site) config imports from; a name search looks there."""
        return game_version_for_url(configured_api_url(self._config()) or _DEFAULT_SITE_API_URL)

    def check_keys(self, client_id: str, client_secret: str | SecretStr) -> None:
        """Ask Warcraft Logs for a token with these keys; raises ``SetupError`` saying why it refused."""
        client_id, secret = self._keys(client_id, client_secret)
        try:
            TokenManager(client_id, secret).get_token()
        except AuthenticationError as e:
            if "HTTP 401" in str(e) or "HTTP 400" in str(e):
                raise SetupError(
                    "Warcraft Logs did not accept those keys. Copy the Client ID and Client Secret again from "
                    "your client's page; a secret is only shown when the client is created or reset."
                ) from e
            raise SetupError(str(e)) from e

    def find_guild(
        self,
        text: str,
        client_id: str,
        client_secret: str | SecretStr,
        *,
        server: str = "",
        region: str = "",
        game_version: str | None = None,
    ) -> GuildMatch:
        """The guild *text* names: a link to its page or one of its reports, a report code, its id, or its name
        (with *server* and *region*). A link decides the site; otherwise *game_version*, else config's site."""
        query = _parse_guild_query(text, server, region)
        version = query.game_version or game_version or self.site()
        if version not in GAME_VERSIONS:
            raise SetupError(f"Unknown Warcraft Logs site '{version}'.")
        api_url = api_url_for(version) or configured_api_url(self._config()) or DEFAULT_API_URL
        client = WarcraftLogsClient(
            TokenManager(*self._keys(client_id, client_secret)), cache_enabled=False, api_url=api_url
        )
        try:
            if query.report_code is not None:
                found = self._report_guild(client, query.report_code, version)
                if found is None:
                    raise SetupError("That report is a personal log, not a guild's. Try one your guild uploaded.")
            elif query.guild_id is not None:
                found = client.find_guild(query.guild_id)
            else:
                found = client.find_guild(name=query.name, server_slug=query.server_slug, region=query.region)
        except SetupError:
            raise
        except AuthenticationError as e:
            raise SetupError(f"Check your API keys first: {e}") from e
        except _API_ERRORS as e:
            raise SetupError(f"Could not reach Warcraft Logs: {e}") from e
        if found is None:
            raise SetupError("Warcraft Logs has no such guild. Check the spelling, server and region.")
        return GuildMatch(
            id=found["id"], name=found["name"], server=found["server"], region=found["region"], game_version=version
        )

    def save(self, client_id: str, client_secret: str | SecretStr, guild: GuildMatch | None = None) -> None:
        """Keep the keys and, when given, the guild: its id, name and server, and its site when config's differs."""
        client_id, secret = self._keys(client_id, client_secret)
        values: dict[str, Any] = {"client_id": client_id, "client_secret": secret.get_secret_value()}
        config = self._config()
        if guild is not None:
            values.update(self.guild_settings(guild))
        elif "guild_id" not in config:
            values.update(guild_id=0)  # no guild yet; without the key the loader's built-in default would apply
        if is_placeholder(config.get("report_id")) and config.get("report_id"):
            values["report_id"] = ""  # the template's stand-in is not a report
        self.store.update(values)

    def guild_settings(self, guild: GuildMatch) -> dict[str, Any]:
        """The config values that make *guild* the one imports come from: its id, name and server, and its site's
        API URL when config's site is another one."""
        values: dict[str, Any] = {"guild_id": guild.id, "guild_name": guild.name, "guild_server": guild.server}
        api_url = api_url_for(guild.game_version)
        if api_url and guild.game_version != self.site():
            values.update(wcl_api_url=api_url)  # a write, not a read of the default
        return values

    @staticmethod
    def _report_guild(client: WarcraftLogsClient, code: str, version: str) -> dict | None:
        try:
            return client.get_report_guild(code)
        except ValueError as e:  # the report is not on this site, or the code is mistyped
            raise SetupError(
                f"Warcraft Logs has no report {code} on the {version} site. Check the code, or paste the report's "
                "link so its site comes with it."
            ) from e

    def _config(self) -> dict[str, Any]:
        return self.store.read()

    def _keys(self, client_id: str, client_secret: str | SecretStr) -> tuple[str, SecretStr]:
        client_id = (client_id or "").strip()
        secret = as_secret(client_secret)
        secret = as_secret(secret.get_secret_value().strip())
        if is_placeholder(client_id) or is_placeholder(secret):
            raise SetupError("Enter both the Client ID and the Client Secret.")
        return client_id, secret
