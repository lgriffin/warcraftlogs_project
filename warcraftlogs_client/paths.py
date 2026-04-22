"""Centralized path resolution for development and frozen (PyInstaller) environments."""

import os
import sys
import shutil
from pathlib import Path

APP_NAME = "WarcraftLogsAnalyzer"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_app_dir() -> Path:
    """Return the directory containing bundled read-only application files.

    In development: the project root (parent of warcraftlogs_client/).
    When frozen: sys._MEIPASS (onefile) or the exe's directory (onedir).
    """
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_user_data_dir() -> Path:
    """Writable user data directory (%APPDATA%/WarcraftLogsAnalyzer)."""
    if not is_frozen():
        return get_app_dir()
    base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    data_dir = Path(base) / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_cache_dir() -> Path:
    if not is_frozen():
        cache_dir = get_app_dir() / ".cache"
    else:
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        cache_dir = Path(base) / APP_NAME / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_config_path() -> Path:
    return get_user_data_dir() / "config.json"


def get_db_path() -> Path:
    return get_user_data_dir() / "warcraftlogs_history.db"


def get_reports_dir() -> Path:
    reports = get_user_data_dir() / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    return reports


def get_spell_data_dir() -> Path:
    return get_app_dir() / "spell_data"


def get_template_dir() -> Path:
    return get_app_dir() / "warcraftlogs_client" / "templates"


def get_logo_path() -> Path:
    return get_app_dir() / "logo.png"


def get_consumes_config_path() -> Path:
    return get_app_dir() / "consumes_config.json"


def ensure_first_run_config():
    """Copy config.example.json to user data dir if config.json doesn't exist yet."""
    config_path = get_config_path()
    if not config_path.exists():
        example = get_app_dir() / "config.example.json"
        if example.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(example, config_path)
