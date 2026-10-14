"""The command palette lists views and, given a raid index, raids opened at the tab a query names."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from warcraftlogs_client.gui.command_palette import CommandPalette
from warcraftlogs_client.services import ReportIndex

KARA = "KaraKaraKaraKar1"
RAIDS = [{"report_id": KARA, "title": "Kara Wednesday", "zone": "Karazhan", "raid_date": "2026-09-30 19:30:00"}]


def _rows(palette):
    return [palette._list.item(i).text() for i in range(palette._list.count())]


@pytest.fixture
def palette(qtbot):
    widget = CommandPalette(reports=ReportIndex(RAIDS))
    qtbot.addWidget(widget)
    return widget


@pytest.mark.gui
class TestCommandPalette:
    def test_lists_every_command_before_typing(self, palette):
        assert "Home    Ctrl+1" in _rows(palette)
        assert not any(row.startswith("Raid  >") for row in _rows(palette))

    def test_a_raid_and_tab_query_lists_the_raid_at_that_tab(self, palette):
        palette._input.setText("kara healing")
        assert _rows(palette) == ["Raid  >  2026-09-30  Kara Wednesday  Karazhan  >  Healers"]

    def test_enter_opens_the_raid_at_the_tab(self, qtbot, palette):
        palette._input.setText("kara pots")
        with qtbot.waitSignal(palette.open_report) as signal:
            qtbot.keyClick(palette, Qt.Key.Key_Return)
        assert signal.args == [KARA, "Consumables"]

    def test_a_raid_without_a_tab_word_opens_at_its_default_tab(self, qtbot, palette):
        palette._input.setText("karazhan")
        with qtbot.waitSignal(palette.open_report) as signal:
            palette._on_activated(palette._list.item(0))
        assert signal.args == [KARA, ""]

    def test_commands_still_navigate(self, qtbot, palette):
        palette._input.setText("settings")
        with qtbot.waitSignal(palette.navigate) as signal:
            qtbot.keyClick(palette, Qt.Key.Key_Return)
        assert signal.args == ["settings"]

    def test_a_link_to_an_unstored_report_offers_to_analyze_it(self, qtbot, palette):
        palette._input.setText("https://fresh.warcraftlogs.com/reports/NewRaidNewRaid12")
        assert _rows(palette) == ["Analyze report NewRaidNewRaid12"]
        with qtbot.waitSignal(palette.analyze_report) as signal:
            qtbot.keyClick(palette, Qt.Key.Key_Return)
        assert signal.args == ["NewRaidNewRaid12"]

    def test_without_an_index_only_commands_are_searched(self, qtbot):
        widget = CommandPalette()
        qtbot.addWidget(widget)
        widget._input.setText("healing")
        assert _rows(widget) == []
