"""
Player Page view — a character's own collection of reports.

Look a character up, discover the Warcraft Logs reports they appear in, and add
the ones they want to their page. All logic lives in services.player_page so the
CLI and web frontends behave the same; this view only wires it to widgets.
"""

import json
import os
import sqlite3

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import paths as _paths
from ..services import AppContext
from ..services.player_page import (
    API_ERRORS,
    NEW,
    ON_PAGE,
    PlayerLog,
    PlayerPageService,
    PlayerRef,
)
from .styles import COLORS, COMMON_STYLES

_COLUMNS = ["Date", "Title", "Zone", "Owner", "Status", "Imported", "Code"]
_STATUS_LABELS = {NEW: "New", ON_PAGE: "On page", "dismissed": "Dismissed"}


class _DiscoverWorker(QThread):
    finished = Signal(list, list)  # discovered logs, page logs
    error = Signal(str)

    def __init__(self, player: PlayerRef, parent=None):
        super().__init__(parent)
        self.player = player

    def run(self):
        try:
            ctx = AppContext.from_config_file()
            with ctx.db() as db:
                service = PlayerPageService.from_context(ctx, db)
                found = service.discover_reports(self.player)
                page = service.get_page(self.player)
            self.finished.emit(found, page.logs)
        except (*API_ERRORS, sqlite3.Error) as e:
            self.error.emit(str(e))


class _AddWorker(QThread):
    progress = Signal(str)
    finished = Signal(list)  # AddResult list
    error = Signal(str)

    def __init__(self, player: PlayerRef, refs: list[str], known: dict[str, PlayerLog], parent=None):
        super().__init__(parent)
        self.player = player
        self.refs = refs
        self.known = known

    def run(self):
        try:
            ctx = AppContext.from_config_file()
            with ctx.db() as db:
                service = PlayerPageService.from_context(ctx, db)
                results = service.add_reports(self.player, self.refs, known=self.known, progress=self.progress.emit)
            self.finished.emit(results)
        except (*API_ERRORS, sqlite3.Error) as e:
            self.error.emit(str(e))


