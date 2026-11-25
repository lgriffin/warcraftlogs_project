"""REQ-CORE-REL-001: the updater refuses to stage a zip whose SHA-256 does not match SHA256SUMS."""

import ast
import hashlib
import json
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from warcraftlogs_client import updater
from warcraftlogs_client.updater import (
    UpdateDownloadError,
    UpdateInfo,
    UpdateVerificationError,
    apply_update,
    download_update,
    fetch_expected_sha256,
    find_checksums_asset,
    parse_sha256sums,
    verify_update_zip,
)

ZIP_NAME = "WarcraftLogsAnalyzer-v9.9.9-portable.zip"
SUMS_URL = "https://github.com/lgriffin/warcraftlogs_project/releases/download/v9.9.9/SHA256SUMS"


def make_update_zip(path) -> str:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("WarcraftLogsAnalyzer/WarcraftLogsAnalyzer.exe", b"MZ fake exe")
        zf.writestr("WarcraftLogsAnalyzer/_internal/lib.dll", b"library")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tamper(path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))


def make_info(checksums_url: str = SUMS_URL) -> UpdateInfo:
    return UpdateInfo(
        version="9.9.9",
        download_url=f"https://example.test/{ZIP_NAME}",
        release_notes="",
        asset_size=0,
        published_at="",
        asset_name=ZIP_NAME,
        checksums_url=checksums_url,
    )


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    install = tmp_path / "install"
    update = tmp_path / "update"
    install.mkdir()
    update.mkdir()
    monkeypatch.setattr(updater.paths, "get_install_dir", lambda: install)
    monkeypatch.setattr(updater.paths, "get_update_dir", lambda: update)
    popen = MagicMock()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)
    return {"install": install, "update": update, "staged": update / "staged", "popen": popen}


class TestParseSha256Sums:
    def test_parses_text_and_binary_mode_lines(self):
        a, b = "a" * 64, "B" * 64
        sums = parse_sha256sums(f"{a}  one.zip\n{b} *two.exe\n")
        assert sums == {"one.zip": a, "two.exe": b.lower()}

    def test_tolerates_bom_crlf_and_junk(self):
        d = "0123456789abcdef" * 4
        text = f"﻿{d}  app.zip\r\nnot a checksum line\r\nabc  short.zip\r\n\r\n"
        assert parse_sha256sums(text) == {"app.zip": d}

    def test_non_hex_digest_ignored(self):
        assert parse_sha256sums(("g" * 64) + "  app.zip\n") == {}


class TestFindChecksumsAsset:
    def test_prefers_sha256sums(self):
        assets = [{"name": "SHA256SUMS.txt"}, {"name": "x.zip"}, {"name": "SHA256SUMS"}]
        assert find_checksums_asset(assets) == {"name": "SHA256SUMS"}

    def test_accepts_legacy_txt(self):
        assert find_checksums_asset([{"name": "SHA256SUMS.txt"}]) == {"name": "SHA256SUMS.txt"}

    def test_missing(self):
        assert find_checksums_asset([{"name": "x.zip"}, {"name": "SHA256SUMS.sigstore.json"}]) is None


class TestCheckForUpdateRecordsChecksums:
    def _release(self, assets):
        resp = MagicMock()
        resp.json.return_value = {"tag_name": "v999.0.0", "assets": assets, "body": "", "published_at": ""}
        resp.raise_for_status.return_value = None
        return resp

    def test_records_zip_name_and_checksums_url(self, monkeypatch):
        monkeypatch.setattr(updater, "_save_check_timestamp", lambda: None)
        assets = [
            {"name": ZIP_NAME, "browser_download_url": "https://x/zip", "size": 10},
            {"name": "SHA256SUMS", "browser_download_url": SUMS_URL},
            {"name": "SHA256SUMS.sigstore.json", "browser_download_url": "https://x/bundle"},
        ]
        with patch.object(updater.requests, "get", return_value=self._release(assets)):
            info = updater.check_for_update(force=True)
        assert info is not None
        assert info.asset_name == ZIP_NAME
        assert info.checksums_url == SUMS_URL

    def test_release_without_checksums_has_empty_url(self, monkeypatch):
        monkeypatch.setattr(updater, "_save_check_timestamp", lambda: None)
        assets = [{"name": ZIP_NAME, "browser_download_url": "https://x/zip", "size": 10}]
        with patch.object(updater.requests, "get", return_value=self._release(assets)):
            info = updater.check_for_update(force=True)
        assert info is not None
        assert info.checksums_url == ""


