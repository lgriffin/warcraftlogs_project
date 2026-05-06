"""
Auto-update logic: check GitHub Releases, download, and apply updates.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal

from . import paths
from .version import __version__

REPO = "lgriffin/warcraftlogs_project"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_COOLDOWN_SECONDS = 4 * 3600


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    release_notes: str
    asset_size: int
    published_at: str


def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split("."))


def check_for_update(force: bool = False) -> UpdateInfo | None:
    """Check GitHub for a newer release. Returns None if up-to-date or on error."""
    if not force:
        config_path = paths.get_config_path()
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = json.load(f)
                last_check = config.get("last_update_check", 0)
                if time.time() - last_check < CHECK_COOLDOWN_SECONDS:
                    return None
            except (json.JSONDecodeError, OSError):
                pass

    try:
        resp = requests.get(API_URL, timeout=10, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
    except (requests.RequestException, OSError):
        return None

    data = resp.json()
    tag = data.get("tag_name", "")
    if not tag:
        return None

    latest = _parse_version(tag)
    current = _parse_version(__version__)
    if latest <= current:
        _save_check_timestamp()
        return None

    zip_asset = None
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".zip") and "portable" not in name.lower():
            zip_asset = asset
            break

    if not zip_asset:
        for asset in data.get("assets", []):
            if asset.get("name", "").endswith(".zip"):
                zip_asset = asset
                break

    if not zip_asset:
        return None

    _save_check_timestamp()

    return UpdateInfo(
        version=tag.lstrip("v"),
        download_url=zip_asset["browser_download_url"],
        release_notes=data.get("body", ""),
        asset_size=zip_asset.get("size", 0),
        published_at=data.get("published_at", ""),
    )


def _save_check_timestamp():
    config_path = paths.get_config_path()
    config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    config["last_update_check"] = time.time()
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
    except OSError:
        pass


class UpdateDownloader(QThread):
    """Downloads an update zip with progress reporting."""
    progress = Signal(int, int)  # bytes_done, bytes_total
    finished = Signal(str)       # zip_path
    error = Signal(str)          # error message

    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self._info = info
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        update_dir = paths.get_update_dir()
        zip_path = update_dir / f"WarcraftLogsAnalyzer-v{self._info.version}.zip"

        try:
            resp = requests.get(self._info.download_url, stream=True, timeout=30)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", self._info.asset_size))
            done = 0

            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if self._cancelled:
                        f.close()
                        zip_path.unlink(missing_ok=True)
                        self.error.emit("Download cancelled")
                        return
                    f.write(chunk)
                    done += len(chunk)
                    self.progress.emit(done, total)

            if self._info.asset_size and abs(done - self._info.asset_size) > 1024:
                zip_path.unlink(missing_ok=True)
                self.error.emit(f"Download size mismatch: expected {self._info.asset_size}, got {done}")
                return

            self.finished.emit(str(zip_path))

        except (requests.RequestException, OSError) as e:
            zip_path.unlink(missing_ok=True)
            self.error.emit(str(e))


def apply_update(zip_path: str) -> bool:
    """Extract update zip and write a batch script to swap files on restart.

    Returns True if the script was created and the caller should quit the app.
    """
    install_dir = paths.get_install_dir()
    update_dir = paths.get_update_dir()
    staged_dir = update_dir / "staged"

    if staged_dir.exists():
        shutil.rmtree(staged_dir, ignore_errors=True)
    staged_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staged_dir)
    except (zipfile.BadZipFile, OSError) as e:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise RuntimeError(f"Failed to extract update: {e}") from e

    # Find the app folder inside the extracted zip
    # Zips typically contain a top-level WarcraftLogsAnalyzer/ folder
    extracted_app_dir = staged_dir / "WarcraftLogsAnalyzer"
    if not extracted_app_dir.exists():
        # Maybe the zip extracts directly without a wrapper folder
        contents = list(staged_dir.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            extracted_app_dir = contents[0]
        else:
            extracted_app_dir = staged_dir

    # Verify the extracted update has the exe
    exe_check = extracted_app_dir / "WarcraftLogsAnalyzer.exe"
    if not exe_check.exists():
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise RuntimeError("Update zip does not contain WarcraftLogsAnalyzer.exe")

    # Write the swap script
    script_path = install_dir / "_update.cmd"
    install_str = str(install_dir).replace("/", "\\")
    source_str = str(extracted_app_dir).replace("/", "\\")
    staged_str = str(staged_dir).replace("/", "\\")
    exe_str = str(install_dir / "WarcraftLogsAnalyzer.exe").replace("/", "\\")

    script = f"""@echo off
echo Updating WarcraftLogs Analyzer...
timeout /t 2 /nobreak >nul

rem Remove old app files
if exist "{install_str}\\_internal" rd /s /q "{install_str}\\_internal"
if exist "{install_str}\\WarcraftLogsAnalyzer.exe" del /f /q "{install_str}\\WarcraftLogsAnalyzer.exe"

rem Copy new files
xcopy /s /e /y /q "{source_str}\\*" "{install_str}\\"

rem Clean up staging
rd /s /q "{staged_str}"

rem Clean up downloaded zip
if exist "{zip_path.replace("/", chr(92))}" del /f /q "{zip_path.replace("/", chr(92))}"

rem Relaunch
start "" "{exe_str}"

rem Delete this script
del "%~f0"
"""

    try:
        with open(script_path, "w") as f:
            f.write(script)
    except OSError as e:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise RuntimeError(
            f"Cannot write update script. Is the app in a read-only folder?\n{e}"
        ) from e

    # Launch the script detached
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
    subprocess.Popen(
        ["cmd.exe", "/c", str(script_path)],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return True
