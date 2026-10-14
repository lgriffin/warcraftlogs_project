"""
Export what the window shows: its charts as PNG or SVG images, and the current view as a PDF, Markdown or JSON report.

``collect_report`` reads a view's visible headings, text, tables and charts in reading order into a ``ViewReport``;
``renderers.view_report`` formats it. ``ChartContextMenu`` gives every chart a right-click "Save image" menu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCharts import QAbstractBarSeries, QBarCategoryAxis, QChartView, QDateTimeAxis, QPieSeries, QXYSeries
from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEvent,
    QIODevice,
    QMarginsF,
    QModelIndex,
    QObject,
    QPoint,
    QRect,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QGuiApplication,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPixmap,
    QTextDocument,
    QTextDocumentFragment,
)
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QTreeView,
    QWidget,
)

from ..renderers.view_report import (
    Block,
    Figure,
    Heading,
    Paragraph,
    Series,
    Table,
    ViewReport,
    file_stem,
    render_html,
    render_json,
    render_markdown,
)

REPORT_FORMATS = {
    "pdf": "PDF Document (*.pdf)",
    "md": "Markdown (*.md)",
    "json": "JSON (*.json)",
}
IMAGE_FORMATS = {
    "png": "PNG Image (*.png)",
    "svg": "SVG Image (*.svg)",
}
IMAGE_SCALE = 2  # charts are saved at twice their on-screen size, so they stay sharp in a report or a slide
_TAG = re.compile(r"<[a-zA-Z/!]")
_MAX_TREE_DEPTH = 6
_ROW_REACH = 80  # a tall widget joins to its row only what starts this far below its top
_SKIPPED = (QAbstractButton, QAbstractSlider, QAbstractSpinBox, QComboBox, QLineEdit, QTabBar, QHeaderView, QMenu)


def is_chart(widget: QWidget) -> bool:
    return isinstance(widget, QChartView) or bool(getattr(widget, "exportable_chart", False))


def chart_title(widget: QWidget) -> str:
    if isinstance(widget, QChartView):
        return widget.chart().title().strip()
    return getattr(widget, "chart_title", "") or widget.accessibleName()


# ── Images ──


def chart_pixmap(widget: QWidget, scale: int = IMAGE_SCALE) -> QPixmap:
    """The chart drawn at ``scale`` times its size, so it is sharp outside the window."""
    size = widget.size()
    pixmap = QPixmap(size * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    QWidget.render(widget, pixmap)  # QChartView's own render() draws only its scene
    return pixmap


def save_png(widget: QWidget, path: Path) -> bool:
    return chart_pixmap(widget).save(str(path), "PNG")


def save_svg(widget: QWidget, path: Path) -> bool:
    size = widget.size()
    generator = QSvgGenerator()
    generator.setFileName(str(path))
    generator.setSize(size)
    generator.setViewBox(QRect(QPoint(0, 0), size))
    generator.setTitle(chart_title(widget) or "Chart")
    painter = QPainter()
    if not painter.begin(generator):
        return False
    QWidget.render(widget, painter, QPoint(0, 0))
    return painter.end()


def save_chart(widget: QWidget, path: Path) -> bool:
    """Save a chart as SVG when ``path`` ends in .svg, else as PNG."""
    return save_svg(widget, path) if path.suffix.lower() == ".svg" else save_png(widget, path)


def copy_chart(widget: QWidget) -> None:
    QGuiApplication.clipboard().setPixmap(chart_pixmap(widget))


# ── Reading a view ──


def _series_points(series) -> tuple[tuple[str | float, float], ...]:
    """A line's points; x as an ISO date on a date axis and as the category's name on a category axis."""
    horizontal = [a for a in series.attachedAxes() if a.orientation() == Qt.Orientation.Horizontal]
    dates = any(isinstance(a, QDateTimeAxis) for a in horizontal)
    categories = next((list(a.categories()) for a in horizontal if isinstance(a, QBarCategoryAxis)), [])
    points = []
    for p in series.points():
        x: str | float = p.x()
        if dates:
            x = datetime.fromtimestamp(p.x() / 1000).isoformat(timespec="seconds")
        elif categories and p.x().is_integer() and 0 <= int(p.x()) < len(categories):
            x = categories[int(p.x())]
        points.append((x, p.y()))
    return tuple(points)


def _bar_categories(series) -> list[str]:
    for axis in series.attachedAxes():
        if isinstance(axis, QBarCategoryAxis):
            return list(axis.categories())
    return []


def chart_series(widget: QWidget) -> tuple[Series, ...]:
    """The data behind a chart, as series of points: a Qt chart's series, or what a painted chart's
    ``export_series()`` gives; a painted chart without one exposes none."""
    if not isinstance(widget, QChartView):
        painted = getattr(widget, "export_series", None)
        if painted is None:
            return ()
        return tuple(Series(name, tuple(points)) for name, points in painted())
    out: list[Series] = []
    for series in widget.chart().series():
        if isinstance(series, QXYSeries):
            out.append(Series(series.name(), _series_points(series)))
        elif isinstance(series, QAbstractBarSeries):
            categories = _bar_categories(series)
            for bar_set in series.barSets():
                values = [bar_set.at(i) for i in range(bar_set.count())]
                labels = categories if len(categories) == len(values) else [str(i) for i in range(len(values))]
                out.append(Series(bar_set.label(), tuple(zip(labels, values, strict=False))))
        elif isinstance(series, QPieSeries):
            out.append(Series(series.name(), tuple((s.label(), s.value()) for s in series.slices())))
    return tuple(out)


def _plain(text: str, rich: bool) -> str:
    plain = QTextDocumentFragment.fromHtml(text).toPlainText() if rich else text
    return "\n".join(line.strip() for line in plain.splitlines() if line.strip())


def _label_block(label: QLabel) -> Block | None:
    text = label.text()
    if not text.strip():
        return None
    rich = label.textFormat() == Qt.TextFormat.RichText or (
        label.textFormat() == Qt.TextFormat.AutoText and _TAG.search(text) is not None
    )
    plain = _plain(text, rich)
    if not plain:
        return None
    label.ensurePolished()
    font = label.font()
    size = font.pointSizeF() if font.pointSizeF() > 0 else font.pixelSize() * 0.75
    if "\n" not in plain and len(plain) <= 80 and size >= 14:
        return Heading(plain, 2)
    if "\n" not in plain and len(plain) <= 80 and size >= 12 and font.bold():
        return Heading(plain, 3)
    return Paragraph(plain)


def _control_value(widget: QWidget) -> str | None:
    """The choice a combo box or spin box shows, "" for a text box, or None for any other widget.

    A text box's content is never exported, label and all: on Settings they hold the API credentials, which must not
    land in a report someone shares.
    """
    if isinstance(widget, QComboBox):
        return widget.currentText().strip()
    if isinstance(widget, QAbstractSpinBox):
        return widget.text().strip()
    if isinstance(widget, QLineEdit):
        return ""
    return None


def item_view_table(view: QAbstractItemView) -> Table | None:
    """The rows of a table, tree or list as shown, children of a tree row indented under it."""
    model = view.model()
    if model is None:
        return None
    columns = max(_column_count(model), 1)
    hidden = {c for c in range(columns) if _column_hidden(view, c)}
    shown = [c for c in range(columns) if c not in hidden]
    header = tuple(
        str(model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or f"Column {c + 1}")
        for c in shown
    )
    rows: list[tuple[str, ...]] = []
    _collect_rows(view, model, None, 0, shown, rows)
    if not rows:
        return None
    return Table(header if columns > 1 or model.headerData(0, Qt.Orientation.Horizontal) else ("Item",), tuple(rows))


def _column_count(model) -> int:
    try:
        return model.columnCount(QModelIndex())
    except TypeError:  # a list model keeps columnCount private: it has the one column
        return 1


def _column_hidden(view: QAbstractItemView, column: int) -> bool:
    is_hidden = getattr(view, "isColumnHidden", None)
    return bool(is_hidden and is_hidden(column))


def _collect_rows(view, model, parent, depth: int, columns: list[int], rows: list[tuple[str, ...]]) -> None:
    parent = parent if parent is not None else QModelIndex()
    is_row_hidden = getattr(view, "isRowHidden", None)
    for r in range(model.rowCount(parent)):
        if is_row_hidden is not None and _row_hidden(view, r, parent):
            continue
        cells = []
        for i, c in enumerate(columns):
            value = model.data(model.index(r, c, parent), Qt.ItemDataRole.DisplayRole)
            text = "" if value is None else str(value)
            cells.append(("  " * depth + text) if i == 0 and depth else text)
        rows.append(tuple(cells))
        first = model.index(r, 0, parent)
        # Only a tree has children; table models often ignore the parent and would repeat their rows forever.
        # A collapsed branch is not shown, so it is not exported.
        if (
            isinstance(view, QTreeView)
            and view.isExpanded(first)
            and depth < _MAX_TREE_DEPTH
            and model.rowCount(first) > 0
        ):
            _collect_rows(view, model, first, depth + 1, columns, rows)


def _row_hidden(view, row: int, parent) -> bool:
    try:
        return bool(view.isRowHidden(row, parent))  # QTreeView
    except TypeError:
        return bool(view.isRowHidden(row))  # QTableView, QListView


@dataclass
class _Reader:
    root: QWidget
    blocks: list[Block] = field(default_factory=list)
    charts: dict[str, QWidget] = field(default_factory=dict)

    def heading(self, text: str, level: int) -> None:
        if text.strip():
            self.add(Heading(text.strip(), level))

    def add(self, block: Block) -> None:
        if self.blocks and self.blocks[-1] == block:
            return
        self.blocks.append(block)

    def last_heading(self) -> str:
        return next((b.text for b in reversed(self.blocks) if isinstance(b, Heading)), "")

    def chart(self, widget: QWidget) -> None:
        title = chart_title(widget) or self.last_heading() or "Chart"
        key = f"{len(self.charts) + 1:02d}_{file_stem(title)}"
        self.charts[key] = widget
        self.add(Figure(key, title, chart_series(widget)))

    def walk(self, widget: QWidget) -> None:
        kids = self._children(widget)
        i = 0
        while i < len(kids):
            nxt = kids[i + 1] if i + 1 < len(kids) else None
            if nxt is not None and self.labelled_control(kids[i], nxt):
                i += 2
                continue
            self.visit(kids[i])
            i += 1

    def labelled_control(self, label: QWidget, control: QWidget) -> bool:
        """A "Name:" label beside the control it names becomes one "Name: value" line, the filter the page shows."""
        if not isinstance(label, QLabel) or not label.text().strip().endswith(":"):
            return False
        value = _control_value(control)
        if value is None:
            return False
        if value:
            self.add(Paragraph(f"{_plain(label.text(), rich=False)} {value}"))
        return True

    def visit(self, w: QWidget) -> None:
        if is_chart(w):
            self.chart(w)
        elif isinstance(w, QTabWidget):
            if w.currentWidget() is not None:
                self.heading(w.tabText(w.currentIndex()).replace("&", ""), 2)
                self.walk(w.currentWidget())
        elif isinstance(w, QGroupBox):
            self.heading(w.title(), 3)
            self.walk(w)
        elif isinstance(w, QLabel):
            block = _label_block(w)
            if block is not None:
                self.add(block)
        elif isinstance(w, QAbstractItemView):
            table = item_view_table(w)
            if table is not None:
                self.add(table)
        elif isinstance(w, (QTextEdit, QPlainTextEdit)):
            text = _plain(w.toPlainText(), rich=False)
            if text:
                self.add(Paragraph(text))
        elif isinstance(w, QAbstractScrollArea):
            self.walk(w.viewport())
        elif not isinstance(w, _SKIPPED):
            self.walk(w)

    def _children(self, widget: QWidget) -> list[QWidget]:
        """The widget's shown children in reading order: row by row, each row left to right.

        Widgets whose heights overlap share a row, so a label centred beside a taller box still reads first.
        """
        kids = [c for c in widget.children() if isinstance(c, QWidget) and not c.isWindow()]
        kids = [c for c in kids if c.isVisibleTo(self.root)]
        top = {id(c): c.mapTo(self.root, QPoint(0, 0)) for c in kids}
        rows: list[list[QWidget]] = []
        bottom = None
        for c in sorted(kids, key=lambda c: (top[id(c)].y(), top[id(c)].x())):
            reach = top[id(c)].y() + min(max(c.height(), 1), _ROW_REACH)
            if bottom is None or top[id(c)].y() >= bottom:
                rows.append([])
                bottom = reach
            rows[-1].append(c)
            bottom = max(bottom, reach)
        return [c for row in rows for c in sorted(row, key=lambda c: top[id(c)].x())]


def collect_report(view: QWidget, title: str) -> tuple[ViewReport, dict[str, QWidget]]:
    """What ``view`` shows as a report, and each of its charts by the key its figure carries."""
    reader = _Reader(view)
    reader.walk(view)
    return ViewReport(title=title, generated_at=datetime.now(), blocks=tuple(reader.blocks)), reader.charts


def report_title(view: QWidget, fallback: str) -> str:
    """The first heading ``view`` shows, else ``fallback``."""
    report, _ = collect_report(view, fallback)
    return next((b.text for b in report.blocks if isinstance(b, Heading)), fallback)


def view_charts(view: QWidget) -> list[tuple[str, QWidget]]:
    """The charts ``view`` shows, each with its file stem, in reading order."""
    _, charts = collect_report(view, "")
    return list(charts.items())


# ── Writing a report ──


def write_report(view: QWidget, title: str, path: Path) -> Path:
    """Write ``view`` as a report to ``path``; the format comes from its suffix (.pdf, .md or .json).

    Markdown and JSON reports save their charts as PNGs in a ``<name>_charts`` folder beside the file.
    """
    report, charts = collect_report(view, title)
    fmt = path.suffix.lower().lstrip(".")
    if fmt == "pdf":
        _write_pdf(report, charts, path)
        return path
    if fmt not in ("md", "json"):
        raise ValueError(f"Cannot export a report as {path.suffix or 'a file with no extension'}")
    images = _save_images(charts, path.parent, f"{path.stem}_charts")
    text = render_markdown(report, images) if fmt == "md" else render_json(report, images)
    path.write_text(text, encoding="utf-8")
    return path


def _save_images(charts: dict[str, QWidget], parent: Path, folder: str) -> dict[str, str]:
    if not charts:
        return {}
    (parent / folder).mkdir(parents=True, exist_ok=True)
    images = {}
    for key, widget in charts.items():
        if save_png(widget, parent / folder / f"{key}.png"):
            images[key] = f"{folder}/{key}.png"
    return images


def _png_bytes(widget: QWidget) -> QByteArray:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    chart_pixmap(widget).save(buffer, "PNG")
    buffer.close()
    return data


def _write_pdf(report: ViewReport, charts: dict[str, QWidget], path: Path) -> None:
    # QPdfWriter fails silently on a file it cannot open (a read-only folder, a PDF open in a viewer): open it first,
    # which raises OSError, and check the result after.
    with path.open("wb"):
        pass
    writer = QPdfWriter(str(path))
    writer.setTitle(report.title)
    writer.setCreator("WarcraftLogs Analyzer")
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(15, 15, 15, 15),
            QPageLayout.Unit.Millimeter,
        )
    )
    doc = QTextDocument()
    images = {}
    for key, widget in charts.items():
        url = f"chart://{key}.png"
        image = QPixmap()
        image.loadFromData(_png_bytes(widget), "PNG")
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)
        images[key] = url
    widths = {key: widget.width() for key, widget in charts.items()}
    doc.setHtml(render_html(report, images, widths))
    doc.print_(writer)
    del writer  # finishes the file
    if path.stat().st_size == 0:
        raise OSError(f"Could not write {path}")


# ── Dialogs ──


def export_report_dialog(parent: QWidget, view: QWidget, title: str, fmt: str = "pdf") -> Path | None:
    """Ask where to save ``view`` as a report, defaulting to ``fmt``, and save it there; None when cancelled."""
    filters = ";;".join(REPORT_FORMATS.values())
    suggested = f"{file_stem(title)}.{fmt}"
    chosen, selected = QFileDialog.getSaveFileName(parent, "Export Report", suggested, filters, REPORT_FORMATS[fmt])
    if not chosen:
        return None
    path = Path(chosen)
    if path.suffix.lower().lstrip(".") not in REPORT_FORMATS:
        ext = next((k for k, v in REPORT_FORMATS.items() if v == selected), fmt)
        path = path.with_name(f"{path.name}.{ext}")
    return write_report(view, title, path)


def save_chart_dialog(parent: QWidget, widget: QWidget, fmt: str = "png") -> Path | None:
    """Ask where to save one chart, as PNG or SVG; None when cancelled or the save failed."""
    suggested = f"{file_stem(chart_title(widget) or 'chart')}.{fmt}"
    filters = ";;".join(IMAGE_FORMATS.values())
    chosen, selected = QFileDialog.getSaveFileName(parent, "Save Chart Image", suggested, filters, IMAGE_FORMATS[fmt])
    if not chosen:
        return None
    path = Path(chosen)
    if path.suffix.lower().lstrip(".") not in IMAGE_FORMATS:
        ext = next((k for k, v in IMAGE_FORMATS.items() if v == selected), fmt)
        path = path.with_name(f"{path.name}.{ext}")
    return path if save_chart(widget, path) else None


def save_all_charts(view: QWidget, folder: Path, formats: tuple[str, ...] = ("png", "svg")) -> list[Path]:
    """Save every chart ``view`` shows into ``folder``, once per format; the files written."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for stem, widget in view_charts(view):
        for fmt in formats:
            path = folder / f"{stem}.{fmt}"
            if save_chart(widget, path):
                written.append(path)
    return written


