"""
Background worker thread for API calls.

Keeps the UI responsive while fetching data from WarcraftLogs.
"""

import requests

from PySide6.QtCore import QThread, Signal

from ..auth import TokenManager
from ..cache import load_wowhead_cache, save_wowhead_cache
from ..client import WarcraftLogsClient
from ..common.errors import WarcraftLogsError
from ..config import load_config
from ..analysis import analyze_raid
from ..models import RaidAnalysis, CharacterProfile


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
            config = load_config()
            role_thresholds = config.get("role_thresholds", {})

            self.progress.emit("Authenticating with WarcraftLogs API...")
            token_mgr = TokenManager(config["client_id"], config["client_secret"])
            client = WarcraftLogsClient(token_mgr)

            self.progress.emit("Analyzing raid data (this may take a minute)...")
            result = analyze_raid(
                client, self.report_id,
                healer_threshold=role_thresholds.get("healer_min_healing", 50000),
                tank_min_taken=role_thresholds.get("tank_min_taken", 150000),
                tank_min_mitigation=role_thresholds.get("tank_min_mitigation", 40),
            )

            self.progress.emit("Analysis complete!")
            self.finished.emit(result)

        except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            self.error.emit(str(e))


class GuildInfoWorker(QThread):
    """Fetches guild name and server in a background thread."""

    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, guild_id: int, parent=None):
        super().__init__(parent)
        self.guild_id = guild_id

    def run(self):
        try:
            config = load_config()
            token_mgr = TokenManager(config["client_id"], config["client_secret"])
            client = WarcraftLogsClient(token_mgr)
            info = client.get_guild_info(self.guild_id)
            self.finished.emit(info)
        except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            self.error.emit(str(e))


class GuildReportsWorker(QThread):
    """Fetches guild report list in a background thread."""

    finished = Signal(list)
    error = Signal(str)

    def __init__(self, guild_id: int, parent=None):
        super().__init__(parent)
        self.guild_id = guild_id

    def run(self):
        try:
            config = load_config()
            token_mgr = TokenManager(config["client_id"], config["client_secret"])
            client = WarcraftLogsClient(token_mgr)
            reports = client.get_guild_reports(self.guild_id)
            self.finished.emit(reports)
        except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            self.error.emit(str(e))


class CharacterProfileWorker(QThread):
    """Fetches character profile from WCL API in a background thread."""

    finished = Signal(CharacterProfile)
    error = Signal(str)

    def __init__(self, char_name: str, server: str, region: str,
                 api_url: str, parent=None):
        super().__init__(parent)
        self.char_name = char_name
        self.server = server
        self.region = region
        self.api_url = api_url

    def run(self):
        try:
            config = load_config()
            token_mgr = TokenManager(config["client_id"], config["client_secret"])
            client = WarcraftLogsClient(token_mgr)
            profile = client.get_character_profile(
                self.char_name, self.server, self.region,
                api_url=self.api_url,
            )
            self.finished.emit(profile)
        except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            self.error.emit(str(e))


class WowheadResolverWorker(QThread):
    """Resolves item/gem/enchant names and tooltips from Wowhead API with persistent caching."""

    finished = Signal(dict)

    WOWHEAD_API = "https://nether.wowhead.com/tooltip"
    PARAMS = {"dataEnv": 5, "locale": 0}

    def __init__(self, item_ids: list[int], enchant_ids: list[int], parent=None):
        super().__init__(parent)
        self.item_ids = item_ids
        self.enchant_ids = enchant_ids

    def _resolve_item(self, item_id: int, cache: dict,
                      names: dict, tooltips: dict) -> bool:
        sid = str(item_id)
        if sid in cache["items"]:
            names[item_id] = cache["items"][sid]
            if sid in cache["tooltips"]:
                tooltips[item_id] = cache["tooltips"][sid]
            return False
        try:
            resp = requests.get(
                f"{self.WOWHEAD_API}/item/{item_id}",
                params=self.PARAMS, timeout=5,
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
        enchant_names: dict[int, str] = {}
        tooltips: dict[int, str] = {}
        dirty = False

        for item_id in self.item_ids:
            if item_id:
                dirty |= self._resolve_item(item_id, cache, item_names, tooltips)

        for ench_id in self.enchant_ids:
            if not ench_id:
                continue
            sid = str(ench_id)
            if sid in cache["enchants"]:
                enchant_names[ench_id] = cache["enchants"][sid]
                continue
            for endpoint in ("spell", "item"):
                try:
                    resp = requests.get(
                        f"{self.WOWHEAD_API}/{endpoint}/{ench_id}",
                        params=self.PARAMS, timeout=5,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        name = data.get("name")
                        if name:
                            enchant_names[ench_id] = name
                            cache["enchants"][sid] = name
                            dirty = True
                            break
                except (requests.RequestException, ValueError, KeyError):
                    continue

        if dirty:
            save_wowhead_cache(cache)

        self.finished.emit({
            "items": item_names,
            "enchants": enchant_names,
            "tooltips": tooltips,
        })
