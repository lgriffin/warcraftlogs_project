"""REQ-CORE-REL-001: UpdateDownloader verifies the zip against SHA256SUMS before reporting success."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")

from tests.test_updater import ZIP_NAME, make_info, make_update_zip, tamper
from warcraftlogs_client import updater
from warcraftlogs_client.updater import UpdateDownloader

pytestmark = [pytest.mark.gui, pytest.mark.security]


def _responses(sums_text: str, zip_bytes: bytes):
    sums = MagicMock(text=sums_text)
    sums.raise_for_status.return_value = None
    download = MagicMock(headers={"content-length": str(len(zip_bytes))})
    download.raise_for_status.return_value = None
    download.iter_content.return_value = [zip_bytes]

    def fake_get(url, **_kwargs):
        return sums if url == make_info().checksums_url else download

    return fake_get


def _run(qtbot, tmp_path, monkeypatch, info, zip_bytes, sums_text):
    monkeypatch.setattr(updater.paths, "get_update_dir", lambda: tmp_path)
    downloader = UpdateDownloader(info)
    finished, errors = [], []
    downloader.finished.connect(finished.append)
    downloader.error.connect(errors.append)
    with patch.object(updater.requests, "get", side_effect=_responses(sums_text, zip_bytes)):
        downloader.run()  # synchronous: exercise the thread body directly
    return downloader, finished, errors


def test_verified_download_reports_success(qtbot, tmp_path, monkeypatch):
    source = tmp_path / "src.zip"
    digest = make_update_zip(source)
    downloader, finished, errors = _run(
        qtbot, tmp_path, monkeypatch, make_info(), source.read_bytes(), f"{digest}  {ZIP_NAME}\n"
    )
    assert errors == []
    assert len(finished) == 1
    assert downloader.expected_sha256 == digest


def test_tampered_download_refused_and_deleted(qtbot, tmp_path, monkeypatch):
    source = tmp_path / "src.zip"
    digest = make_update_zip(source)
    tamper(source)
    _, finished, errors = _run(
        qtbot, tmp_path, monkeypatch, make_info(), source.read_bytes(), f"{digest}  {ZIP_NAME}\n"
    )
    assert finished == []
    assert len(errors) == 1
    assert "does not match the SHA-256" in errors[0]
    assert not (tmp_path / "WarcraftLogsAnalyzer-v9.9.9.zip").exists()


def test_release_without_sha256sums_refused_before_download(qtbot, tmp_path, monkeypatch):
    source = tmp_path / "src.zip"
    make_update_zip(source)
    _, finished, errors = _run(qtbot, tmp_path, monkeypatch, make_info(checksums_url=""), source.read_bytes(), "")
    assert finished == []
    assert len(errors) == 1
    assert "does not publish a SHA256SUMS" in errors[0]
