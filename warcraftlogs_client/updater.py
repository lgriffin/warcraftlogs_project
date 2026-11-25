"""
Auto-update logic: check GitHub Releases, download, and apply updates.

Integrity (REQ-CORE-REL-001): every release publishes a ``SHA256SUMS`` asset listing the
SHA-256 of each downloadable file. The release workflow signs ``SHA256SUMS`` with Sigstore
keyless signing (cosign + GitHub OIDC) and publishes the bundle as
``SHA256SUMS.sigstore.json``. The updater refuses to stage a zip unless its digest matches
the entry in ``SHA256SUMS``; a missing ``SHA256SUMS`` or a missing/mismatched entry is an error.

Two kinds of Windows copy update themselves:

* **Installed** (``WarcraftLogsAnalyzer-<version>-Setup.exe``, Inno Setup leaves ``unins000.exe`` next to the app):
  the updater downloads the new release's Setup.exe and runs it silently over the old install, so the Start menu
  entry, the uninstaller and "Apps & features" all show the new version.
* **Portable** (the ``-portable.zip``): the updater downloads the new zip and swaps the files on restart.

TODO(REQ-CORE-REL-001): verify the Sigstore bundle in-app as well. That needs the
``sigstore`` package (plus its TUF/crypto dependency tree) inside the frozen app, so for
now the trust chain is: CI signs SHA256SUMS keylessly (verifiable offline with
``cosign verify-blob``), and the app enforces the digest match against the release's
SHA256SUMS over HTTPS from github.com.
"""

import hashlib
import hmac
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests
from wcl_core import paths

from .version import __version__

REPO = "lgriffin/warcraftlogs_project"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_COOLDOWN_SECONDS = 4 * 3600
CHECKSUMS_ASSET_NAMES = ("SHA256SUMS", "SHA256SUMS.txt")
_HEX_DIGITS = frozenset("0123456789abcdef")
SETUP_SUFFIX = "-Setup.exe"
_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")
# Inno Setup flags for an unattended upgrade: no wizard, no prompts, close the app if it is still running.
SILENT_INSTALL_FLAGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/SP-")


class UpdateVerificationError(RuntimeError):
    """The downloaded update could not be proven to match the release's SHA256SUMS."""


class UpdateDownloadError(RuntimeError):
    """The download was cancelled or did not arrive whole."""


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    release_notes: str
    asset_size: int
    published_at: str
    asset_name: str = ""
    checksums_url: str = ""


def self_update_supported(platform: str = sys.platform) -> bool:
    """Whether this app can update itself: the release zip and its swap script are Windows-only.

    On Linux and macOS the app runs from a source checkout, so it updates with ``git pull`` and a reinstall
    (``scripts/install_linux.sh``) instead of offering a Windows download.
    """
    return platform == "win32"


def manual_update_steps(platform: str = sys.platform) -> str:
    """How to update where the app cannot update itself (see ``self_update_supported``)."""
    if platform.startswith("linux"):
        return (
            "run git pull in the app's folder (or unpack the newest Linux release over it), "
            "then scripts/install_linux.sh"
        )
    return "run git pull in the app's folder, then pip install -e . again"


def _parse_version(v: str) -> tuple[int, ...] | None:
    """``v4.5.0`` -> (4, 5, 0), padded to three parts; None for a tag that is not a plain release (``v5.0.0-rc1``)."""
    match = _VERSION.fullmatch(v.strip())
    if not match:
        return None
    parts = tuple(int(x) for x in match.group(1).split("."))
    return parts + (0,) * (3 - len(parts))


def installed_with_setup(install_dir: Path | None = None) -> bool:
    """Whether this copy came from the Setup.exe installer: Inno Setup leaves its uninstaller next to the app."""
    folder = install_dir if install_dir is not None else paths.get_install_dir()
    return any(folder.glob("unins*.exe"))


def pick_update_asset(assets: list[dict], installed: bool) -> dict | None:
    """The release file this copy updates from: the Setup.exe for an installed copy, else the zip.

    An installed copy falls back to the zip when a release has no installer; the zip swap works in its folder too.
    """
    names = [(asset.get("name", ""), asset) for asset in assets]
    if installed:
        for name, asset in names:
            if name.endswith(SETUP_SUFFIX):
                return asset
    zips = [asset for name, asset in names if name.endswith(".zip")]
    for asset in zips:
        if "portable" not in asset.get("name", "").lower():
            return asset
    return zips[0] if zips else None


