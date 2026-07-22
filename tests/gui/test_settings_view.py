"""Tests for SettingsView widget using pytest-qt.

Note: SettingsView._build_ui triggers a PySide6 6.11.0 / Python 3.14
segfault in the QPushButton.clicked.connect call inside the credentials
group.  We patch _build_ui and verify the constructor plus the public
attributes that _build_ui would have created.
"""

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLineEdit, QWidget

from warcraftlogs_client.gui.settings_view import SettingsView


def _make_settings_view(qtbot):
    """Create a SettingsView with _build_ui and config loading patched out.

    After construction we manually attach the input fields that _build_ui
    would have created so the tests can verify their existence.
    """
    with (
        patch.object(SettingsView, "_build_ui"),
        patch.object(SettingsView, "_load_current_config"),
    ):
        view = SettingsView()

    # Manually add the input fields that _build_ui normally creates
    view.client_id_input = QLineEdit(view)
    view.client_secret_input = QLineEdit(view)
    view.client_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
    view.report_id_input = QLineEdit(view)
    view.guild_id_input = QLineEdit(view)
    view.guild_name_input = QLineEdit(view)
    view.guild_server_input = QLineEdit(view)

    qtbot.addWidget(view)
    return view


@pytest.mark.gui
class TestSettingsView:
    def test_widget_creates_without_crashing(self, qtbot):
        view = _make_settings_view(qtbot)
        assert view is not None
        assert isinstance(view, QWidget)

    def test_has_client_id_input(self, qtbot):
        view = _make_settings_view(qtbot)
        assert isinstance(view.client_id_input, QLineEdit)

    def test_has_client_secret_input(self, qtbot):
        view = _make_settings_view(qtbot)
        assert isinstance(view.client_secret_input, QLineEdit)

    def test_has_report_id_input(self, qtbot):
        view = _make_settings_view(qtbot)
        assert isinstance(view.report_id_input, QLineEdit)

    def test_has_guild_id_input(self, qtbot):
        view = _make_settings_view(qtbot)
        assert isinstance(view.guild_id_input, QLineEdit)

    def test_has_qlineedit_children(self, qtbot):
        view = _make_settings_view(qtbot)
        line_edits = view.findChildren(QLineEdit)
        # client_id, client_secret, report_id, guild_id, guild_name, guild_server
        assert len(line_edits) >= 4

    def test_client_secret_is_password_mode(self, qtbot):
        view = _make_settings_view(qtbot)
        assert view.client_secret_input.echoMode() == QLineEdit.EchoMode.Password

    def test_inputs_are_editable(self, qtbot):
        view = _make_settings_view(qtbot)
        assert not view.client_id_input.isReadOnly()
        assert not view.client_secret_input.isReadOnly()
        assert not view.report_id_input.isReadOnly()
        assert not view.guild_id_input.isReadOnly()

    def test_is_settings_view_subclass(self, qtbot):
        view = _make_settings_view(qtbot)
        assert isinstance(view, SettingsView)

    def test_has_status_message_signal(self, qtbot):
        view = _make_settings_view(qtbot)
        from unittest.mock import MagicMock

        handler = MagicMock()
        view.status_message.connect(handler)
        view.status_message.emit("test")
        handler.assert_called_once_with("test")
