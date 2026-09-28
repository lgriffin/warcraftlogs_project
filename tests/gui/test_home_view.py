"""Tests for the customisable Home view using pytest-qt."""

from datetime import datetime

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidget, QPushButton, QTableWidget

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.gui.home_view import CustomiseHomeDialog, HomeView
from warcraftlogs_client.services import HomeLayout, HomeService
from warcraftlogs_client.services.home import CATALOGUE, MemoryLayoutStore

NOW = datetime(2023, 11, 20, 12, 0)


@pytest.fixture
def service(tmp_path, sample_analysis):
    path = str(tmp_path / "home.db")
    with PerformanceDB(path) as db:
        db.import_raid(sample_analysis)
    return HomeService(lambda: PerformanceDB(path), MemoryLayoutStore(), now=lambda: NOW)


@pytest.fixture
def view(qtbot, service):
    v = HomeView(service)
    qtbot.addWidget(v)
    return v


def _card(view, widget_id):
    return next(c for c in view.cards if c.widget_id == widget_id)


@pytest.mark.gui
class TestHomeView:
    def test_default_page_draws_a_card_per_default_widget(self, view, service):
        view.show_page(service.page())
        assert [c.widget_id for c in view.cards] == list(HomeLayout.default().widgets)

    def test_every_catalogue_widget_renders(self, view, service):
        view.show_page(service.page(HomeLayout.of(s.id for s in CATALOGUE)))
        assert len(view.cards) == len(CATALOGUE)

    def test_empty_layout_shows_a_hint(self, view, service):
        view.show_page(service.page(HomeLayout(())))
        assert view.cards == []
        texts = [w.text() for w in view.findChildren(QLabel)]
        assert any("Customise" in t for t in texts)

    def test_table_rows_open_the_character(self, qtbot, view, service):
        view.show_page(service.page(HomeLayout.of(["top_damage"])))
        table = _card(view, "top_damage").findChild(QTableWidget)
        assert table.rowCount() == 1 and table.item(0, 1).text() == "StabbyRogue"
        with qtbot.waitSignal(view.open_character) as blocker:
            table.cellDoubleClicked.emit(0, 1)
        assert blocker.args == ["StabbyRogue"]

    def test_recent_raid_opens_the_raid(self, qtbot, view, service):
        view.show_page(service.page(HomeLayout.of(["recent_raids"])))
        lst = _card(view, "recent_raids").findChild(QListWidget)
        with qtbot.waitSignal(view.open_raid) as blocker:
            lst.itemDoubleClicked.emit(lst.item(0))
        assert blocker.args == ["gui_test_001"]

    def test_quick_action_runs_its_command(self, qtbot, view, service):
        view.show_page(service.page(HomeLayout.of(["quick_actions"])))
        btn = _card(view, "quick_actions").findChild(QPushButton, "action:raids.download")
        with qtbot.waitSignal(view.run_action) as blocker:
            qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
        assert blocker.args == ["raids.download"]

    def test_player_page_link_carries_the_character(self, qtbot, view):
        from warcraftlogs_client.services.home import PLAYER_PAGE, Link

        with qtbot.waitSignal(view.open_player_page) as blocker:
            view.follow(Link(PLAYER_PAGE, {"name": "Hadur", "server": "Spineshatter", "region": "eu"}))
        assert blocker.args == ["Hadur", "Spineshatter", "eu"]

    def test_hiding_a_widget_saves_the_layout(self, view, service, monkeypatch):
        monkeypatch.setattr(view, "refresh", lambda: None)
        view.hide_widget("attendance")
        assert "attendance" not in service.layout().widgets
        assert service.layout().widgets[0] == "quick_actions"

    def test_failed_widget_shows_its_error(self, view, service):
        page = service.page(HomeLayout.of(["guild_snapshot"]))
        page.widgets[0].error = "database is locked"
        view.show_page(page)
        texts = [w.text() for w in _card(view, "guild_snapshot").findChildren(QLabel)]
        assert any("database is locked" in t for t in texts)

    def test_refresh_loads_in_the_background(self, qtbot, view):
        with qtbot.waitSignal(view.status_message, timeout=5000) as blocker:
            view.refresh()
        assert blocker.args == ["Home loaded"]
        qtbot.waitUntil(lambda: view._refresh_btn.isEnabled(), timeout=5000)
        assert len(view.cards) == len(HomeLayout.default().widgets)


@pytest.mark.gui
class TestCustomiseDialog:
    def test_lists_shown_widgets_first_then_the_rest_unticked(self, qtbot):
        dialog = CustomiseHomeDialog(list(CATALOGUE), HomeLayout.of(["attendance", "last_raid"]))
        qtbot.addWidget(dialog)
        assert dialog.chosen() == ["attendance", "last_raid"]
        assert dialog.list.count() == len(CATALOGUE)

    def test_reorder_and_tick(self, qtbot):
        dialog = CustomiseHomeDialog(list(CATALOGUE), HomeLayout.of(["attendance", "last_raid"]))
        qtbot.addWidget(dialog)
        dialog.list.setCurrentRow(1)
        dialog.move_selected(-1)
        dialog.list.item(2).setCheckState(Qt.CheckState.Checked)
        chosen = dialog.chosen()
        assert chosen[:2] == ["last_raid", "attendance"] and len(chosen) == 3

    def test_move_past_the_ends_does_nothing(self, qtbot):
        dialog = CustomiseHomeDialog(list(CATALOGUE), HomeLayout.default())
        qtbot.addWidget(dialog)
        dialog.list.setCurrentRow(0)
        dialog.move_selected(-1)
        assert dialog.chosen() == list(HomeLayout.default().widgets)


@pytest.mark.gui
class TestChartWidgets:
    def test_weekly_healing_draws_a_chart_with_its_notes(self, view, service):
        view.show_page(service.page(HomeLayout.of(["healing_weekly", "healers_weekly"])))
        from PySide6.QtCharts import QChartView

        for widget_id in ("healing_weekly", "healers_weekly"):
            card = _card(view, widget_id)
            assert card.findChildren(QChartView), widget_id

    def test_payload_chart_breaks_lines_at_gaps_and_keeps_one_legend_entry(self, qtbot):
        from warcraftlogs_client.gui.charts import build_payload_chart
        from warcraftlogs_client.services.charts import Chart, Series

        payload = Chart(
            id="demo",
            title="Demo",
            kind="line",
            categories=["a", "b", "c", "d", "e"],
            series=[
                Series("one", "One", [1, 2, None, 4, 5], ["1", "2", "-", "4", "5"], emphasis=True),
                Series("two", "Two", [None, 3, None, None, None], ["-", "3", "-", "-", "-"]),
            ],
            y_max=5.0,
        ).validate()
        view = build_payload_chart(payload)
        qtbot.addWidget(view)
        chart = view.chart()
        assert len(chart.series()) == 3  # two runs of "One", a lone point of "Two"
        visible = [m.label() for m in chart.legend().markers() if m.isVisible()]
        assert visible == ["One", "Two"]

    def test_payload_bar_chart_draws_one_set_per_series(self, qtbot):
        from warcraftlogs_client.gui.charts import build_payload_chart
        from warcraftlogs_client.services.charts import Chart, Series

        payload = Chart(
            id="demo",
            title="Demo",
            kind="bar",
            categories=["a", "b"],
            series=[Series("one", "One", [None, 2], ["-", "2"])],
            y_max=2.0,
        )
        view = build_payload_chart(payload)
        qtbot.addWidget(view)
        (bars,) = view.chart().series()
        assert [s.label() for s in bars.barSets()] == ["One"]
        assert not view.chart().legend().isVisible()