def _recently_checked() -> bool:
    config_path = paths.get_config_path()
    if not config_path.exists():
        return False
    try:
        with config_path.open() as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return time.time() - config.get("last_update_check", 0) < CHECK_COOLDOWN_SECONDS


def check_for_update(force: bool = False) -> UpdateInfo | None:
    """Check GitHub for a newer release. Returns None if up-to-date or on error."""
    if not force and _recently_checked():
        return None

    try:
        resp = requests.get(API_URL, timeout=10, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, OSError, ValueError):
        return None

    tag = data.get("tag_name", "")
    latest = _parse_version(tag)
    current = _parse_version(__version__)
    if latest is None or current is None:
        return None
    if latest <= current:
        _save_check_timestamp()
        return None

    assets = data.get("assets", [])
    asset = pick_update_asset(assets, installed_with_setup())
    if not asset:
        return None

    _save_check_timestamp()

    checksums_asset = find_checksums_asset(assets)

    return UpdateInfo(
        version=tag.lstrip("v"),
        download_url=asset["browser_download_url"],
        release_notes=data.get("body", ""),
        asset_size=asset.get("size", 0),
        published_at=data.get("published_at", ""),
        asset_name=asset.get("name", ""),
        checksums_url=checksums_asset.get("browser_download_url", "") if checksums_asset else "",
    )


