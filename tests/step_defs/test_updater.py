"""Step definitions for the verified-update feature (REQ-CORE-REL-001)."""

from unittest.mock import MagicMock, patch

from pytest_bdd import given, parsers, scenarios, then, when

from tests.test_updater import ZIP_NAME, make_info, make_update_zip, tamper
from warcraftlogs_client import updater
from warcraftlogs_client.updater import UpdateVerificationError, apply_update, fetch_expected_sha256

scenarios("updater.feature")


def _release(tmp_path, monkeypatch) -> dict:
    install, update = tmp_path / "install", tmp_path / "update"
    install.mkdir()
    update.mkdir()
    monkeypatch.setattr(updater.paths, "get_install_dir", lambda: install)
    monkeypatch.setattr(updater.paths, "get_update_dir", lambda: update)
    popen = MagicMock()
    monkeypatch.setattr(updater.subprocess, "Popen", popen)

    zip_path = tmp_path / ZIP_NAME
    digest = make_update_zip(zip_path)
    return {
        "info": make_info(),
        "sums_text": f"{'0' * 64}  WarcraftLogsAnalyzer-Setup.exe\n{digest}  {ZIP_NAME}\n",
        "zip_path": zip_path,
        "install": install,
        "staged": update / "staged",
        "popen": popen,
    }


@given("a release whose SHA256SUMS lists the update zip", target_fixture="update_ctx")
def release_with_sums(tmp_path, monkeypatch):
    return _release(tmp_path, monkeypatch)


@given("a release that publishes no SHA256SUMS", target_fixture="update_ctx")
def release_without_sums(tmp_path, monkeypatch):
    ctx = _release(tmp_path, monkeypatch)
    ctx["info"] = make_info(checksums_url="")
    return ctx


@given("the downloaded update zip has been tampered with")
def tampered_zip(update_ctx):
    tamper(update_ctx["zip_path"])


@when("the user installs the update", target_fixture="install_result")
def install_update(update_ctx):
    """The UpdateDownloader + UpdateDialog flow: resolve the expected digest, then apply."""
    sums_resp = MagicMock(text=update_ctx.get("sums_text", ""))
    sums_resp.raise_for_status.return_value = None
    try:
        with patch.object(updater.requests, "get", return_value=sums_resp):
            expected = fetch_expected_sha256(update_ctx["info"])
        return {"ok": apply_update(str(update_ctx["zip_path"]), expected), "error": None}
    except UpdateVerificationError as e:
        return {"ok": False, "error": e}


@then(parsers.parse('the update should be refused with a message containing "{text}"'))
def refused(install_result, text):
    assert install_result["error"] is not None
    assert text in str(install_result["error"])


@then("nothing should be staged or launched")
def nothing_staged(update_ctx):
    assert not update_ctx["staged"].exists()
    assert not (update_ctx["install"] / "_update.cmd").exists()
    update_ctx["popen"].assert_not_called()


@then("the update should be staged and the swap script launched")
def staged(install_result, update_ctx):
    assert install_result == {"ok": True, "error": None}
    assert (update_ctx["staged"] / "WarcraftLogsAnalyzer" / "WarcraftLogsAnalyzer.exe").exists()
    assert (update_ctx["install"] / "_update.cmd").exists()
    update_ctx["popen"].assert_called_once()
