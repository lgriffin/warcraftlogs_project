"""
Background worker thread for API calls.

Keeps the UI responsive while fetching data from WarcraftLogs.
"""

import requests
from PySide6.QtCore import QThread, Signal
from wcl_core.cache import load_wowhead_cache, save_wowhead_cache
from wcl_core.common.errors import WarcraftLogsError
from wcl_core.models import CharacterProfile, RaidAnalysis

from ..services import (
    AppContext,
    PlayerService,
    RaidService,
    ReferenceAuthRequired,
    ReferenceRequestError,
    ReferenceService,
)


class AnalysisWorker(QThread):
    """Runs raid analysis in a background thread."""

    progress = Signal(str)
    finished = Signal(RaidAnalysis)
    error = Signal(str)

    def __init__(self, report_id: str, parent=None):
        super().__init__(parent)
        self.report_id = report_id

    def run(self):
        try:
            self.progress.emit("Loading configuration...")
            ctx = AppContext.desktop()

            self.progress.emit("Authenticating with WarcraftLogs API...")
            result = RaidService(ctx).analyze(self.report_id, progress=self.progress.emit)

            self.progress.emit("Analysis complete!")
            self.finished.emit(result)

        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class ReferenceAnalysisWorker(QThread):
    """Imports a reference report through ReferenceService, with the user-level OAuth token."""

    progress = Signal(str)
    finished = Signal(RaidAnalysis)
    error = Signal(str)
    auth_required = Signal()

    def __init__(self, report_id: str, label: str = "", parent=None):
        super().__init__(parent)
        self.report_id = report_id
        self.label = label

    def run(self):
        try:
            self.progress.emit("Loading configuration...")
            ctx = AppContext.desktop()

            self.progress.emit("Connecting with user credentials...")
            result = ReferenceService(ctx).import_reference(
                self.report_id, label=self.label or None, progress=self.progress.emit
            )

            self.progress.emit("Analysis complete!")
            self.finished.emit(result)

        except ReferenceAuthRequired:
            self.auth_required.emit()
        except ReferenceRequestError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class GuildInfoWorker(QThread):
    """Fetches guild name and server in a background thread."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, guild_id: int, parent=None):
        super().__init__(parent)
        self.guild_id = guild_id

    def run(self):
        try:
            info = RaidService(AppContext.desktop()).guild_info(self.guild_id)
            self.finished.emit(info)
        except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            self.error.emit(str(e))


class GuildReportsWorker(QThread):
    """Fetches guild report list in a background thread: the active profile's guild and era unless given one."""

    finished = Signal(list)
    error = Signal(str)

    def __init__(self, guild_id: int | None = None, parent=None):
        super().__init__(parent)
        self.guild_id = guild_id

    def run(self):
        try:
            reports = RaidService(AppContext.desktop()).guild_reports(self.guild_id)
            self.finished.emit(reports)
        except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            self.error.emit(str(e))


class CharacterProfileWorker(QThread):
    """Fetches character profile from WCL API in a background thread."""

    finished = Signal(CharacterProfile)
    error = Signal(str)

    def __init__(self, char_name: str, server: str, region: str, api_url: str, parent=None):
        super().__init__(parent)
        self.char_name = char_name
        self.server = server
        self.region = region
        self.api_url = api_url

    def run(self):
        try:
            profile = PlayerService(AppContext.desktop()).profile(
                self.char_name,
                self.server,
                self.region,
                api_url=self.api_url,
            )
            self.finished.emit(profile)
        except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            self.error.emit(str(e))


class WowheadResolverWorker(QThread):
    """Resolves item/gem names and tooltips from Wowhead API with persistent caching."""

    finished = Signal(dict)

    WOWHEAD_API = "https://nether.wowhead.com/tooltip"
    PARAMS = {"dataEnv": 5, "locale": 0}

    def __init__(self, item_ids: list[int], parent=None):
        super().__init__(parent)
        self.item_ids = item_ids

    def _resolve_item(self, item_id: int, cache: dict, names: dict, tooltips: dict) -> bool:
        sid = str(item_id)
        if sid in cache["items"]:
            names[item_id] = cache["items"][sid]
            if sid in cache["tooltips"]:
                tooltips[item_id] = cache["tooltips"][sid]
            return False
        try:
            resp = requests.get(
                f"{self.WOWHEAD_API}/item/{item_id}",
                params=self.PARAMS,
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                name = data.get("name")
                if name:
                    names[item_id] = name
                    cache["items"][sid] = name
                    tooltip_html = data.get("tooltip")
                    if tooltip_html:
                        tooltips[item_id] = tooltip_html
                        cache["tooltips"][sid] = tooltip_html
                    return True
        except (requests.RequestException, ValueError, KeyError):
            pass
        return False

    def run(self):
        cache = load_wowhead_cache()
        item_names: dict[int, str] = {}
        tooltips: dict[int, str] = {}
        dirty = False

        for item_id in self.item_ids:
            if item_id:
                dirty |= self._resolve_item(item_id, cache, item_names, tooltips)

        if dirty:
            save_wowhead_cache(cache)

        self.finished.emit(
            {
                "items": item_names,
                "tooltips": tooltips,
            }
        )
