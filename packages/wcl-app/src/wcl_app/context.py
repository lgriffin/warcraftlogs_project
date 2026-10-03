"""
Application context shared by every frontend.

The CLI, the desktop app and the web API all need the same things before they
can do any work: loaded config, analysis thresholds, an authenticated WCL
client and a database handle. ``AppContext`` builds those once so no frontend
wires ``TokenManager`` / ``WarcraftLogsClient`` / ``PerformanceDB`` itself.

Services open storage through ``repository()``, typed as the ``wcl_store.RaidRepository`` protocol. It is the
desktop SQLite database unless the host passes ``storage`` (the Toads Hub worker passes a Postgres one).
A headless host builds the context with ``AppContext.headless(client, storage)``: no config file, no SQLite.

The active raid profile (``wcl_app.profiles``) sits on the context too: ``scope`` is what services pass to
repository reads, and ``wcl_client`` follows the profile's Warcraft Logs host when it names one.
"""

import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeAlias, TypedDict

from wcl_core.client import DEFAULT_API_URL, WarcraftLogsClient
from wcl_core.common.errors import ConfigurationError
from wcl_core.config import configured_api_url, configured_guild_id
from wcl_core.game_version import api_url_for
from wcl_store import RaidRepository, RaidScope

# A fixed scope, or a callable a service asks at read time (``lambda: ctx.scope``) so a profile switch on the
# context reaches services built before it.
ScopeSource: TypeAlias = "RaidScope | Callable[[], RaidScope | None] | None"


def resolve_scope(source: ScopeSource) -> RaidScope | None:
    """The scope ``source`` stands for right now."""
    return source() if callable(source) else source


if TYPE_CHECKING:
    from wcl_core.auth import TokenManager
    from wcl_store.sqlite import PerformanceDB

    from wcl_app.profiles import Profile

ProgressCallback = Callable[[str], None]
# Opens a repository for one ``with`` block, e.g. ``lambda: PostgresRaidRepository(engine)``.
StorageFactory = Callable[[], AbstractContextManager[RaidRepository]]

_REPORT_CODE_RE = re.compile(r"^[A-Za-z0-9]{16}$")


def validate_report_code(code: str) -> str:
    """Return the stripped report code, or raise ValueError if it is not a WCL report code."""
    code = (code or "").strip()
    if not _REPORT_CODE_RE.match(code):
        raise ValueError(f"Invalid report code: {code!r}")
    return code


class ThresholdKwargs(TypedDict):
    """The threshold keyword arguments of ``analyze_raid``."""

    healer_threshold: int
    tank_min_taken: int
    tank_min_mitigation: int
    healer_threshold_10: int
    tank_min_taken_10: int


@dataclass(frozen=True)
class AnalysisThresholds:
    """Role-detection thresholds passed to ``analyze_raid``."""

    healer_min_healing: int = 900000
    tank_min_taken: int = 150000
    tank_min_mitigation: int = 40
    healer_min_healing_10: int = 400000
    tank_min_taken_10: int = 300000

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "AnalysisThresholds":
        rt = config.get("role_thresholds") or {}
        defaults = cls()
        return cls(
            healer_min_healing=rt.get("healer_min_healing", defaults.healer_min_healing),
            tank_min_taken=rt.get("tank_min_taken", defaults.tank_min_taken),
            tank_min_mitigation=rt.get("tank_min_mitigation", defaults.tank_min_mitigation),
            healer_min_healing_10=rt.get("healer_min_healing_10", defaults.healer_min_healing_10),
            tank_min_taken_10=rt.get("tank_min_taken_10", defaults.tank_min_taken_10),
        )

    def as_kwargs(self) -> ThresholdKwargs:
        """Keyword arguments in the shape ``analyze_raid`` takes."""
        return {
            "healer_threshold": self.healer_min_healing,
            "tank_min_taken": self.tank_min_taken,
            "tank_min_mitigation": self.tank_min_mitigation,
            "healer_threshold_10": self.healer_min_healing_10,
            "tank_min_taken_10": self.tank_min_taken_10,
        }


