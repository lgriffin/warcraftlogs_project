"""Centralized path resolution for development and frozen (PyInstaller) environments."""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "WarcraftLogsAnalyzer"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


_app_dir: Path | None = None


def set_app_dir(path: Path) -> None:
    """Tell wcl-core where the host application lives.

    The desktop app and CLI call this on import with the project root, so config.json,
    the database and the cache stay where they always were.
    """
    global _app_dir
    _app_dir = Path(path)


def get_app_dir() -> Path:
    """Return the host application's directory.

    When frozen: sys._MEIPASS (onefile) or the exe's directory (onedir).
    Otherwise: the directory set with set_app_dir(), then $WCL_APP_DIR, then the working directory.
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))  # noqa: B009 - set only by PyInstaller, unknown to typeshed
    if _app_dir is not None:
        return _app_dir
    env = os.environ.get("WCL_APP_DIR")
    return Path(env) if env else Path.cwd()


def get_data_dir() -> Path:
    """Read-only analysis data shipped inside the wcl_core package (spell data, role configs)."""
    return Path(__file__).resolve().parent / "data"


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
    return get_data_dir() / "spell_data"


def get_template_dir() -> Path:
    return get_app_dir() / "warcraftlogs_client" / "templates"


def get_logo_path() -> Path:
    return get_app_dir() / "logo.png"


def get_user_token_path() -> Path:
    return get_user_data_dir() / "user_token.json"


def get_consumes_config_path() -> Path:
    return get_data_dir() / "consumes_config.json"


def get_interrupt_config_path() -> Path:
    return get_data_dir() / "interrupt_config.json"


def get_debuff_config_path() -> Path:
    return get_data_dir() / "debuff_config.json"


def get_totem_config_path() -> Path:
    return get_data_dir() / "totem_config.json"


def get_cooldowns_config_path() -> Path:
    return get_data_dir() / "cooldowns_config.json"


def get_update_dir() -> Path:
    """Temp directory for downloading and staging updates."""
    base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    update_dir = Path(base) / APP_NAME / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    return update_dir


def get_install_dir() -> Path:
    """The directory containing WarcraftLogsAnalyzer.exe (the portable install root)."""
    if is_frozen():
        return Path(sys.executable).parent
    return get_app_dir()


def ensure_first_run_config() -> None:
    """Copy config.example.json to user data dir if config.json doesn't exist yet."""
    config_path = get_config_path()
    if not config_path.exists():
        example = get_app_dir() / "config.example.json"
        if example.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(example, config_path)