class PlayerPageView(QWidget):
    status_message = Signal(str)
    open_report = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMMON_STYLES)
        self._player: PlayerRef | None = None
        self._discovered: list[PlayerLog] = []
        self._worker: QThread | None = None
        self._build_ui()
        self._prefill_from_config()

    # ── UI ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Player Page")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(title)

        lookup = QHBoxLayout()
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Character")
        self._server_input = QLineEdit()
        self._server_input.setPlaceholderText("Server, e.g. spineshatter")
        self._region_input = QLineEdit()
        self._region_input.setPlaceholderText("Region")
        self._region_input.setFixedWidth(70)
        for w in (self._name_input, self._server_input, self._region_input):
            w.returnPressed.connect(self._discover)
        lookup.addWidget(self._name_input, 2)
        lookup.addWidget(self._server_input, 2)
        lookup.addWidget(self._region_input)
        self._discover_btn = QPushButton("Find My Logs")
        self._discover_btn.setFixedHeight(36)
        self._discover_btn.clicked.connect(self._discover)
        lookup.addWidget(self._discover_btn)
        layout.addLayout(lookup)

        self._summary = QLabel("Enter a character to find the reports they appear in.")
        self._summary.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        layout.addWidget(self._summary)

        # ── On the page ──
        layout.addWidget(self._section_label("On your page"))
        self._page_table = self._make_table()
        self._page_table.doubleClicked.connect(lambda idx: self._open_row(self._page_table, idx.row()))
        layout.addWidget(self._page_table, 2)

        page_actions = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("Paste a report URL or code to add it...")
        self._url_input.returnPressed.connect(self._add_by_url)
        page_actions.addWidget(self._url_input, 1)
        self._add_url_btn = QPushButton("Add Report")
        self._add_url_btn.setProperty("secondary", True)
        self._add_url_btn.clicked.connect(self._add_by_url)
        page_actions.addWidget(self._add_url_btn)
        self._remove_btn = QPushButton("Remove Selected")
        self._remove_btn.setProperty("secondary", True)
        self._remove_btn.clicked.connect(self._remove_selected)
        page_actions.addWidget(self._remove_btn)
        layout.addLayout(page_actions)

        # ── Discovered ──
        layout.addWidget(self._section_label("Found in Warcraft Logs and your database"))
        self._found_table = self._make_table()
        self._found_table.doubleClicked.connect(lambda idx: self._open_row(self._found_table, idx.row()))
        layout.addWidget(self._found_table, 3)

        found_actions = QHBoxLayout()
        found_actions.addStretch()
        self._dismiss_btn = QPushButton("Dismiss Selected")
        self._dismiss_btn.setProperty("secondary", True)
        self._dismiss_btn.clicked.connect(self._dismiss_selected)
        found_actions.addWidget(self._dismiss_btn)
        self._add_selected_btn = QPushButton("Add Selected")
        self._add_selected_btn.clicked.connect(self._add_selected)
        found_actions.addWidget(self._add_selected_btn)
        self._add_new_btn = QPushButton("Add All New")
        self._add_new_btn.clicked.connect(self._add_all_new)
        found_actions.addWidget(self._add_new_btn)
        layout.addLayout(found_actions)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._set_page_actions_enabled(False)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {COLORS['text_gold']};")
        return label

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_COLUMNS))
        table.setHorizontalHeaderLabels(_COLUMNS)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        return table

    def _fill_table(self, table: QTableWidget, logs: list[PlayerLog]) -> None:
        table.setRowCount(len(logs))
        for row, log in enumerate(logs):
            values = [
                log.date_formatted,
                log.title,
                log.zone,
                log.owner or log.guild,
                _STATUS_LABELS.get(log.status, log.status),
                "Yes" if log.imported else "No",
                log.code,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 4 and log.status == NEW:
                    item.setForeground(QColor(COLORS["accent"]))
                table.setItem(row, col, item)

    def _set_page_actions_enabled(self, enabled: bool) -> None:
        for w in (
            self._url_input,
            self._add_url_btn,
            self._remove_btn,
            self._dismiss_btn,
            self._add_selected_btn,
            self._add_new_btn,
        ):
            w.setEnabled(enabled)

    def _set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._discover_btn.setEnabled(not busy)
        self._set_page_actions_enabled(not busy and self._player is not None)

    # ── Config ──

    def _prefill_from_config(self):
        """Start from the My Character settings so a player sees their own page first."""
        config_path = str(_paths.get_config_path())
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        self._name_input.setText(config.get("character_name", ""))
        self._server_input.setText(config.get("character_server", config.get("default_server", "")))
        self._region_input.setText(config.get("character_region", config.get("default_region", "eu")))

    # ── Actions ──

    def _read_player(self) -> PlayerRef | None:
        try:
            return PlayerRef.create(
                self._name_input.text(), self._server_input.text(), self._region_input.text() or "eu"
            )
        except ValueError as e:
            self.status_message.emit(str(e))
            return None

    def _discover(self):
        player = self._read_player()
        if player is None or (self._worker and self._worker.isRunning()):
            return
        self._player = player
        self._set_busy(True)
        self.status_message.emit(f"Finding reports for {player.label}...")
        worker = _DiscoverWorker(player, self)
        worker.finished.connect(self._on_discovered)
        worker.error.connect(self._on_error)
        self._worker = worker
        worker.start()

    def _on_discovered(self, found: list, page_logs: list):
        self._set_busy(False)
        # Dismissed reports stay hidden; the page table already lists what's on the page.
        self._discovered = [log for log in found if log.status != "dismissed"]
        self._fill_table(self._found_table, self._discovered)
        self._fill_table(self._page_table, page_logs)
        new = sum(1 for log in self._discovered if log.status == NEW)
        assert self._player is not None
        self._summary.setText(
            f"{self._player.label}: {len(page_logs)} on your page, {len(self._discovered)} found, {new} new"
        )
        self.status_message.emit(f"Found {len(self._discovered)} reports for {self._player.name}")

    def _on_error(self, message: str):
        self._set_busy(False)
        self.status_message.emit(f"Player page error: {message}")
        self._summary.setText(message)

    def _selected_codes(self, table: QTableWidget) -> list[str]:
        rows = sorted({i.row() for i in table.selectedIndexes()})
        return [table.item(r, len(_COLUMNS) - 1).text() for r in rows if table.item(r, len(_COLUMNS) - 1)]

    def _start_add(self, refs: list[str]):
        if not refs or self._player is None or (self._worker and self._worker.isRunning()):
            return
        known = {log.code: log for log in self._discovered if log.code in refs}
        self._set_busy(True)
        worker = _AddWorker(self._player, refs, known, self)
        worker.progress.connect(self.status_message)
        worker.finished.connect(self._on_added)
        worker.error.connect(self._on_error)
        self._worker = worker
        worker.start()

    def _on_added(self, results: list):
        self._set_busy(False)
        added = sum(1 for r in results if r.ok)
        problems = [f"{r.code}: {r.message}" for r in results if not r.ok]
        msg = f"Added {added} of {len(results)} report(s)"
        if problems:
            msg += " — " + "; ".join(problems[:3])
        self.status_message.emit(msg)
        self._discover()

    def _add_selected(self):
        self._start_add(self._selected_codes(self._found_table))

    def _add_all_new(self):
        self._start_add([log.code for log in self._discovered if log.status == NEW])

    def _add_by_url(self):
        text = self._url_input.text().strip()
        if text:
            self._url_input.clear()
            self._start_add([text])

    def _with_service(self, action) -> None:
        if self._player is None:
            return
        try:
            ctx = AppContext.from_config_file()
            with ctx.db() as db:
                action(PlayerPageService.from_context(ctx, db, with_api=False), self._player)
        except (*API_ERRORS, sqlite3.Error) as e:
            self.status_message.emit(f"Player page error: {e}")
            return
        self._discover()

    def _remove_selected(self):
        codes = self._selected_codes(self._page_table)
        if codes:
            self._with_service(lambda service, player: service.remove(player, codes))

    def _dismiss_selected(self):
        codes = self._selected_codes(self._found_table)
        if codes:
            self._with_service(lambda service, player: service.dismiss(player, codes))

    def _open_row(self, table: QTableWidget, row: int):
        code_item = table.item(row, len(_COLUMNS) - 1)
        imported_item = table.item(row, 5)
        if code_item and imported_item and imported_item.text() == "Yes":
            self.open_report.emit(code_item.text())
        elif code_item:
            self.status_message.emit("Add this report to your page to import and open it")
