"""
Application context shared by every frontend.

The CLI, the desktop app and the web API all need the same things before they
can do any work: loaded config, analysis thresholds, an authenticated WCL
client and a database handle. ``AppContext`` builds those once so no frontend
wires ``TokenManager`` / ``WarcraftLogsClient`` / ``PerformanceDB`` itself.
"""

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from wcl_core.client import WarcraftLogsClient
from wcl_core.common.errors import ConfigurationError

from ..database import PerformanceDB

ProgressCallback = Callable[[str], None]

_REPORT_CODE_RE = re.compile(r"^[A-Za-z0-9]{16}$")


def validate_report_code(code: str) -> str:
    """Return the stripped report code, or raise ValueError if it is not a WCL report code."""
    code = (code or "").strip()
    if not _REPORT_CODE_RE.match(code):
        raise ValueError(f"Invalid report code: {code!r}")
    return code


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

    def as_kwargs(self) -> dict[str, int]:
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

    @classmethod
    def from_config_file(cls, config_file: str | None = None, db_path: str | None = None) -> "AppContext":
        from wcl_core.config import load_config

        return cls(config=load_config(config_file), db_path=db_path)

    @property
    def thresholds(self) -> AnalysisThresholds:
        return AnalysisThresholds.from_config(self.config)

    @property
    def wcl_client(self) -> WarcraftLogsClient:
        """Client-credentials WCL client, created on first use."""
        if self._client is None:
            from wcl_core.auth import TokenManager

            try:
                token_mgr = TokenManager(self.config["client_id"], self.config["client_secret"])
            except KeyError as e:
                raise ConfigurationError(f"Missing config value: {e.args[0]}") from e
            self._client = WarcraftLogsClient(token_mgr, api_url=self.config.get("wcl_api_url"))
        return self._client

    def user_client(self) -> WarcraftLogsClient | None:
        """User-scoped WCL client for reference reports, or None if the user has not signed in."""
        from ..user_auth import UserTokenManager, _get_base_url

        user_tm = UserTokenManager()
        if not user_tm.is_authenticated():
            return None
        return WarcraftLogsClient(user_tm, cache_enabled=False, api_url=f"{_get_base_url()}/api/v2/user")

    @contextmanager
    def db(self) -> Iterator[PerformanceDB]:
        """Open the performance database for the duration of a ``with`` block."""
        with PerformanceDB(self.db_path) as db:
            yield db
