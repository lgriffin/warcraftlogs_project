"""Tests for RaidAnalysisWidget using pytest-qt."""


import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QTabWidget

from warcraftlogs_client.gui.raid_analysis_widget import RaidAnalysisWidget


@pytest.mark.gui
class TestRaidAnalysisWidget:
    def test_widget_creates_with_sample_analysis(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        assert widget is not None

    def test_title_label_shows_raid_title(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        title_text = widget._title_label.text()
        assert "Karazhan Full Clear" in title_text

    def test_back_button_exists_when_show_back_true(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis, show_back=True)
        qtbot.addWidget(widget)
        back_buttons = [
            btn for btn in widget.findChildren(QPushButton)
            if btn.text() == "< Back"
        ]
        assert len(back_buttons) == 1

    def test_back_button_absent_when_show_back_false(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis, show_back=False)
        qtbot.addWidget(widget)
        back_buttons = [
            btn for btn in widget.findChildren(QPushButton)
            if btn.text() == "< Back"
        ]
        assert len(back_buttons) == 0

    def test_delete_button_exists_when_show_delete_true(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis, show_delete=True)
        qtbot.addWidget(widget)
        delete_buttons = [
            btn for btn in widget.findChildren(QPushButton)
            if btn.text() == "Delete"
        ]
        assert len(delete_buttons) == 1

    def test_delete_button_hidden_when_show_delete_false(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis, show_delete=False)
        qtbot.addWidget(widget)
        delete_buttons = [
            btn for btn in widget.findChildren(QPushButton)
            if btn.text() == "Delete"
        ]
        assert len(delete_buttons) == 0

    def test_refresh_button_exists_and_enabled(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        assert widget._refresh_btn is not None
        assert widget._refresh_btn.isEnabled()
        assert widget._refresh_btn.text() == "Refresh"

    def test_tab_widget_has_expected_tabs(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        tabs = widget._tabs
        assert isinstance(tabs, QTabWidget)

        tab_names = [tabs.tabText(i) for i in range(tabs.count())]
        for expected in ["Healers", "Tanks", "Melee DPS", "Ranged DPS"]:
            assert expected in tab_names, f"Expected tab '{expected}' not found in {tab_names}"

    def test_consumables_tab_exists(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        tab_names = [widget._tabs.tabText(i) for i in range(widget._tabs.count())]
        assert "Consumables" in tab_names

    def test_request_back_signal_on_back_click(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis, show_back=True)
        qtbot.addWidget(widget)
        back_btn = next(
            btn for btn in widget.findChildren(QPushButton)
            if btn.text() == "< Back"
        )
        with qtbot.waitSignal(widget.request_back, timeout=1000):
            qtbot.mouseClick(back_btn, Qt.MouseButton.LeftButton)

    def test_composition_tab_exists(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        tab_names = [widget._tabs.tabText(i) for i in range(widget._tabs.count())]
        assert "Composition" in tab_names

    def test_cast_efficiency_tab_exists(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        tab_names = [widget._tabs.tabText(i) for i in range(widget._tabs.count())]
        assert "Cast Efficiency" in tab_names

    def test_title_includes_composition_counts(self, qtbot, sample_analysis):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        title_text = widget._title_label.text()
        # Should include tank/healer/melee/ranged counts
        assert "1T" in title_text
        assert "1H" in title_text
        assert "1M" in title_text
        assert "1R" in title_text
