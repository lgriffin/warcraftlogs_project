"""First-run setup window: check the API keys, find the guild, save both (``wcl_app.onboarding`` underneath)."""

import pytest

pytest.importorskip("PySide6")

from warcraftlogs_client.services.onboarding import KEYS_URL, MemoryConfigStore
from wcl_core.testing import FakeWarcraftLogs, status

from warcraftlogs_client.gui.setup_wizard import (
    CHECKING,
    KEYS_OK,
    GuildFinderDialog,
    SetupWizard,
    found_text,
)
from warcraftlogs_client.services import GuildMatch, OnboardingService

AMICABLE = {
    "id": 774065,
    "name": "Amicable",
    "server": {"name": "Gehennas", "slug": "gehennas", "region": {"slug": "EU"}},
}
FRESH_API = "https://fresh.warcraftlogs.com/api/v2/client"
TEMPLATE = {
    "client_id": "YOUR_CLIENT_ID_HERE",
    "client_secret": "YOUR_CLIENT_SECRET_HERE",
    "report_id": "YOUR_DEFAULT_REPORT_ID",
    "wcl_api_url": FRESH_API,
}


@pytest.fixture
def wcl():
    fake = FakeWarcraftLogs().answer("guildData", {"guildData": {"guild": AMICABLE}})
    with fake.install():
        yield fake


def _wizard(qtbot, config=None, opened=None):
    store = MemoryConfigStore(TEMPLATE if config is None else config)
    wizard = SetupWizard(OnboardingService(store), open_url=(opened if opened is not None else []).append)
    qtbot.addWidget(wizard)
    return wizard, store


def _check_keys(qtbot, wizard, client_id="abc", secret="xyz"):  # noqa: S107 - a fake key
    wizard.client_id_input.setText(client_id)
    wizard.secret_input.setText(secret)
    wizard.next_button.click()
    qtbot.waitUntil(lambda: wizard.next_button.text() != CHECKING, timeout=5000)


@pytest.mark.gui
class TestSetupWizard:
    def test_starts_on_the_keys_step_without_the_template_stand_ins(self, qtbot):
        opened = []
        wizard, _ = _wizard(qtbot, opened=opened)
        assert wizard.pages.currentIndex() == SetupWizard.KEYS
        assert wizard.client_id_input.text() == "" and wizard.secret_input.text() == ""
        assert not wizard.later_button.isHidden() and wizard.back_button.isHidden()
        wizard.open_keys_button.click()
        assert opened == [KEYS_URL]
        assert wizard.redirect_label.text() == "http://localhost:8764/callback"

    def test_saved_keys_are_filled_in(self, qtbot):
        wizard, _ = _wizard(qtbot, config={"client_id": "abc", "client_secret": "xyz"})
        assert wizard.client_id_input.text() == "abc" and wizard.secret_input.text() == "xyz"

    def test_the_secret_can_be_shown(self, qtbot):
        wizard, _ = _wizard(qtbot)
        assert wizard.secret_input.echoMode() == wizard.secret_input.EchoMode.Password
        wizard.show_secret_button.click()
        assert wizard.secret_input.echoMode() == wizard.secret_input.EchoMode.Normal

    def test_refused_keys_stay_on_the_keys_step_and_say_why(self, qtbot, wcl):
        wcl.token(status(401))
        wizard, store = _wizard(qtbot)
        _check_keys(qtbot, wizard)
        assert wizard.pages.currentIndex() == SetupWizard.KEYS
        assert "did not accept" in wizard.keys_status.text()
        assert store.config == TEMPLATE

    def test_good_keys_then_a_guild_link_save_both(self, qtbot, wcl):
        wizard, store = _wizard(qtbot)
        saved = []
        wizard.saved.connect(saved.append)
        _check_keys(qtbot, wizard)
        assert wizard.pages.currentIndex() == SetupWizard.GUILD and wizard.keys_status.text() == KEYS_OK
        assert wizard.next_button.text() == "Finish" and not wizard.next_button.isEnabled()

        wizard.finder.query_input.setText("https://fresh.warcraftlogs.com/guild/id/774065")
        wizard.finder.find_button.click()
        qtbot.waitUntil(lambda: wizard.finder.guild is not None, timeout=5000)
        guild = GuildMatch(774065, "Amicable", "Gehennas", "eu", "fresh")
        assert wizard.finder.result.text() == found_text(guild) and wizard.next_button.isEnabled()

        wizard.next_button.click()
        assert saved == ["Setup saved: imports now come from Amicable on Gehennas (EU)"]
        assert store.config["client_id"] == "abc" and store.config["client_secret"] == "xyz"
        assert store.config["guild_id"] == 774065 and store.config["report_id"] == ""

    def test_a_failed_search_says_why_and_finish_waits(self, qtbot, wcl):
        wizard, _ = _wizard(qtbot)
        _check_keys(qtbot, wizard)
        wizard.finder.query_input.setText("Amicable")  # a name without a server
        wizard.finder.find_button.click()
        qtbot.waitUntil(lambda: wizard.finder.find_button.isEnabled(), timeout=5000)
        assert "server and region" in wizard.finder.result.text() and not wizard.next_button.isEnabled()

    def test_skip_keeps_the_keys_without_a_guild(self, qtbot, wcl):
        wizard, store = _wizard(qtbot)
        saved = []
        wizard.saved.connect(saved.append)
        _check_keys(qtbot, wizard)
        wizard.skip_button.click()
        assert saved == ["Setup saved: API keys kept"]
        assert store.config["client_id"] == "abc" and "guild_id" not in store.config

    def test_back_returns_to_the_keys(self, qtbot, wcl):
        wizard, _ = _wizard(qtbot)
        _check_keys(qtbot, wizard)
        wizard.back_button.click()
        assert wizard.pages.currentIndex() == SetupWizard.KEYS and wizard.next_button.text() == "Check keys"

    def test_set_up_later_saves_nothing(self, qtbot):
        wizard, store = _wizard(qtbot)
        wizard.later_button.click()
        assert store.config == TEMPLATE


@pytest.mark.gui
class TestGuildFinderDialog:
    def test_finds_a_guild_by_name_on_the_chosen_site(self, qtbot, wcl):
        service = OnboardingService(MemoryConfigStore({"client_id": "abc", "client_secret": "xyz"}))
        dlg = GuildFinderDialog(service, lambda: ("abc", "xyz"))
        qtbot.addWidget(dlg)
        assert not dlg.use_button.isEnabled()
        dlg.finder.query_input.setText("Amicable")
        dlg.finder.server_input.setText("Gehennas")
        dlg.finder.site_combo.setCurrentIndex(dlg.finder.site_combo.findData("classic"))
        dlg.finder.find_button.click()
        qtbot.waitUntil(lambda: dlg.guild is not None, timeout=5000)
        assert dlg.use_button.isEnabled() and dlg.guild.game_version == "classic"
        assert wcl.queries[0].url.startswith("https://classic.")
        assert wcl.queries[0].variables == {"name": "Amicable", "serverSlug": "gehennas", "serverRegion": "eu"}
        assert service.guild_settings(dlg.guild)["wcl_api_url"] == "https://classic.warcraftlogs.com/api/v2/client"