@dataclass
class AppContext:
    """Config plus lazily created WCL client and database access."""

    config: dict[str, Any]
    db_path: str | None = None
    _client: WarcraftLogsClient | None = field(default=None, repr=False)
    storage: StorageFactory | None = field(default=None, repr=False)
    # Headless hosts: returns the user-scoped client for reference reports, or None. Unset means no reference
    # analysis; the desktop's signed-in token file is never read.
    _user_client: Callable[[], WarcraftLogsClient | None] | None = field(default=None, repr=False)
    _headless: bool = field(default=False, repr=False)
    # The active raid profile, or None for the plain, unfiltered app.
    profile: "Profile | None" = None

    @classmethod
    def from_config_file(cls, config_file: str | None = None, db_path: str | None = None) -> "AppContext":
        from wcl_core.config import load_config

        return cls(config=load_config(config_file), db_path=db_path)

    @classmethod
    def desktop(
        cls, config_file: str | None = None, db_path: str | None = None, *, with_config: bool = True
    ) -> "AppContext":
        """The desktop and CLI context: the config file (or none, for database-only work) with the saved active
        profile applied, so every scoped read starts in the profile the user last picked."""
        from wcl_app.profiles import saved_active_profile

        ctx = cls.from_config_file(config_file, db_path) if with_config else cls(config={}, db_path=db_path)
        profile = saved_active_profile()
        if profile is not None:
            ctx.use_profile(profile)
        return ctx

    @classmethod
    def headless(
        cls,
        client: WarcraftLogsClient,
        storage: StorageFactory,
        config: dict[str, Any] | None = None,
        user_client: Callable[[], WarcraftLogsClient | None] | None = None,
        profile: "Profile | None" = None,
    ) -> "AppContext":
        """Context for a host with its own WCL client and storage, such as the Toads Hub worker.

        Reads no config file and never opens the SQLite database. ``config`` only supplies optional
        settings such as ``role_thresholds``. ``user_client`` supplies the user-scoped client for reference
        reports; without it reference analysis raises ``ReferenceAuthRequired``. ``profile`` scopes reads to
        the member's active profile; the host's client is used as it is, whatever host the profile names.
        """
        return cls(
            config=dict(config or {}),
            _client=client,
            storage=storage,
            _user_client=user_client,
            _headless=True,
            profile=profile,
        )

    @property
    def scope(self) -> RaidScope | None:
        """The active profile's raid scope, or None for everything (today's behaviour)."""
        return self.profile.scope if self.profile is not None else None

    def use_profile(self, profile: "Profile | None") -> None:
        """Switch the active profile. On the desktop the client is rebuilt when the profile's host differs."""
        self.profile = profile
        wanted = (self.api_url or DEFAULT_API_URL).rstrip("/")
        if self._client is not None and not self._headless and self._client.api_url != wanted:
            self._client = None

    @property
    def guild_id(self) -> int | None:
        """The guild imports come from: the profile's, else the configured one."""
        if self.profile is not None and self.profile.guild_id is not None:
            return self.profile.guild_id
        return configured_guild_id(self.config)

    @property
    def api_url(self) -> str | None:
        """The client API URL imports use: the profile's host, else ``wcl_api_url`` from config."""
        if self.profile is not None and self.profile.api_url:
            return self.profile.api_url
        return configured_api_url(self.config)

    @property
    def thresholds(self) -> AnalysisThresholds:
        return AnalysisThresholds.from_config(self.config)

    @property
    def wcl_client(self) -> WarcraftLogsClient:
        """Client-credentials WCL client, created on first use."""
        if self._client is None:
            self._client = WarcraftLogsClient(self._token_manager(), api_url=self.api_url)
        return self._client

    def client_for(self, game_version: str | None) -> WarcraftLogsClient:
        """A client on the site a raid of *game_version* was fetched from, for reading more of that raid.

        The active profile's own host for its own game version (it may name a custom API URL); otherwise the
        version's site. A raid stored before eras were read, or of a version whose site is not announced yet, came
        from the configured site. The context's own client is reused when the site is the same, and a headless host
        always gets the client it brought.
        """
        if self._headless:
            return self.wcl_client
        url = self._source_url(game_version).rstrip("/")
        if url == (self.api_url or DEFAULT_API_URL).rstrip("/"):
            return self.wcl_client
        return WarcraftLogsClient(self._token_manager(), api_url=url)

    def _source_url(self, game_version: str | None) -> str:
        profile = self.profile
        if game_version and profile is not None and profile.game_version == game_version and profile.api_url:
            return profile.api_url
        known = api_url_for(game_version) if game_version else None
        return known or configured_api_url(self.config) or DEFAULT_API_URL

    def _token_manager(self) -> "TokenManager":
        from wcl_core.auth import TokenManager

        try:
            return TokenManager(self.config["client_id"], self.config["client_secret"])
        except KeyError as e:
            raise ConfigurationError(f"Missing config value: {e.args[0]}") from e

    def user_client(self) -> WarcraftLogsClient | None:
        """User-scoped WCL client for reference reports, or None if the user has not signed in."""
        if self._headless:
            return self._user_client() if self._user_client is not None else None
        from wcl_core.user_auth import UserTokenManager, _get_base_url

        user_tm = UserTokenManager()
        if not user_tm.is_authenticated():
            return None
        return WarcraftLogsClient(user_tm, cache_enabled=False, api_url=f"{_get_base_url()}/api/v2/user")

    @contextmanager
    def db(self) -> Iterator["PerformanceDB"]:
        """Open the desktop SQLite database for the duration of a ``with`` block.

        For frontends that still need queries outside ``RaidRepository``; services use ``repository()``.
        """
        from wcl_store.sqlite import PerformanceDB

        with PerformanceDB(self.db_path) as db:
            yield db

    @contextmanager
    def repository(self) -> Iterator[RaidRepository]:
        """Open the configured storage (``storage``, else the SQLite database) for a ``with`` block."""
        if self.storage is None:
            with self.db() as db:
                yield db
        else:
            with self.storage() as repo:
                yield repo
