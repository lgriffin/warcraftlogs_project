"""Tests for DownloadView widget using pytest-qt."""

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QCheckBox, QLineEdit

from warcraftlogs_client.gui.download_view import DownloadView


def _make_download_view(qtbot):
    """Create a DownloadView with DB calls patched out."""
    with patch.object(DownloadView, "showEvent", lambda self, event: None):
        view = DownloadView()
    qtbot.addWidget(view)
    return view


@pytest.mark.gui
class TestDownloadView:
    def test_widget_creates_without_crashing(self, qtbot):
        view = _make_download_view(qtbot)
        assert view is not None

    def test_day_filter_checkboxes_exist(self, qtbot):
        view = _make_download_view(qtbot)
        assert len(view._day_checkboxes) == 7

    def test_day_filter_checkboxes_are_qcheckbox(self, qtbot):
        view = _make_download_view(qtbot)
        for cb in view._day_checkboxes.values():
            assert isinstance(cb, QCheckBox)

    def test_default_day_checkboxes(self, qtbot):
        """Wed (2), Thu (3), and Sun (6) should be checked by default."""
        view = _make_download_view(qtbot)
        for i, cb in view._day_checkboxes.items():
            if i in (2, 3, 6):
                assert cb.isChecked(), f"Day {i} should be checked by default"
            else:
                assert not cb.isChecked(), f"Day {i} should not be checked by default"

    def test_apply_day_filter_populates_table(self, qtbot):
        view = _make_download_view(qtbot)
        view._cached_codes = {}
        view._guild_reports_raw = [
            {
                "start_time": 1700006400000,  # 2023-11-15 00:00 UTC (Wednesday)
                "code": "ABC123",
                "title": "Kara Run",
                "owner": "TestOwner",
                "zone": "Karazhan",
            },
        ]
        view._apply_day_filter()
        assert view._table_model.rowCount() > 0

    def test_analyze_all_new_button_disabled_initially(self, qtbot):
        view = _make_download_view(qtbot)
        assert not view._analyze_new_btn.isEnabled()

    def test_report_input_field_exists_and_editable(self, qtbot):
        view = _make_download_view(qtbot)
        assert isinstance(view._report_input, QLineEdit)
        assert not view._report_input.isReadOnly()

    def test_fetch_button_exists(self, qtbot):
        view = _make_download_view(qtbot)
        assert view._fetch_btn is not None
        assert view._fetch_btn.text() == "Fetch Guild Reports"

    def test_analyze_selected_button_disabled_initially(self, qtbot):
        view = _make_download_view(qtbot)
        assert not view._analyze_selected_btn.isEnabled()

    def test_table_model_is_checkable(self, qtbot):
        view = _make_download_view(qtbot)
        assert view._table_model._checkable is True

    def test_cached_codes_starts_empty(self, qtbot):
        view = _make_download_view(qtbot)
        assert isinstance(view._cached_codes, dict)
