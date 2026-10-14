"""Exporting a page: its charts as PNG and SVG, and the page as a PDF, Markdown or JSON report."""

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCharts import QChart, QChartView, QPieSeries
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QGuiApplication, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from wcl_app.charts import Chart
from wcl_app.charts import Series as ChartSeries

from warcraftlogs_client.gui import export
from warcraftlogs_client.gui.charts import build_attendance_chart, build_healer_chart, build_payload_chart
from warcraftlogs_client.gui.raid_analysis_widget import RaidAnalysisWidget
from warcraftlogs_client.renderers.view_report import Heading, Paragraph, Table


class _PaintedChart(QWidget):
    """Stands in for the custom-painted charts (heatmaps, timelines, spider charts)."""

    exportable_chart = True

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 120)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.darkCyan)


def _heading(text: str, px: int = 20) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size: {px}px; font-weight: bold;")
    return label


def _table() -> QTableWidget:
    table = QTableWidget(2, 3)
    table.setHorizontalHeaderLabels(["Name", "Healing", "Secret"])
    for r, row in enumerate([("Holy", "1,234", "x"), ("Resto", "987.5", "y")]):
        for c, text in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(text))
    table.setColumnHidden(2, True)
    return table


TREND = [{"raid_date": f"2026-0{m}-10", "total_healing": 1000 * m, "total_overhealing": 100 * m} for m in (3, 2, 1)]


@pytest.fixture
def page(qtbot):
    """A page with a heading, rich text, tabs (one shown), a chart, a table, a group, a tree and a painted chart."""
    root = QWidget()
    layout = QVBoxLayout(root)
    layout.addWidget(_heading("Character History"))
    layout.addWidget(QLabel("Tracked since <b>March</b>."))
    layout.addWidget(QPushButton("Refresh"))
    hidden = QLabel("Not shown")
    hidden.setVisible(False)
    layout.addWidget(hidden)

    tabs = QTabWidget()
    trends = QWidget()
    trends_layout = QVBoxLayout(trends)
    trends_layout.addWidget(build_healer_chart(TREND))
    trends_layout.addWidget(_table())
    tabs.addTab(trends, "&Trends")
    tabs.addTab(QLabel("On the other tab"), "Other")
    layout.addWidget(tabs)

    group = QGroupBox("Attendance")
    group_layout = QVBoxLayout(group)
    group_layout.addWidget(
        build_attendance_chart([{"name": "Holy", "raid_count": 4}, {"name": "Resto", "raid_count": 2}])
    )
    layout.addWidget(group)

    tree = QTreeView()
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(["Boss", "Kills"])
    boss = QStandardItem("Gruul")
    boss.appendRow([QStandardItem("Trash"), QStandardItem("12")])
    model.appendRow([boss, QStandardItem("3")])
    tree.setModel(model)
    tree.expandAll()
    layout.addWidget(tree)

    notes = QTextEdit()
    notes.setPlainText("Officer notes\nsecond line")
    layout.addWidget(notes)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(_PaintedChart())
    layout.addWidget(scroll)

    qtbot.addWidget(root)
    root.resize(900, 2400)
    root.show()
    qtbot.waitExposed(root)
    return root


