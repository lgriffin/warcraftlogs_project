"""Tests for the Player Page view using pytest-qt."""

from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from warcraftlogs_client.gui.player_page_view import PlayerPageView
from warcraftlogs_client.services.lineage import CharacterLineage, Spread
from warcraftlogs_client.services.player_page import NEW, ON_PAGE, PlayerLog, PlayerPageData, PlayerRef


def _make_view(qtbot):
    with patch.object(PlayerPageView, "_prefill_from_config", lambda self: None):
        view = PlayerPageView()
    qtbot.addWidget(view)
    return view


@pytest.mark.gui
class TestPlayerPageView:
    def test_actions_disabled_until_player_loaded(self, qtbot):
        view = _make_view(qtbot)
        assert not view._add_new_btn.isEnabled()
        assert view._discover_btn.isEnabled()

    def test_invalid_input_reports_error(self, qtbot):
        view = _make_view(qtbot)
        with qtbot.waitSignal(view.status_message) as blocker:
            view._discover()
        assert "not a valid character name" in blocker.args[0]
        assert view._worker is None

    def test_discovery_results_fill_tables(self, qtbot):
        view = _make_view(qtbot)
        view._player = PlayerRef.create("Hadur", "spineshatter", "eu")
        found = [
            PlayerLog(code="A" * 16, title="Kara", start_time=1_700_000_000_000, status=NEW),
            PlayerLog(code="B" * 16, title="Gruul", status=ON_PAGE, imported=True),
            PlayerLog(code="C" * 16, title="Hidden", status="dismissed"),
        ]
        view._on_discovered(found, PlayerPageData(player=view._player, logs=[found[1]]))

        assert view._found_table.rowCount() == 2
        assert view._page_table.rowCount() == 1
        assert view._page_table.item(0, 6).text() == "B" * 16
        assert "1 new" in view._summary.text()
        assert view._add_new_btn.isEnabled()

    def test_add_all_new_only_sends_new_reports(self, qtbot):
        view = _make_view(qtbot)
        view._player = PlayerRef.create("Hadur", "spineshatter", "eu")
        view._discovered = [
            PlayerLog(code="A" * 16, title="Kara", status=NEW),
            PlayerLog(code="B" * 16, title="Gruul", status=ON_PAGE),
        ]
        with patch.object(view, "_start_add") as start:
            view._add_all_new()
        start.assert_called_once_with(["A" * 16])

    def test_open_imported_row_emits_report(self, qtbot):
        view = _make_view(qtbot)
        view._player = PlayerRef.create("Hadur", "spineshatter", "eu")
        view._on_discovered(
            [PlayerLog(code="B" * 16, title="Gruul", status=ON_PAGE, imported=True)],
            PlayerPageData(player=view._player),
        )
        with qtbot.waitSignal(view.open_report) as blocker:
            view._open_row(view._found_table, 0)
        assert blocker.args == ["B" * 16]

    def test_lineage_and_role_override_shown(self, qtbot):
        view = _make_view(qtbot)
        view._player = PlayerRef.create("Hadur", "spineshatter", "eu")
        lineage = CharacterLineage(
            character="Hadur",
            raids=3,
            metrics=[Spread.of("Healing", [100.0, 200.0, 300.0], "healer")],
            casts=[Spread.of("Flash Heal", [10.0, 20.0, 30.0], "healer")],
            consumables=[Spread.of("Super Mana Potion", [0.0, 2.0, 4.0])],
        )
        page = PlayerPageData(
            player=view._player,
            lineage=lineage,
            role_overrides=[{"character_name": "Hadur", "report_id": "", "role": "healer"}],
        )
        view._on_discovered([], page)

        table = view._lineage_table
        assert table.rowCount() == 6  # three section headers + three rows
        assert table.item(0, 0).text() == "Per raid"
        assert [table.item(1, c).text() for c in range(6)] == ["Healing", "healer", "100", "200.0", "300", "3"]
        assert view._tabs.tabText(1) == "Lineage (3 raids)"
        assert view._role_combo.currentText() == "healer"

    def test_apply_detected_clears_override(self, qtbot):
        view = _make_view(qtbot)
        view._player = PlayerRef.create("Hadur", "spineshatter", "eu")
        view._role_combo.setCurrentText("Detected")
        with patch("warcraftlogs_client.gui.player_page_view._RoleWorker") as worker_cls:
            view._apply_role()
        worker_cls.assert_called_once_with("Hadur", None, view)
        worker_cls.return_value.start.assert_called_once()
