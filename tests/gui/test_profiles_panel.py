"""Settings' raid profiles section (phase 5): profiles are edited here, not as raw config keys."""

import pytest

pytest.importorskip("PySide6")

from wcl_app.profiles import JsonProfileStore, ProfileService
from wcl_core.discord_auth import DiscordIdentity

from warcraftlogs_client.gui.profiles_panel import GUILD_NOT_A_NUMBER, NO_PROFILES, ProfilesPanel, describe
from warcraftlogs_client.services import AppContext


@pytest.fixture
def service(tmp_path):
    return ProfileService(JsonProfileStore(tmp_path / "profiles.json"), AppContext(config={}))


class LinkedAs:
    """Stands in for IdentityService with a Discord account already linked."""

    def __init__(self, identity):
        self._identity = identity

    def current(self):
        return self._identity


def _panel(qtbot, service, identity=None):
    panel = ProfilesPanel(service, identity)
    qtbot.addWidget(panel)
    return panel


def _shown(panel):
    return [panel.list.item(i).text() for i in range(panel.list.count())]


def test_describe_names_the_site_and_guild_when_the_profile_has_them(service):
    assert describe(service.create("Pond", game_version="fresh", guild_id=774065)) == "Pond (fresh, guild 774065)"
    assert describe(service.create("Lily")) == "Lily (default site)"


@pytest.mark.gui
class TestProfilesPanel:
    def test_with_no_profiles_it_says_how_to_start(self, qtbot, service):
        panel = _panel(qtbot, service)
        assert panel.empty.text() == NO_PROFILES
        assert not panel.list.isVisibleTo(panel) and panel.empty.isVisibleTo(panel)
        assert not panel.delete_button.isEnabled()

    def test_lists_the_saved_profiles(self, qtbot, service):
        service.create("TBC", game_version="fresh")
        panel = _panel(qtbot, service)
        assert _shown(panel) == ["TBC (fresh)"]
        assert panel.list.isVisibleTo(panel) and not panel.empty.isVisibleTo(panel)

    def test_adding_a_profile_saves_it_and_tells_the_switcher(self, qtbot, service):
        panel = _panel(qtbot, service)
        panel.name_input.setText("Classic Era")
        panel.version_input.setCurrentIndex(panel.version_input.findData("classic"))
        panel.guild_input.setText("12")
        with qtbot.waitSignal(panel.profiles_changed), qtbot.waitSignal(panel.status_message) as message:
            panel.add_button.click()
        saved = service.get("classic-era")
        assert (saved.game_version, saved.guild_id, saved.owner) == ("classic", 12, None)
        assert message.args == ["Added the Classic Era profile"]
        assert _shown(panel) == ["Classic Era (classic, guild 12)"]
        assert (panel.name_input.text(), panel.guild_input.text(), panel.version_input.currentData()) == ("", "", None)

    def test_a_blank_game_version_and_guild_keep_the_defaults(self, qtbot, service):
        panel = _panel(qtbot, service)
        panel.name_input.setText("Everything")
        panel.add_button.click()
        saved = service.get("everything")
        assert (saved.game_version, saved.guild_id) == (None, None)

    def test_a_guild_that_is_not_a_number_saves_nothing(self, qtbot, service):
        panel = _panel(qtbot, service)
        panel.name_input.setText("Pond")
        panel.guild_input.setText("toads")
        panel.add_button.click()
        assert panel.error.text() == GUILD_NOT_A_NUMBER
        assert service.list() == []

    def test_a_name_in_use_or_no_name_says_why(self, qtbot, service):
        service.create("Pond")
        panel = _panel(qtbot, service)
        panel.name_input.setText("pond")
        panel.add_button.click()
        assert "already exists" in panel.error.text()
        panel.name_input.setText("   ")
        panel.add_button.click()
        assert panel.error.text() == "A profile needs a name"
        assert len(service.list()) == 1

    def test_deleting_the_active_profile_goes_back_to_all_raids(self, qtbot, service):
        service.create("Pond", game_version="fresh", activate=True)
        panel = _panel(qtbot, service)
        panel.list.setCurrentRow(0)
        assert panel.delete_button.isEnabled()
        with qtbot.waitSignal(panel.profiles_changed), qtbot.waitSignal(panel.status_message) as message:
            panel.delete_button.click()
        assert message.args == ["Deleted Pond (fresh)"]
        assert service.list() == [] and service.active() is None
        assert service.ctx.profile is None
        assert panel.empty.isVisibleTo(panel)

    def test_a_profile_added_while_discord_is_linked_is_theirs(self, qtbot, service):
        panel = _panel(qtbot, service, LinkedAs(DiscordIdentity(id="1234", username="toad", global_name="Toad")))
        panel.name_input.setText("Pond")
        panel.add_button.click()
        assert service.get("pond").owner == "1234"