class TestFetchExpectedSha256:
    def test_returns_listed_digest(self):
        digest = "c" * 64
        resp = MagicMock(text=f"{'d' * 64}  other.exe\n{digest}  {ZIP_NAME}\n")
        resp.raise_for_status.return_value = None
        with patch.object(updater.requests, "get", return_value=resp):
            assert fetch_expected_sha256(make_info()) == digest

    def test_missing_sha256sums_refused(self):
        with pytest.raises(UpdateVerificationError, match="does not publish a SHA256SUMS"):
            fetch_expected_sha256(make_info(checksums_url=""))

    def test_zip_not_listed_refused(self):
        resp = MagicMock(text=f"{'d' * 64}  something-else.zip\n")
        resp.raise_for_status.return_value = None
        with (
            patch.object(updater.requests, "get", return_value=resp),
            pytest.raises(UpdateVerificationError, match="does not list"),
        ):
            fetch_expected_sha256(make_info())

    def test_download_failure_refused(self):
        with (
            patch.object(updater.requests, "get", side_effect=requests.ConnectionError("down")),
            pytest.raises(UpdateVerificationError, match="Could not download SHA256SUMS"),
        ):
            fetch_expected_sha256(make_info())


@pytest.mark.security
class TestTamperedZipRefused:
    def test_verify_accepts_matching_digest(self, tmp_path):
        zip_path = tmp_path / ZIP_NAME
        digest = make_update_zip(zip_path)
        assert verify_update_zip(str(zip_path), digest.upper()) is None  # case-insensitive, no exception

    def test_verify_rejects_tampered_zip(self, tmp_path):
        zip_path = tmp_path / ZIP_NAME
        digest = make_update_zip(zip_path)
        tamper(zip_path)
        with pytest.raises(UpdateVerificationError, match="does not match the SHA-256"):
            verify_update_zip(str(zip_path), digest)

    def test_verify_rejects_missing_digest(self, tmp_path):
        zip_path = tmp_path / ZIP_NAME
        make_update_zip(zip_path)
        with pytest.raises(UpdateVerificationError, match="unverified"):
            verify_update_zip(str(zip_path), "")
        with pytest.raises(UpdateVerificationError, match="unverified"):
            verify_update_zip(str(zip_path), "not-a-digest")

    def test_apply_update_stages_verified_zip(self, tmp_path, dirs):
        """Positive control: an untampered zip is staged and the swap script launched."""
        zip_path = tmp_path / ZIP_NAME
        digest = make_update_zip(zip_path)
        assert apply_update(str(zip_path), digest) is True
        assert (dirs["staged"] / "WarcraftLogsAnalyzer" / "WarcraftLogsAnalyzer.exe").exists()
        assert (dirs["install"] / "_update.cmd").exists()
        dirs["popen"].assert_called_once()

    def test_apply_update_refuses_tampered_zip(self, tmp_path, dirs):
        zip_path = tmp_path / ZIP_NAME
        digest = make_update_zip(zip_path)
        tamper(zip_path)
        with pytest.raises(UpdateVerificationError) as exc_info:
            apply_update(str(zip_path), digest)
        assert isinstance(exc_info.value, RuntimeError)  # UpdateDialog shows RuntimeError text to the user
        assert "SHA256SUMS" in str(exc_info.value)
        assert not dirs["staged"].exists()
        assert not (dirs["install"] / "_update.cmd").exists()
        dirs["popen"].assert_not_called()

    def test_apply_update_refuses_without_digest(self, tmp_path, dirs):
        zip_path = tmp_path / ZIP_NAME
        make_update_zip(zip_path)
        with pytest.raises(UpdateVerificationError):
            apply_update(str(zip_path), "")
        assert not dirs["staged"].exists()
        dirs["popen"].assert_not_called()


