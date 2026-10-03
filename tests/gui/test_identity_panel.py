"""Settings' Discord account and raid era sections (phase 2.3)."""

import sqlite3

import pytest

pytest.importorskip("PySide6")

from wcl_app.identity import DiscordNotConfigured
from wcl_app.profiles import JsonProfileStore, ProfileService
from wcl_core.discord_auth import DiscordIdentity

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.gui.identity_panel import (
    NOT_LINKED,
    SIGN_IN,
    SIGN_OUT,
    TAG_RAIDS,
    IdentityPanel,
    linked_text,
    tagged_text,
)
from warcraftlogs_client.services import AppContext

TOAD = DiscordIdentity(id="1234", username="toad", global_name="Toad")


class FakeIdentity:
    """Stands in for IdentityService: no browser, no token file."""

    def __init__(self, linked=None, result=TOAD, error=None):
        self._linked = linked
        self.result = result
        self.error = error

    def current(self):
        return self._linked

    def is_linked(self):
        return self._linked is not None

    def link(self, *, open_browser=True, timeout=None):
        if self.error is not None:
            raise self.error
        self._linked = self.result
        return self.result

    def unlink(self):
        self._linked = None


@pytest.fixture
def profiles(tmp_path, build_analysis):
    path = str(tmp_path / "eras.db")
    with PerformanceDB(path) as db:
        db.import_raid(build_analysis(report_id="UntaggedRaid0000"))
    return ProfileService(JsonProfileStore(tmp_path / "profiles.json"), AppContext(config={}, db_path=path))


def _panel(qtbot, profiles, identity=None):
    panel = IdentityPanel(identity if identity is not None else FakeIdentity(), profiles)
    qtbot.addWidget(panel)
    return panel


def test_texts():
    assert linked_text("Toad") == "Linked to Toad"
    assert (tagged_text(0), tagged_text(1), tagged_text(2)) == (
        "Every stored raid already has its era",
        "Tagged 1 raid with their era",
        "Tagged 2 raids with their era",
    )


@pytest.mark.gui
class TestDiscordAccount:
    def test_starts_unlinked(self, qtbot, profiles):
        panel = _panel(qtbot, profiles)
        assert (panel.discord_status.text(), panel.discord_button.text()) == (NOT_LINKED, SIGN_IN)

    def test_shows_who_is_linked(self, qtbot, profiles):
        panel = _panel(qtbot, profiles, FakeIdentity(linked=TOAD))
        assert (panel.discord_status.text(), panel.discord_button.text()) == (linked_text("Toad"), SIGN_OUT)

    def test_signing_in_links_off_the_ui_thread(self, qtbot, profiles):
        panel = _panel(qtbot, profiles)
        with qtbot.waitSignal(panel._relay.linked):
            panel.discord_button.click()
        assert (panel.discord_status.text(), panel.discord_button.text()) == (linked_text("Toad"), SIGN_OUT)
        assert panel.discord_button.isEnabled()

    def test_a_failed_sign_in_says_why(self, qtbot, profiles):
        identity = FakeIdentity(error=DiscordNotConfigured("Set discord_client_id in config.json"))
        panel = _panel(qtbot, profiles, identity)
        with qtbot.waitSignal(panel._relay.failed):
            panel.discord_button.click()
        assert panel.discord_status.text() == "Set discord_client_id in config.json"
        assert panel.discord_button.text() == SIGN_IN and panel.discord_button.isEnabled()

    def test_signing_out_unlinks(self, qtbot, profiles):
        identity = FakeIdentity(linked=TOAD)
        panel = _panel(qtbot, profiles, identity)
        with qtbot.waitSignal(panel.status_message) as message:
            panel.discord_button.click()
        assert message.args == ["Signed out of Discord"]
        assert not identity.is_linked() and panel.discord_status.text() == NOT_LINKED


@pytest.mark.gui
class TestRaidEras:
    def test_tagging_fills_in_eras_once(self, qtbot, profiles):
        panel = _panel(qtbot, profiles)
        with qtbot.waitSignal(panel.eras_changed):
            panel.tag_button.click()
        qtbot.waitUntil(lambda: panel._tag_worker is None)
        assert panel.tag_status.text() == tagged_text(1)
        assert panel.tag_button.text() == TAG_RAIDS and panel.tag_button.isEnabled()

        changed: list[bool] = []
        panel.eras_changed.connect(lambda: changed.append(True))
        panel.tag_button.click()
        qtbot.waitUntil(lambda: panel._tag_worker is None and panel.tag_status.text() == tagged_text(0))
        assert changed == []  # nothing to tag, nothing to refresh

    def test_a_failed_pass_still_refreshes(self, qtbot, profiles, monkeypatch):
        """Each raid is saved as it is tagged, so a pass that fails part way may have changed some."""

        def broken():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(profiles, "backfill_eras", broken)
        panel = _panel(qtbot, profiles)
        with qtbot.waitSignal(panel.eras_changed):
            panel.tag_button.click()
        qtbot.waitUntil(lambda: panel._tag_worker is None)
        assert panel.tag_status.text() == "Tagging failed: database is locked"

    def test_a_saved_config_reaches_sign_in_and_tagging(self, qtbot, profiles):
        identity = FakeIdentity()
        identity.config = {}
        panel = _panel(qtbot, profiles, identity)
        panel.use_config({"discord_client_id": "42", "wcl_api_url": "https://fresh.warcraftlogs.com/api/v2/client"})
        assert identity.config["discord_client_id"] == "42"
        assert profiles.ctx.config["wcl_api_url"] == "https://fresh.warcraftlogs.com/api/v2/client"
