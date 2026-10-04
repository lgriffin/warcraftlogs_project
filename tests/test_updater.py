"""REQ-CORE-REL-001: the updater refuses to stage a zip whose SHA-256 does not match SHA256SUMS."""

import hashlib
import zipfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from warcraftlogs_client import updater
from warcraftlogs_client.updater import (
    UpdateInfo,
    UpdateVerificationError,
    apply_update,
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
