"""Settings' Toads Hub section (phase 4): paste the bot's code, publish profiles, unlink."""

import pytest

pytest.importorskip("PySide6")

from warcraftlogs_client.services.profiles import MemoryProfileStore
from wcl_core.hub import HubLinkStore
from wcl_core.testing import FakeHub

from warcraftlogs_client.gui.hub_panel import LINK, NOT_LINKED, PUBLISH, UNLINK, HubPanel, linked_text
from warcraftlogs_client.services import BridgeService, Profile, ProfileService, ProfileSet

HUB = "https://hub.toads.test"


@pytest.fixture
def hub(monkeypatch):
    monkeypatch.setenv("TOADS_HUB_URL", HUB)
    fake = FakeHub(HUB)
    with fake.install():
        yield fake


def _panel(qtbot, tmp_path):
    profiles = ProfileService(MemoryProfileStore(ProfileSet([Profile("tbc", "TBC")], active="tbc")))
    panel = HubPanel(BridgeService(HubLinkStore(tmp_path / "hub_link.json"), profiles=profiles))
    qtbot.addWidget(panel)
    return panel


@pytest.mark.gui
class TestHubPanel:
    def test_starts_unlinked_with_a_code_box(self, qtbot, tmp_path):
        panel = _panel(qtbot, tmp_path)
        assert panel.status.text() == NOT_LINKED and panel.link_button.text() == LINK
        assert not panel.code_input.isHidden() and panel.publish_button.isHidden()

    def test_a_code_links_off_the_ui_thread_and_publishes(self, qtbot, tmp_path, hub):
        panel = _panel(qtbot, tmp_path)
        panel.code_input.setText(hub.issue_code("42", "toadlord", "Leigh"))
        with qtbot.waitSignal(panel.status_message, timeout=5000) as said:
            panel.link_button.click()
        assert said.args == ["Linked to the Toads Hub as Leigh"]
        assert panel.status.text() == linked_text("Leigh", HUB) and panel.link_button.text() == UNLINK
        assert panel.code_input.isHidden() and panel.publish_button.text() == PUBLISH
        assert hub.load("42")["active"] == "tbc"

        with qtbot.waitSignal(panel.status_message, timeout=5000) as said:
            panel.publish_button.click()
        assert said.args == ["Raid profiles published to the Toads Hub"]
        with qtbot.waitSignal(panel.status_message, timeout=5000) as said:
            panel.link_button.click()
        assert said.args == ["Hub link forgotten"] and panel.status.text() == NOT_LINKED

    def test_a_bad_code_says_why(self, qtbot, tmp_path, hub):
        panel = _panel(qtbot, tmp_path)
        panel.link_button.click()  # nothing typed: a hint, no request
        assert "Code from the Toads bot" in panel.status.text() and hub.requests == []
        panel.code_input.setText("ZZZZ-ZZZZ")
        with qtbot.waitSignal(panel.status_message, timeout=5000) as said:
            panel.link_button.click()
        assert said.args == ["Toads Hub link failed"] and "did not accept that code" in panel.status.text()
        assert panel.link_button.isEnabled() and panel.link_button.text() == LINK

    def test_a_saved_config_reaches_the_bridge(self, qtbot, tmp_path):
        panel = _panel(qtbot, tmp_path)
        panel.use_config({"toads_hub_url": "https://toads.example"})
        assert panel._bridge.config == {"toads_hub_url": "https://toads.example"}