@pytest.mark.gui
class TestCollectReport:
    def test_reads_what_the_page_shows_in_reading_order(self, page):
        report, charts = export.collect_report(page, "History")

        kinds = [(type(b).__name__, getattr(b, "text", getattr(b, "title", ""))) for b in report.blocks]
        assert kinds == [
            ("Heading", "Character History"),
            ("Paragraph", "Tracked since March."),
            ("Heading", "Trends"),
            ("Figure", "Healing Performance"),
            ("Table", ""),
            ("Heading", "Attendance"),
            ("Figure", "Raid Attendance"),
            ("Table", ""),
            ("Paragraph", "Officer notes\nsecond line"),
            ("Figure", "Attendance"),  # a painted chart has no title of its own: the heading above it
        ]
        assert report.title == "History"
        assert list(charts) == ["01_healing_performance", "02_raid_attendance", "03_attendance"]

    def test_skips_hidden_widgets_buttons_and_other_tabs(self, page):
        report, _ = export.collect_report(page, "History")

        text = json.dumps([getattr(b, "text", "") for b in report.blocks])
        assert "Not shown" not in text
        assert "Refresh" not in text
        assert "On the other tab" not in text

    def test_tables_keep_shown_columns_and_indent_tree_children(self, page):
        report, _ = export.collect_report(page, "History")

        table, tree = [b for b in report.blocks if isinstance(b, Table)]
        assert table.columns == ("Name", "Healing")
        assert table.rows == (("Holy", "1,234"), ("Resto", "987.5"))
        assert tree.columns == ("Boss", "Kills")
        assert tree.rows == (("Gruul", "3"), ("  Trash", "12"))

    def test_qt_charts_carry_their_data(self, page):
        report, _ = export.collect_report(page, "History")

        healing, attendance, painted = report.figures
        names = [s.name for s in healing.series]
        assert names == ["Healing", "Overhealing"]
        assert healing.series[0].points[0] == ("2026-01-10T00:00:00", 1000.0)
        assert sorted(attendance.series[0].points) == [("Holy", 4.0), ("Resto", 2.0)]
        assert painted.series == ()

    def test_line_on_a_category_axis_and_pie_slices_are_named(self, qtbot):
        payload = Chart(
            id="dps",
            title="Weekly DPS",
            kind="line",
            categories=["W1", "W2"],
            series=[ChartSeries(key="dps", name="DPS", values=[10.0, 20.0], display=["10", "20"])],
            y_max=30,
        )
        view = build_payload_chart(payload)
        qtbot.addWidget(view)
        assert export.chart_series(view)[0].points == (("W1", 10.0), ("W2", 20.0))

        pie = QPieSeries()
        pie.setName("Roles")
        pie.append("Tanks", 2)
        pie.append("Healers", 5)
        chart = QChart()
        chart.addSeries(pie)
        pie_view = QChartView(chart)
        qtbot.addWidget(pie_view)
        assert export.chart_series(pie_view)[0].points == (("Tanks", 2.0), ("Healers", 5.0))

    def test_a_labelled_filter_reads_as_one_line(self, qtbot):
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit

        root = QWidget()
        row = QHBoxLayout(root)
        combo = QComboBox()
        combo.addItems(["All Zones", "Karazhan"])
        combo.setCurrentIndex(1)
        combo.setMinimumHeight(40)  # taller than its label, which sits centred beside it
        row.addWidget(QLabel("Zone:"))
        row.addWidget(combo)
        row.addWidget(QLabel("Search:"))
        row.addWidget(QLineEdit())  # empty: left out
        row.addWidget(combo_alone := QComboBox())
        combo_alone.addItem("Unlabelled")
        qtbot.addWidget(root)
        root.show()

        report, _ = export.collect_report(root, "Filters")

        assert report.blocks == (Paragraph("Zone: Karazhan"),)

    def test_report_title_is_the_first_heading(self, page, qtbot):
        assert export.report_title(page, fallback="Report") == "Character History"
        empty = QWidget()
        qtbot.addWidget(empty)
        assert export.report_title(empty, fallback="Report") == "Report"

    def test_a_raid_page_exports(self, qtbot, sample_analysis, tmp_path):
        widget = RaidAnalysisWidget(sample_analysis)
        qtbot.addWidget(widget)
        widget.resize(1400, 900)
        widget.show()

        report, _ = export.collect_report(widget, "Raid")

        assert any(isinstance(b, Heading) and "Karazhan Full Clear" in b.text for b in report.blocks)
        healers = next(b for b in report.blocks if isinstance(b, Table) and "Healing" in b.columns)
        assert healers.rows[0][0] == "HolyPriest"


@pytest.mark.gui
class TestWriteReport:
    def test_markdown_links_chart_pngs_saved_beside_it(self, page, tmp_path):
        path = export.write_report(page, "History", tmp_path / "history.md")

        md = path.read_text(encoding="utf-8")
        assert md.startswith("# History")
        assert "![Healing Performance](history_charts/01_healing_performance.png)" in md
        assert "| Holy | 1,234 |" in md
        pngs = sorted(p.name for p in (tmp_path / "history_charts").iterdir())
        assert pngs == ["01_healing_performance.png", "02_raid_attendance.png", "03_attendance.png"]
        assert (tmp_path / "history_charts" / pngs[0]).read_bytes().startswith(b"\x89PNG")

    def test_json_has_records_and_chart_data(self, page, tmp_path):
        path = export.write_report(page, "History", tmp_path / "history.json")

        doc = json.loads(path.read_text(encoding="utf-8"))
        table = next(b for b in doc["blocks"] if b["type"] == "table")
        assert table["rows"][0] == {"Name": "Holy", "Healing": 1234}
        chart = next(b for b in doc["blocks"] if b["type"] == "chart")
        assert chart["image"] == "history_charts/01_healing_performance.png"
        assert chart["series"][0]["points"][0] == {"x": "2026-01-10T00:00:00", "y": 1000.0}

    def test_pdf(self, page, tmp_path):
        path = export.write_report(page, "History", tmp_path / "history.pdf")

        data = path.read_bytes()
        assert data.startswith(b"%PDF")
        assert len(data) > 10_000  # the charts are in it
        assert not (tmp_path / "history_charts").exists()

    def test_a_page_with_no_charts_writes_no_image_folder(self, qtbot, tmp_path):
        root = QWidget()
        QVBoxLayout(root).addWidget(QLabel("Just text"))
        qtbot.addWidget(root)

        export.write_report(root, "Plain", tmp_path / "plain.md")

        assert not (tmp_path / "plain_charts").exists()

    def test_unknown_format_is_refused(self, page, tmp_path):
        with pytest.raises(ValueError, match=r"\.txt"):
            export.write_report(page, "History", tmp_path / "history.txt")


