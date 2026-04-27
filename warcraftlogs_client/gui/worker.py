"""
Background worker thread for API calls.

Keeps the UI responsive while fetching data from WarcraftLogs.
"""

import requests

from PySide6.QtCore import QThread, Signal

from ..auth import TokenManager
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