class ChartContextMenu(QObject):
    """Right-click any chart in the application for Save as PNG, Save as SVG and Copy image.

    Installed once on the application, so charts built anywhere, now or later, get the menu without each view
    wiring it up. ``saved`` reports where an image went.
    """

    def __init__(self, on_saved=None, parent=None):
        super().__init__(parent)
        self._on_saved = on_saved

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.ContextMenu or not isinstance(obj, QWidget):
            return False
        chart = _chart_at(obj)
        if chart is None:
            return False
        self.show_menu(chart, event.globalPos())
        return True

    def build_menu(self, chart: QWidget) -> QMenu:
        menu = QMenu(chart)
        menu.addAction("Save image as PNG…", lambda: self._save(chart, "png"))
        menu.addAction("Save image as SVG…", lambda: self._save(chart, "svg"))
        menu.addSeparator()
        menu.addAction("Copy image", lambda: self._copy(chart))
        return menu

    def show_menu(self, chart: QWidget, pos) -> None:
        menu = self.build_menu(chart)
        menu.exec(pos)
        menu.deleteLater()

    def _save(self, chart: QWidget, fmt: str) -> None:
        path = save_chart_dialog(chart.window(), chart, fmt)
        if path and self._on_saved:
            self._on_saved(f"Chart saved to {path}")

    def _copy(self, chart: QWidget) -> None:
        copy_chart(chart)
        if self._on_saved:
            self._on_saved("Chart image copied to the clipboard")


def _chart_at(widget: QWidget | None) -> QWidget | None:
    while widget is not None:
        if is_chart(widget):
            return widget
        if widget.isWindow():
            return None
        widget = widget.parentWidget()
    return None
