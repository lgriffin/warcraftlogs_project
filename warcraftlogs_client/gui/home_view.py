"""
Home — a customisable landing page built from ``services.home`` widgets.

The view only draws what ``HomeService`` returns: each widget kind (stats, table, list, bars, actions, chart,
badges) has one renderer here, and links are turned into navigation signals the main window handles. The user's
choice of widgets is saved through the service to ``home_layout.json`` in the user data directory.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..common.errors import ConfigurationError
from ..paths import get_user_data_dir
from ..services import AppContext, HomeLayout, HomePage, HomeService, HomeWidget, JsonLayoutStore, WidgetSpec
from ..services.home import ACTION, CHARACTER, PLAYER_PAGE, RAID, Link
from .badges import BadgeStrip
from .charts import build_payload_chart
from .styles import CLASS_COLORS, COLORS, COMMON_STYLES

LAYOUT_FILE = "home_layout.json"
_ROW_HEIGHT = 30
_TILES_PER_ROW = 6


def desktop_context() -> AppContext:
    """The desktop's context in the saved profile; without a loadable config.json, a database-only one."""
    try:
        return AppContext.desktop()
    except ConfigurationError:
        return AppContext.desktop(with_config=False)


def default_home_service(ctx: AppContext | None = None) -> HomeService:
    """The desktop's home service: the local database, with the layout kept next to it.

    Badge thresholds come from config.json when it loads; without it the defaults apply. Pass the window's
    ``ctx`` so a profile switch on it reaches the home page.
    """
    context = ctx if ctx is not None else desktop_context()
    return HomeService.from_context(context, JsonLayoutStore(get_user_data_dir() / LAYOUT_FILE))


class _PageWorker(QThread):
    loaded = Signal(object)  # HomePage

    def __init__(self, service: HomeService, parent=None):
        super().__init__(parent)
        self._service = service

    def run(self):
        self.loaded.emit(self._service.page())


