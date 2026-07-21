"""Tests for RaidsView widget using pytest-qt."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QComboBox, QLabel

from warcraftlogs_client.gui.raids_view import RaidsView


def _make_raids_view(qtbot):
    """Create a RaidsView with database calls patched out."""
    with (
        patch("warcraftlogs_client.gui.raids_view.PerformanceDB"),
        patch.object(RaidsView, "showEvent", lambda self, event: None),
    ):
        view = RaidsView()
    qtbot.addWidget(view)
    return view


@pytest.mark.gui
class TestRaidsView:
    def test_widget_creates_without_crashing(self, qtbot):
        view = _make_raids_view(qtbot)
        assert view is not None

    def test_has_title_label(self, qtbot):
        view = _make_raids_view(qtbot)
        labels = view.findChildren(QLabel)
        title_labels = [lbl for lbl in labels if lbl.text() == "Raids"]
        assert len(title_labels) == 1

    def test_has_boss_dropdown(self, qtbot):
        view = _make_raids_view(qtbot)
        assert isinstance(view._boss_combo, QComboBox)

    def test_has_status_message_signal(self, qtbot):
        view = _make_raids_view(qtbot)
        # Verify the signal exists and can be connected
        handler = MagicMock()
        view.status_message.connect(handler)
        view.status_message.emit("test")
        handler.assert_called_once_with("test")

    def test_has_open_raid_signal(self, qtbot):
        view = _make_raids_view(qtbot)
        handler = MagicMock()
        view.open_raid.connect(handler)
        view.open_raid.emit("report_123")
        handler.assert_called_once_with("report_123")

    def test_has_day_filter_checkboxes(self, qtbot):
        view = _make_raids_view(qtbot)
        assert len(view._boss_day_checkboxes) == 7

    def test_has_boss_table(self, qtbot):
        view = _make_raids_view(qtbot)
        assert view._boss_table is not None
        assert view._boss_table.columnCount() == 7