def find_checksums_asset(assets: list[dict]) -> dict | None:
    """Return the release's SHA256SUMS asset, or None when the release does not publish one."""
    for wanted in CHECKSUMS_ASSET_NAMES:
        for asset in assets:
            if asset.get("name") == wanted:
                return asset
    return None


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse ``sha256sum``-style lines (``<hex>  <name>`` or ``<hex> *<name>``) into {name: hex}.

    Malformed lines are ignored; a UTF-8 BOM and CRLF line endings (PowerShell output) are tolerated.
    """
    digests: dict[str, str] = {}
    for raw_line in text.lstrip("\ufeff").splitlines():
        parts = raw_line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].lower(), parts[1].strip().lstrip("*")
        if len(digest) == 64 and set(digest) <= _HEX_DIGITS and name:
            digests[name] = digest
    return digests


def fetch_expected_sha256(info: UpdateInfo) -> str:
    """Download the release's SHA256SUMS and return the digest listed for ``info.asset_name``."""
    if not info.checksums_url:
        raise UpdateVerificationError(
            "This release does not publish a SHA256SUMS file, so the download cannot be verified. "
            "The update was not installed; download it manually from the GitHub releases page."
        )
    try:
        resp = requests.get(info.checksums_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise UpdateVerificationError(f"Could not download SHA256SUMS to verify the update: {e}") from e

    expected = parse_sha256sums(resp.text).get(info.asset_name)
    if not expected:
        raise UpdateVerificationError(
            f"SHA256SUMS does not list {info.asset_name!r}, so the download cannot be verified. "
            "The update was not installed."
        )
    return expected


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_update_zip(zip_path: str, expected_sha256: str) -> None:
    """Raise UpdateVerificationError unless *zip_path* hashes to *expected_sha256*."""
    expected_sha256 = (expected_sha256 or "").strip().lower()
    if len(expected_sha256) != 64 or not set(expected_sha256) <= _HEX_DIGITS:
        raise UpdateVerificationError(
            "No valid expected SHA-256 for this update; refusing to install an unverified file."
        )
    actual = sha256_file(zip_path)
    if not hmac.compare_digest(actual, expected_sha256):
        raise UpdateVerificationError(
            "The downloaded update does not match the SHA-256 published in the release's SHA256SUMS "
            "(it may be corrupted or tampered with). It was not installed.\n"
            f"Expected {expected_sha256}\nGot      {actual}"
        )


def _save_check_timestamp():
    config_path = paths.get_config_path()
    config = {}
    if config_path.exists():
        try:
            with config_path.open() as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    config["last_update_check"] = time.time()
    try:
        with config_path.open("w") as f:
            json.dump(config, f, indent=4)
    except OSError:
        pass


@dataclass
class DownloadedUpdate:
    zip_path: str  # the downloaded release file: the portable zip, or the Setup.exe for an installed copy
    expected_sha256: str  # from SHA256SUMS; pass it to apply_update()


def _download_path(info: UpdateInfo) -> Path:
    """Where the release file lands: its own name (only the final part, never a path), else a versioned zip name."""
    name = Path(info.asset_name).name if info.asset_name else ""
    return paths.get_update_dir() / (name or f"WarcraftLogsAnalyzer-v{info.version}.zip")


def download_update(
    info: UpdateInfo,
    on_progress: Callable[[int, int], None] = lambda _done, _total: None,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> DownloadedUpdate:
    """Download and verify the update file (zip or Setup.exe), reporting (bytes_done, bytes_total) as it goes.

    Raises UpdateVerificationError, UpdateDownloadError, requests.RequestException or OSError (or whatever a
    callback raises), and leaves no partial zip behind when it does.
    """
    zip_path = _download_path(info)
    try:
        # Resolve the expected digest first: no SHA256SUMS entry means no download at all.
        expected_sha256 = fetch_expected_sha256(info)
        resp = requests.get(info.download_url, stream=True, timeout=30)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", info.asset_size))
        done = 0

        with zip_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if is_cancelled():
                    raise UpdateDownloadError("Download cancelled")
                f.write(chunk)
                done += len(chunk)
                on_progress(done, total)

        if info.asset_size and abs(done - info.asset_size) > 1024:
            raise UpdateDownloadError(f"Download size mismatch: expected {info.asset_size}, got {done}")

        verify_update_zip(str(zip_path), expected_sha256)
    except BaseException:
        zip_path.unlink(missing_ok=True)
        raise
    return DownloadedUpdate(str(zip_path), expected_sha256)


def apply_update(zip_path: str, expected_sha256: str) -> bool:
    """Verify the download against SHA256SUMS and hand over to a script that updates the app once it quits.

    A Setup.exe is run silently over the install; a zip is extracted and its files swapped in. Raises
    UpdateVerificationError (a RuntimeError) without staging anything if the digest does not match.
    Returns True if the script was started and the caller should quit the app.
    """
    verify_update_zip(zip_path, expected_sha256)
    if zip_path.lower().endswith(".exe"):
        script_path = paths.get_update_dir() / "_update.cmd"
        script = installer_update_script(zip_path, paths.get_install_dir())
        _write_script(script_path, script)
    else:
        script_path = paths.get_install_dir() / "_update.cmd"
        staged_dir, script = _stage_zip(zip_path)
        try:
            _write_script(script_path, script)
        except RuntimeError:
            shutil.rmtree(staged_dir, ignore_errors=True)
            raise
    _launch_detached(script_path)
    return True


def _win(path: Path | str) -> str:
    return str(path).replace("/", "\\")


def installer_update_script(setup_path: str, install_dir: Path) -> str:
    """A batch script that waits for the app to quit, runs the new Setup.exe silently, then relaunches the app.

    The installer upgrades the existing install in place (same AppId, its previous folder), keeping the
    uninstaller and the version in "Apps & features" right. User data lives in %APPDATA% and is untouched.
    """
    setup = _win(setup_path)
    exe = _win(install_dir / "WarcraftLogsAnalyzer.exe")
    flags = " ".join(SILENT_INSTALL_FLAGS)
    return f"""@echo off
echo Updating WarcraftLogs Analyzer...
timeout /t 2 /nobreak >nul

start "" /wait "{setup}" {flags}

rem Clean up the downloaded installer
if exist "{setup}" del /f /q "{setup}"

rem Relaunch
start "" "{exe}"

rem Delete this script
del "%~f0"
"""


def _stage_zip(zip_path: str) -> tuple[Path, str]:
    """Extract the zip into the update folder and return (staged folder, swap script)."""
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

    install_str = _win(install_dir)
    source_str = _win(extracted_app_dir)
    staged_str = _win(staged_dir)
    exe_str = _win(install_dir / "WarcraftLogsAnalyzer.exe")
    zip_str = _win(zip_path)

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
if exist "{zip_str}" del /f /q "{zip_str}"

rem Relaunch
start "" "{exe_str}"

rem Delete this script
del "%~f0"
"""
    return staged_dir, script


def _write_script(script_path: Path, script: str) -> None:
    try:
        with script_path.open("w") as f:
            f.write(script)
    except OSError as e:
        raise RuntimeError(f"Cannot write update script. Is the app in a read-only folder?\n{e}") from e


def _launch_detached(script_path: Path) -> None:
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
    subprocess.Popen(
        ["cmd.exe", "/c", str(script_path)],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