def _label(text: str, size: int = 10, color: str = "text", bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setFont(QFont("Segoe UI", size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
    label.setStyleSheet(f"color: {COLORS[color]}; background: transparent; border: none;")
    return label


class _Tile(QFrame):
    def __init__(self, label: str, display: str, hint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("homeTile")
        self.setStyleSheet(f"""
            QFrame#homeTile {{
                background-color: {COLORS["bg_input"]};
                border: 1px solid {COLORS["border"]};
                border-top: 3px solid {COLORS["accent"]};
                border-radius: 6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        layout.addWidget(_label(label, 9, "text_dim"))
        self.value_label = _label(display, 18, "text_gold", bold=True)
        layout.addWidget(self.value_label)
        if hint:
            layout.addWidget(_label(hint, 8, "text_dim"))


class WidgetCard(QFrame):
    """One home widget: a header with its title and actions, and a body drawn for the widget's kind."""

    link_activated = Signal(object)  # Link
    hide_requested = Signal(str)  # widget id

    def __init__(self, widget: HomeWidget, parent=None):
        super().__init__(parent)
        self.widget_id = widget.id
        self.setObjectName("homeCard")
        self.setStyleSheet(f"""
            QFrame#homeCard {{
                background-color: {COLORS["bg_card"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)
        layout.addLayout(self._header(widget))

        if widget.error:
            layout.addWidget(_label(f"Could not load: {widget.error}", 10, "error"))
        elif widget.empty:
            layout.addWidget(_label(widget.empty, 10, "text_dim"))
        else:
            layout.addWidget(self._body(widget))

    def _header(self, widget: HomeWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_label(widget.title, 13, "text_header", bold=True))
        if widget.subtitle:
            row.addWidget(_label(widget.subtitle, 10, "text_dim"))
        row.addStretch()
        if widget.link is not None and not widget.error:
            open_btn = QPushButton("Open")
            open_btn.setProperty("secondary", True)
            open_btn.setFixedHeight(28)
            link = widget.link
            open_btn.clicked.connect(lambda: self.link_activated.emit(link))
            row.addWidget(open_btn)
        hide_btn = QPushButton("✕")
        hide_btn.setProperty("secondary", True)
        hide_btn.setFixedSize(28, 28)
        hide_btn.setStyleSheet("padding: 0;")
        hide_btn.setToolTip("Remove from Home (add it back with Customise)")
        hide_btn.clicked.connect(lambda: self.hide_requested.emit(self.widget_id))
        row.addWidget(hide_btn)
        return row

    def _body(self, widget: HomeWidget) -> QWidget:
        builders = {
            "stats": self._stats,
            "table": self._table,
            "list": self._list,
            "bars": self._bars,
            "actions": self._actions,
            "badges": self._badges,
            "chart": self._chart,
        }
        return builders[widget.kind](widget)

    def _stats(self, widget: HomeWidget) -> QWidget:
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        for i, tile in enumerate(widget.tiles):
            grid.addWidget(_Tile(tile.label, tile.display, tile.hint), i // _TILES_PER_ROW, i % _TILES_PER_ROW)
        return body

    def _table(self, widget: HomeWidget) -> QWidget:
        table = QTableWidget(len(widget.rows), len(widget.columns))
        table.setObjectName("homeTable")
        table.setHorizontalHeaderLabels([c.label for c in widget.columns])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(_ROW_HEIGHT)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setShowGrid(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setStyleSheet(f"""
            QTableWidget#homeTable {{
                background-color: {COLORS["bg_card"]};
                border: none;
                font-size: 12px;
            }}
            QTableWidget#homeTable::item:selected {{
                background-color: {COLORS["bg_hover"]};
                color: {COLORS["text_gold"]};
            }}
            QHeaderView::section {{
                background-color: {COLORS["bg_card"]};
                color: {COLORS["text_dim"]};
                border: none;
                border-bottom: 1px solid {COLORS["border"]};
                padding: 4px 6px;
            }}
        """)
        header = table.horizontalHeader()
        for col, column in enumerate(widget.columns):
            mode = QHeaderView.ResizeMode.Stretch if column.key == "name" else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(col, mode)
        header.setStretchLastSection(not any(c.key == "name" for c in widget.columns))

        for r, row in enumerate(widget.rows):
            for c, column in enumerate(widget.columns):
                item = QTableWidgetItem(row.cells.get(column.key, ""))
                if column.align == "right":
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column.key == "class" and row.cells.get("class") in CLASS_COLORS:
                    item.setForeground(QColor(CLASS_COLORS[row.cells["class"]]))
                if row.link is not None:
                    item.setToolTip("Double-click to open")
                table.setItem(r, c, item)

        links = [row.link for row in widget.rows]

        def activate(r: int, _c: int) -> None:
            if links[r] is not None:
                self.link_activated.emit(links[r])

        table.cellDoubleClicked.connect(activate)
        table.setFixedHeight(header.sizeHint().height() + _ROW_HEIGHT * len(widget.rows) + 4)
        return table

    def _list(self, widget: HomeWidget) -> QWidget:
        lst = QListWidget()
        lst.setObjectName("homeList")
        lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lst.setStyleSheet(f"""
            QListWidget#homeList {{
                background-color: {COLORS["bg_card"]};
                border: none;
                font-size: 12px;
            }}
            QListWidget#homeList::item {{
                padding: 6px 4px;
                border-bottom: 1px solid {COLORS["border"]};
            }}
            QListWidget#homeList::item:selected {{
                background-color: {COLORS["bg_hover"]};
                color: {COLORS["text_gold"]};
            }}
        """)
        for entry in widget.items:
            item = QListWidgetItem(f"{entry.detail}    {entry.label}" if entry.detail else entry.label)
            item.setData(Qt.ItemDataRole.UserRole, entry.link)
            if entry.link is not None:
                item.setToolTip("Double-click to open")
            lst.addItem(item)
        lst.itemDoubleClicked.connect(self._on_list_item)
        lst.setFixedHeight(_ROW_HEIGHT * len(widget.items) + 8)
        return lst

    def _on_list_item(self, item: QListWidgetItem) -> None:
        link = item.data(Qt.ItemDataRole.UserRole)
        if link is not None:
            self.link_activated.emit(link)

    def _bars(self, widget: HomeWidget) -> QWidget:
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        top = max((b.value for b in widget.bars), default=0) or 1
        for r, bar in enumerate(widget.bars):
            grid.addWidget(_label(bar.label, 9, "text_dim"), r, 0)
            meter = QProgressBar()
            meter.setRange(0, 1000)
            meter.setValue(int(bar.value / top * 1000))
            meter.setTextVisible(False)
            meter.setFixedHeight(12)
            meter.setStyleSheet(f"""
                QProgressBar {{ background-color: {COLORS["bg_input"]}; border: none; border-radius: 3px; }}
                QProgressBar::chunk {{ background-color: {COLORS["accent"]}; border-radius: 3px; }}
            """)
            grid.addWidget(meter, r, 1)
            grid.addWidget(_label(bar.display, 9, "text"), r, 2)
        return body

    def _chart(self, widget: HomeWidget) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if widget.chart is not None:
            layout.addWidget(build_payload_chart(widget.chart))
            for note in widget.chart.notes:
                layout.addWidget(_label(note, 9, "text_dim"))
        return body

    def _actions(self, widget: HomeWidget) -> QWidget:
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        per_row = 4
        for i, action in enumerate(widget.actions):
            btn = QPushButton(action.label)
            btn.setProperty("secondary", True)
            btn.setMinimumHeight(40)
            btn.setToolTip(action.description)
            btn.setObjectName(f"action:{action.id}")
            link = Link(ACTION, {"id": action.id})
            btn.clicked.connect(lambda _checked=False, link=link: self.link_activated.emit(link))
            grid.addWidget(btn, i // per_row, i % per_row)
        return body

    def _badges(self, widget: HomeWidget) -> QWidget:
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        for r, holder in enumerate(widget.holders):
            name = QPushButton(holder.name)
            name.setObjectName(f"holder:{holder.name}")
            name.setFlat(True)
            name.setCursor(Qt.CursorShape.PointingHandCursor)
            color = CLASS_COLORS.get(holder.player_class, COLORS["text"])
            name.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {color}; text-align: left; padding: 2px 4px;"
                f" font-weight: normal; }} QPushButton:hover {{ color: {COLORS['text_gold']}; }}"
            )
            if holder.link is not None:
                link = holder.link
                name.clicked.connect(lambda _checked=False, link=link: self.link_activated.emit(link))
            grid.addWidget(name, r, 0)
            grid.addWidget(BadgeStrip(holder.badges, 24), r, 1)
        return body


class CustomiseHomeDialog(QDialog):
    """Pick and order the widgets on Home: tick to show, drag or use the arrows to reorder."""

    def __init__(self, catalogue: list[WidgetSpec], layout: HomeLayout, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customise Home")
        self.setMinimumSize(460, 520)
        self.setStyleSheet(
            COMMON_STYLES
            + f"""
            CustomiseHomeDialog {{ background-color: {COLORS["bg_dark"]}; }}
            QListWidget {{
                background-color: {COLORS["bg_card"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 6px;
                font-size: 13px;
            }}
            QListWidget::item {{ padding: 8px; }}
            QListWidget::item:selected {{ background-color: {COLORS["bg_hover"]}; }}
        """
        )
        self._catalogue = catalogue

        outer = QVBoxLayout(self)
        outer.addWidget(_label("Tick the widgets to show on Home. Drag to reorder.", 10, "text_dim"))

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        outer.addWidget(self.list, 1)
        self._fill(layout)

        row = QHBoxLayout()
        for text, step in (("Move up", -1), ("Move down", 1)):
            btn = QPushButton(text)
            btn.setProperty("secondary", True)
            btn.clicked.connect(lambda _checked=False, step=step: self.move_selected(step))
            row.addWidget(btn)
        row.addStretch()
        restore = QPushButton("Restore defaults")
        restore.setProperty("secondary", True)
        restore.clicked.connect(lambda: self._fill(HomeLayout.default()))
        row.addWidget(restore)
        outer.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _fill(self, layout: HomeLayout) -> None:
        specs = {s.id: s for s in self._catalogue}
        self.list.clear()
        for widget_id in [*layout.widgets, *layout.hidden()]:
            spec = specs[widget_id]
            item = QListWidgetItem(f"{spec.title}  ·  {spec.description}")
            item.setData(Qt.ItemDataRole.UserRole, spec.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if spec.id in layout.widgets else Qt.CheckState.Unchecked)
            self.list.addItem(item)

    def move_selected(self, step: int) -> None:
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)

    def chosen(self) -> list[str]:
        """Ticked widget ids, in list order."""
        items = (self.list.item(i) for i in range(self.list.count()))
        return [i.data(Qt.ItemDataRole.UserRole) for i in items if i.checkState() == Qt.CheckState.Checked]


class HomeView(QWidget):
    status_message = Signal(str)
    open_raid = Signal(str)
    open_character = Signal(str)
    open_player_page = Signal(str, str, str)  # name, server, region
    run_action = Signal(str)  # a quick action id, which is also a command palette key

    def __init__(self, service: HomeService | None = None, parent=None):
        super().__init__(parent)
        self._service = service or default_home_service()
        self._worker: _PageWorker | None = None
        self._reload_after = False
        self._loading = False
        self.cards: list[WidgetCard] = []
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(
            COMMON_STYLES
            + f"""
            HomeView, HomeView QScrollArea, HomeView QWidget#homeContent {{
                background-color: {COLORS["bg_dark"]};
            }}
        """
        )
        header = QHBoxLayout()
        header.setContentsMargins(24, 20, 24, 0)
        header.addWidget(_label("Home", 20, "text_gold", bold=True))
        self._updated_label = _label("", 9, "text_dim")
        header.addWidget(self._updated_label)
        header.addStretch()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setProperty("secondary", True)
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn)
        self._customise_btn = QPushButton("Customise")
        self._customise_btn.setToolTip("Choose and order the widgets on Home")
        self._customise_btn.clicked.connect(self.customise)
        header.addWidget(self._customise_btn)

        content = QWidget()
        content.setObjectName("homeContent")
        self._grid = QGridLayout(content)
        self._grid.setContentsMargins(24, 16, 24, 20)
        self._grid.setSpacing(16)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addLayout(header)
        main.addWidget(scroll, 1)

    # ── Loading ──

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """Reload every widget in the background; the current page stays up until the new one arrives."""
        if self._loading:
            self._reload_after = True  # e.g. the layout changed mid-load: load again once this one lands
            return
        self._reload_after = False
        self._loading = True
        self._refresh_btn.setEnabled(False)
        worker = _PageWorker(self._service, self)
        worker.loaded.connect(self.show_page)
        worker.finished.connect(self._on_loaded)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_loaded(self) -> None:
        self._loading = False
        self._worker = None  # the finished worker deletes itself; closeEvent must not touch it
        self._refresh_btn.setEnabled(True)
        if self._reload_after:
            self.refresh()

    def show_page(self, page: HomePage) -> None:
        self._clear()
        row, col = 0, 0
        for widget in page.widgets:
            card = WidgetCard(widget)
            card.link_activated.connect(self.follow)
            card.hide_requested.connect(self.hide_widget)
            if widget.size == "full":
                if col:
                    row, col = row + 1, 0
                self._grid.addWidget(card, row, 0, 1, 2)
                row += 1
            else:
                self._grid.addWidget(card, row, col)
                row, col = (row + 1, 0) if col else (row, 1)
            self.cards.append(card)
        if not page.widgets:
            hint = _label("Home is empty. Use Customise to add widgets.", 11, "text_dim")
            self._grid.addWidget(hint, 0, 0, 1, 2)
        self._grid.setRowStretch(self._grid.rowCount(), 1)
        self._updated_label.setText(f"Updated {page.generated_at[11:16]}")
        failed = [w.title for w in page.widgets if w.error]
        self.status_message.emit(f"Home: could not load {', '.join(failed)}" if failed else "Home loaded")

    def _clear(self) -> None:
        self.cards = []
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)

    # ── Customising ──

    def customise(self) -> None:
        dialog = CustomiseHomeDialog(self._service.catalogue(), self._service.layout(), self)
        if dialog.exec():
            self.apply_layout(dialog.chosen())

    def apply_layout(self, widget_ids: list[str]) -> None:
        self._service.save_layout(widget_ids)
        self.status_message.emit("Home layout saved")
        self.refresh()

    def hide_widget(self, widget_id: str) -> None:
        self.apply_layout([w for w in self._service.layout().widgets if w != widget_id])

    # ── Links ──

    def follow(self, link: Link) -> None:
        params = link.params
        if link.kind == RAID:
            self.open_raid.emit(params["report_id"])
        elif link.kind == CHARACTER:
            self.open_character.emit(params["name"])
        elif link.kind == PLAYER_PAGE:
            self.open_player_page.emit(params["name"], params["server"], params["region"])
        elif link.kind == ACTION:
            self.run_action.emit(params["id"])