@pytest.mark.gui
class TestChartImages:
    def test_png_is_drawn_at_twice_the_size(self, page, tmp_path):
        from PySide6.QtGui import QImage

        chart = next(w for _, w in export.view_charts(page))
        path = tmp_path / "chart.png"

        assert export.save_chart(chart, path)

        image = QImage(str(path))
        assert image.width() == chart.width() * export.IMAGE_SCALE

    def test_svg(self, page, tmp_path):
        chart = next(w for _, w in export.view_charts(page))
        path = tmp_path / "chart.svg"

        assert export.save_chart(chart, path)

        assert "<svg" in path.read_text(encoding="utf-8")

    def test_save_all_charts_writes_png_and_svg_of_each(self, page, tmp_path):
        written = export.save_all_charts(page, tmp_path / "out")

        names = sorted(p.name for p in written)
        assert len(names) == 6
        assert "01_healing_performance.png" in names
        assert "01_healing_performance.svg" in names

    def test_copy_puts_the_image_on_the_clipboard(self, page):
        chart = next(w for _, w in export.view_charts(page))

        export.copy_chart(chart)

        assert not QGuiApplication.clipboard().pixmap().isNull()


@pytest.mark.gui
class TestDialogs:
    def test_report_dialog_adds_the_chosen_formats_extension(self, page, tmp_path, monkeypatch):
        chosen = tmp_path / "my report"
        monkeypatch.setattr(
            export.QFileDialog, "getSaveFileName", lambda *a: (str(chosen), export.REPORT_FORMATS["json"])
        )

        path = export.export_report_dialog(page, page, "History", "pdf")

        assert path == tmp_path / "my report.json"
        assert path.exists()

    def test_report_dialog_cancelled(self, page, monkeypatch):
        monkeypatch.setattr(export.QFileDialog, "getSaveFileName", lambda *a: ("", ""))

        assert export.export_report_dialog(page, page, "History") is None

    def test_chart_dialog_suggests_the_chart_title(self, page, tmp_path, monkeypatch):
        seen = {}

        def fake(parent, caption, suggested, filters, selected):
            seen["suggested"] = suggested
            return str(tmp_path / "healing"), export.IMAGE_FORMATS["svg"]

        monkeypatch.setattr(export.QFileDialog, "getSaveFileName", fake)
        chart = next(w for _, w in export.view_charts(page))

        path = export.save_chart_dialog(page, chart, "png")

        assert seen["suggested"] == "healing_performance.png"
        assert path == tmp_path / "healing.svg"
        assert path.exists()


@pytest.mark.gui
class TestChartContextMenu:
    def test_menu_offers_png_svg_and_copy(self, page):
        chart = next(w for _, w in export.view_charts(page))
        menu = export.ChartContextMenu().build_menu(chart)

        labels = [a.text() for a in menu.actions() if not a.isSeparator()]

        assert labels == ["Save image as PNG…", "Save image as SVG…", "Copy image"]

    def test_right_click_inside_a_chart_opens_it_and_elsewhere_does_not(self, page, monkeypatch):
        shown = []
        handler = export.ChartContextMenu()
        monkeypatch.setattr(handler, "show_menu", lambda chart, pos: shown.append(chart))
        chart_view = next(w for _, w in export.view_charts(page) if isinstance(w, QChartView))
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5))

        assert handler.eventFilter(chart_view.viewport(), event) is True
        assert handler.eventFilter(page, event) is False
        assert handler.eventFilter(chart_view, QEvent(QEvent.Type.MouseButtonPress)) is False
        assert shown == [chart_view]

    def test_copy_action_reports_back(self, page):
        messages = []
        chart = next(w for _, w in export.view_charts(page))
        menu = export.ChartContextMenu(on_saved=messages.append).build_menu(chart)

        next(a for a in menu.actions() if a.text() == "Copy image").trigger()

        assert messages == ["Chart image copied to the clipboard"]

    def test_save_action_reports_where(self, page, tmp_path, monkeypatch):
        messages = []
        monkeypatch.setattr(
            export.QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "c.png"), export.IMAGE_FORMATS["png"])
        )
        chart = next(w for _, w in export.view_charts(page))
        menu = export.ChartContextMenu(on_saved=messages.append).build_menu(chart)

        next(a for a in menu.actions() if a.text() == "Save image as PNG…").trigger()

        assert messages == [f"Chart saved to {tmp_path / 'c.png'}"]