def test_updater_does_not_import_qt():
    """Issue #167: the update logic stays importable on a CLI-only install; the QThread lives in gui/."""
    tree = ast.parse(Path(updater.__file__).read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {name for name in imported if name.split(".")[0] == "PySide6"}


class TestDownloadUpdate:
    def _get(self, sums_text: str, zip_bytes: bytes):
        sums = MagicMock(text=sums_text)
        sums.raise_for_status.return_value = None
        download = MagicMock(headers={"content-length": str(len(zip_bytes))})
        download.raise_for_status.return_value = None
        download.iter_content.return_value = [zip_bytes[:10], zip_bytes[10:]]
        return lambda url, **_kwargs: sums if url == SUMS_URL else download

    def _zip(self, tmp_path, tampered=False):
        source = tmp_path / "src.zip"
        digest = make_update_zip(source)
        if tampered:
            tamper(source)
        return source.read_bytes(), f"{digest}  {ZIP_NAME}\n", digest

    def test_verified_download_returns_path_and_digest(self, dirs, tmp_path):
        zip_bytes, sums, digest = self._zip(tmp_path)
        progress = []
        with patch.object(updater.requests, "get", side_effect=self._get(sums, zip_bytes)):
            result = download_update(make_info(), lambda done, total: progress.append((done, total)))
        assert result.expected_sha256 == digest
        assert Path(result.zip_path).read_bytes() == zip_bytes
        assert progress == [(10, len(zip_bytes)), (len(zip_bytes), len(zip_bytes))]

    def test_tampered_download_raises_and_is_deleted(self, dirs, tmp_path):
        zip_bytes, sums, _ = self._zip(tmp_path, tampered=True)
        with (
            patch.object(updater.requests, "get", side_effect=self._get(sums, zip_bytes)),
            pytest.raises(UpdateVerificationError),
        ):
            download_update(make_info())
        assert list(dirs["update"].iterdir()) == []

    def test_cancel_stops_and_deletes_partial_zip(self, dirs, tmp_path):
        zip_bytes, sums, _ = self._zip(tmp_path)
        with (
            patch.object(updater.requests, "get", side_effect=self._get(sums, zip_bytes)),
            pytest.raises(UpdateDownloadError, match="Download cancelled"),
        ):
            download_update(make_info(), is_cancelled=lambda: True)
        assert list(dirs["update"].iterdir()) == []

    def test_size_mismatch_raises_and_deletes_zip(self, dirs, tmp_path):
        zip_bytes, sums, _ = self._zip(tmp_path)
        info = make_info()
        info.asset_size = len(zip_bytes) + 4096
        with (
            patch.object(updater.requests, "get", side_effect=self._get(sums, zip_bytes)),
            pytest.raises(UpdateDownloadError, match="size mismatch"),
        ):
            download_update(info)
        assert list(dirs["update"].iterdir()) == []

    def test_failing_progress_callback_deletes_partial_zip(self, dirs, tmp_path):
        zip_bytes, sums, _ = self._zip(tmp_path)

        def explode(_done, _total):
            raise ValueError("progress callback failed")

        with (
            patch.object(updater.requests, "get", side_effect=self._get(sums, zip_bytes)),
            pytest.raises(ValueError, match="progress callback failed"),
        ):
            download_update(make_info(), explode)
        assert list(dirs["update"].iterdir()) == []


def test_only_windows_updates_itself():
    """The release zip and its swap script are Windows-only; a Linux source install updates with git pull."""
    assert updater.self_update_supported("win32") is True
    assert updater.self_update_supported("linux") is False
    assert updater.self_update_supported("darwin") is False


def test_manual_update_steps_name_the_linux_script_only_on_linux():
    assert "scripts/install_linux.sh" in updater.manual_update_steps("linux")
    assert "release" in updater.manual_update_steps("linux")  # a release bundle has no .git to pull
    assert "install_linux" not in updater.manual_update_steps("darwin")


SETUP_NAME = "WarcraftLogsAnalyzer-9.9.9-Setup.exe"
RELEASE_ASSETS = [
    {"name": "SHA256SUMS", "browser_download_url": SUMS_URL},
    {"name": SETUP_NAME, "browser_download_url": "https://x/setup", "size": 20},
    {"name": ZIP_NAME, "browser_download_url": "https://x/zip", "size": 10},
    {"name": "WarcraftLogsAnalyzer-v9.9.9-linux.tar.gz", "browser_download_url": "https://x/tgz", "size": 5},
]


class TestInstalledCopiesUpdateFromTheInstaller:
    def test_installed_copy_is_detected_by_its_uninstaller(self, tmp_path):
        assert updater.installed_with_setup(tmp_path) is False
        (tmp_path / "unins000.exe").write_bytes(b"MZ")
        assert updater.installed_with_setup(tmp_path) is True

    def test_installed_copy_picks_the_setup_exe(self):
        assert updater.pick_update_asset(RELEASE_ASSETS, installed=True)["name"] == SETUP_NAME

    def test_portable_copy_picks_the_zip(self):
        assert updater.pick_update_asset(RELEASE_ASSETS, installed=False)["name"] == ZIP_NAME

    def test_installed_copy_falls_back_to_the_zip_without_an_installer(self):
        assets = [a for a in RELEASE_ASSETS if a["name"] != SETUP_NAME]
        assert updater.pick_update_asset(assets, installed=True)["name"] == ZIP_NAME

    def test_no_windows_file_means_no_update(self):
        assert updater.pick_update_asset(RELEASE_ASSETS[3:], installed=True) is None

    def test_check_offers_the_setup_exe_to_an_installed_copy(self, monkeypatch, tmp_path):
        monkeypatch.setattr(updater, "_save_check_timestamp", lambda: None)
        (tmp_path / "unins000.exe").write_bytes(b"MZ")
        monkeypatch.setattr(updater.paths, "get_install_dir", lambda: tmp_path)
        resp = MagicMock()
        resp.json.return_value = {"tag_name": "v999.0.0", "assets": RELEASE_ASSETS, "body": "", "published_at": ""}
        with patch.object(updater.requests, "get", return_value=resp):
            info = updater.check_for_update(force=True)
        assert info is not None
        assert (info.asset_name, info.download_url, info.checksums_url) == (SETUP_NAME, "https://x/setup", SUMS_URL)

    def test_setup_exe_is_downloaded_under_its_own_name(self, dirs):
        info = make_info()
        info.asset_name = SETUP_NAME
        assert updater._download_path(info) == dirs["update"] / SETUP_NAME
        info.asset_name = "../../evil.exe"
        assert updater._download_path(info) == dirs["update"] / "evil.exe"

    def test_apply_runs_the_verified_installer_silently_then_relaunches(self, tmp_path, dirs):
        setup = dirs["update"] / SETUP_NAME
        setup.write_bytes(b"MZ installer")
        digest = hashlib.sha256(setup.read_bytes()).hexdigest()
        assert apply_update(str(setup), digest) is True
        script = (dirs["update"] / "_update.cmd").read_text()
        assert "/VERYSILENT" in script and "/SUPPRESSMSGBOXES" in script
        assert script.index(SETUP_NAME) < script.index("WarcraftLogsAnalyzer.exe")
        assert not (dirs["install"] / "_update.cmd").exists()
        assert not (dirs["update"] / "staged").exists()
        dirs["popen"].assert_called_once()

    def test_apply_refuses_a_tampered_installer(self, tmp_path, dirs):
        setup = dirs["update"] / SETUP_NAME
        setup.write_bytes(b"MZ installer")
        digest = hashlib.sha256(b"something else").hexdigest()
        with pytest.raises(UpdateVerificationError):
            apply_update(str(setup), digest)
        assert not (dirs["update"] / "_update.cmd").exists()
        dirs["popen"].assert_not_called()


class TestVersionTags:
    @pytest.mark.parametrize(
        ("tag", "parsed"),
        [("v4.5.0", (4, 5, 0)), ("4.6", (4, 6, 0)), ("v10.0.1", (10, 0, 1)), ("v5.0.0-rc1", None), ("", None)],
    )
    def test_parse(self, tag, parsed):
        assert updater._parse_version(tag) == parsed

    def test_prerelease_tag_is_ignored_not_a_crash(self, monkeypatch):
        resp = MagicMock()
        resp.json.return_value = {"tag_name": "v999.0.0-beta", "assets": RELEASE_ASSETS}
        with patch.object(updater.requests, "get", return_value=resp):
            assert updater.check_for_update(force=True) is None


class TestCheckCooldown:
    @pytest.fixture
    def config(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        monkeypatch.setattr(updater.paths, "get_config_path", lambda: path)
        return path

    def test_no_config_means_not_checked(self, config):
        assert updater._recently_checked() is False

    def test_recent_check_skips_the_network(self, config):
        config.write_text(json.dumps({"last_update_check": time.time()}))
        with patch.object(updater.requests, "get") as get:
            assert updater.check_for_update() is None
        get.assert_not_called()

    def test_old_or_unreadable_check_is_not_recent(self, config):
        config.write_text(json.dumps({"last_update_check": 0}))
        assert updater._recently_checked() is False
        config.write_text("{not json")
        assert updater._recently_checked() is False


def test_network_error_means_no_update():
    with patch.object(updater.requests, "get", side_effect=requests.ConnectionError("offline")):
        assert updater.check_for_update(force=True) is None


def test_newer_release_without_a_windows_file_is_not_offered(monkeypatch):
    monkeypatch.setattr(updater, "_save_check_timestamp", lambda: None)
    resp = MagicMock()
    resp.json.return_value = {"tag_name": "v999.0.0", "assets": RELEASE_ASSETS[3:]}
    with patch.object(updater.requests, "get", return_value=resp):
        assert updater.check_for_update(force=True) is None


def test_unwritable_script_folder_is_reported_and_unstaged(tmp_path, dirs, monkeypatch):
    zip_path = dirs["update"] / ZIP_NAME
    digest = make_update_zip(zip_path)
    monkeypatch.setattr(updater.paths, "get_install_dir", lambda: tmp_path / "missing")
    with pytest.raises(RuntimeError, match="Cannot write update script"):
        apply_update(str(zip_path), digest)
    assert not dirs["staged"].exists()
    dirs["popen"].assert_not_called()


class TestFailedSilentInstall:
    def test_script_logs_setup_and_keeps_it_when_it_fails(self, dirs):
        setup = dirs["update"] / SETUP_NAME
        script = updater.installer_update_script(str(setup), dirs["install"])
        assert '/LOG="' in script and updater.SETUP_LOG in script
        assert 'set "rc=%errorlevel%"' in script
        failed, succeeded = script.split(") else (")
        assert updater.FAILURE_MARKER in failed and "del" not in failed.split("if not")[-1]
        assert f'del /f /q "{str(setup).replace("/", chr(92))}"' in succeeded

    def test_failure_is_reported_once(self, dirs):
        (dirs["update"] / updater.FAILURE_MARKER).write_text("5\n")
        message = updater.take_update_failure()
        assert message is not None
        assert "exit code 5" in message and updater.SETUP_LOG in message
        assert updater.take_update_failure() is None

    def test_no_marker_means_no_failure(self, dirs):
        assert updater.take_update_failure() is None
