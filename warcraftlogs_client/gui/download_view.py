"""
Download view — fetch guild reports, show download status, batch analyze.
"""

import json
import sqlite3
import webbrowser
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableView, QHeaderView, QCheckBox, QProgressBar,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QModelIndex
from PySide6.QtGui import QFont, QColor

from .styles import COMMON_STYLES, COLORS
from .table_models import HistoryTableModel
from .worker import AnalysisWorker, GuildReportsWorker

import requests

from ..common.errors import WarcraftLogsError


class DownloadView(QWidget):
    status_message = Signal(str)
    raid_downloaded = Signal()
    open_raid = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._guild_reports_raw: list[dict] = []
        self._cached_codes: set[str] = set()
        self._worker = None
        self._batch_queue: list[str] = []
        self._batch_total = 0
        self._auto_fetched = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.setStyleSheet(COMMON_STYLES)

        title = QLabel("Download Raids")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(title)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self._report_input = QLineEdit()
        self._report_input.setPlaceholderText("Paste a report ID to analyze directly...")
        self._report_input.returnPressed.connect(self._analyze_single)
        top_row.addWidget(self._report_input, 1)

        analyze_btn = QPushButton("Analyze")
        analyze_btn.setFixedHeight(36)
        analyze_btn.clicked.connect(self._analyze_single)
        top_row.addWidget(analyze_btn)

        top_row.addSpacing(20)

        self._fetch_btn = QPushButton("Fetch Guild Reports")
        self._fetch_btn.setFixedHeight(36)
        self._fetch_btn.clicked.connect(self._fetch_guild_reports)
        top_row.addWidget(self._fetch_btn)

        layout.addLayout(top_row)

        day_row = QHBoxLayout()
        day_label = QLabel("Filter days:")
        day_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        day_row.addWidget(day_label)

        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        defaults = {2, 3, 6}
        self._day_checkboxes: dict[int, QCheckBox] = {}
        for i, name in enumerate(day_names):
            cb = QCheckBox(name)
            cb.setChecked(i in defaults)
            cb.toggled.connect(self._apply_day_filter)
            self._day_checkboxes[i] = cb
            day_row.addWidget(cb)

        day_row.addStretch()

        self._analyze_selected_btn = QPushButton("Analyze Selected")
        self._analyze_selected_btn.setProperty("secondary", True)
        self._analyze_selected_btn.setFixedHeight(30)
        self._analyze_selected_btn.setEnabled(False)
        self._analyze_selected_btn.clicked.connect(self._analyze_selected)
        day_row.addWidget(self._analyze_selected_btn)

        self._analyze_new_btn = QPushButton("Analyze All New")
        self._analyze_new_btn.setProperty("secondary", True)
        self._analyze_new_btn.setFixedHeight(30)
        self._analyze_new_btn.setEnabled(False)
        self._analyze_new_btn.clicked.connect(self._analyze_all_new)
        day_row.addWidget(self._analyze_new_btn)

        layout.addLayout(day_row)

        self._table_model = HistoryTableModel(checkable=True)
        self._table_model.dataChanged.connect(self._on_check_changed)
        self._table = QTableView()
        self._table.setModel(self._table_model)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.clicked.connect(self._on_click)
        layout.addWidget(self._table, 1)

        progress_row = QHBoxLayout()
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        progress_row.addWidget(self._progress_bar)

        self._progress_label = QLabel()
        self._progress_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        self._progress_label.setVisible(False)
        progress_row.addWidget(self._progress_label)
        layout.addLayout(progress_row)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_cached_codes()
        if self._guild_reports_raw:
            self._apply_day_filter()
        elif not self._auto_fetched:
            try:
                from ..config import load_config
                config = load_config()
                guild_id = config.get("guild_id", 0)
                client_id = config.get("client_id", "")
                if guild_id and client_id:
                    self._auto_fetched = True
                    self._fetch_guild_reports()
            except (FileNotFoundError, json.JSONDecodeError, KeyError):
                pass

    def _fetch_guild_reports(self):
        try:
            from ..config import load_config
            config = load_config()
            guild_id = config.get("guild_id", 774065)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            guild_id = 774065

        self._fetch_btn.setEnabled(False)
        self.status_message.emit("Fetching guild reports...")

        self._guild_worker = GuildReportsWorker(guild_id)
        self._guild_worker.finished.connect(self._on_guild_loaded)
        self._guild_worker.error.connect(self._on_guild_error)
        self._guild_worker.start()

    def _on_guild_loaded(self, reports: list):
        self._fetch_btn.setEnabled(True)
        self._guild_reports_raw = reports
        self._refresh_cached_codes()
        self._apply_day_filter()
        self.status_message.emit(f"Loaded {len(reports)} guild reports")

    def _on_guild_error(self, error_msg: str):
        self._fetch_btn.setEnabled(True)
        self.status_message.emit(f"Failed to fetch: {error_msg}")

    def _refresh_cached_codes(self):
        try:
            from ..database import PerformanceDB
            with PerformanceDB() as db:
                self._cached_codes = db.get_imported_report_codes()
        except (sqlite3.Error, OSError):
            self._cached_codes = set()

    def _apply_day_filter(self):
        allowed_days = {i for i, cb in self._day_checkboxes.items() if cb.isChecked()}

        display_rows = []
        new_count = 0
        for r in self._guild_reports_raw:
            start = r.get("start_time", 0)
            if not start:
                continue
            dt = datetime.fromtimestamp(start / 1000)
            if dt.weekday() not in allowed_days:
                continue
            code = r.get("code", "")
            is_saved = code in self._cached_codes
            if not is_saved:
                new_count += 1
            display_rows.append({
                "date": dt.strftime("%Y-%m-%d %H:%M"),
                "day": dt.strftime("%a"),
                "title": r.get("title", ""),
                "owner": r.get("owner", ""),
                "zone": r.get("zone", ""),
                "code": code,
                "status": "Downloaded" if is_saved else "",
            })
            if len(display_rows) >= 50:
                break

        self._table_model.set_data(
            display_rows,
            ["date", "day", "title", "owner", "zone", "code", "status"],
        )
        self._analyze_new_btn.setEnabled(new_count > 0)
        self._analyze_new_btn.setText(f"Analyze All New ({new_count})" if new_count else "Analyze All New")
        self._analyze_selected_btn.setEnabled(False)

    def _on_click(self, index: QModelIndex):
        rows = self._table_model._rows
        if index.row() >= len(rows):
            return
        col_idx = index.column() - 1 if self._table_model._checkable else index.column()
        if col_idx < 0 or col_idx >= len(self._table_model._columns):
            return
        col_name = self._table_model._columns[col_idx]
        if col_name == "code":
            code = rows[index.row()].get("code", "")
            if code:
                try:
                    from ..config import load_config
                    api_url = load_config().get("wcl_api_url", "")
                except (FileNotFoundError, json.JSONDecodeError, KeyError):
                    api_url = ""
                base = "https://fresh.warcraftlogs.com" if "fresh." in api_url else "https://www.warcraftlogs.com"
                webbrowser.open(f"{base}/reports/{code}")
        else:
            code = rows[index.row()].get("code", "")
            if code:
                self._report_input.setText(code)

    def _on_check_changed(self):
        selected = self._table_model.checked_rows()
        count = len(selected)
        self._analyze_selected_btn.setEnabled(count > 0)
        self._analyze_selected_btn.setText(
            f"Analyze Selected ({count})" if count else "Analyze Selected"
        )

    def _analyze_selected(self):
        selected = self._table_model.checked_rows()
        codes = [r["code"] for r in selected if r.get("code")]
        if codes:
            self._start_batch(codes)

    def _on_double_click(self, index: QModelIndex):
        rows = self._table_model._rows
        if index.row() >= len(rows):
            return
        row = rows[index.row()]
        code = row.get("code", "")
        if not code:
            return
        if row.get("status") == "Downloaded":
            self.open_raid.emit(code)
        else:
            self._start_batch([code])

    def _analyze_single(self):
        report_id = self._report_input.text().strip()
        if not report_id:
            return
        self._start_batch([report_id])

    def _analyze_all_new(self):
        rows = self._table_model._rows
        new_codes = [r["code"] for r in rows if r.get("status") != "Downloaded" and r.get("code")]
        if not new_codes:
            return
        self._start_batch(new_codes)

    def _start_batch(self, codes: list[str]):
        self._batch_queue = list(codes)
        self._batch_total = len(codes)
        self._progress_bar.setVisible(True)
        self._progress_bar.setMaximum(self._batch_total)
        self._progress_bar.setValue(0)
        self._progress_label.setVisible(True)
        self._fetch_btn.setEnabled(False)
        self._analyze_new_btn.setEnabled(False)
        self._run_next_in_batch()

    def _run_next_in_batch(self):
        if not self._batch_queue:
            self._on_batch_complete()
            return

        code = self._batch_queue.pop(0)
        done = self._batch_total - len(self._batch_queue) - 1
        self._progress_bar.setValue(done)
        self._progress_label.setText(f"Analyzing {done + 1}/{self._batch_total}: {code}")
        self.status_message.emit(f"Analyzing {code}...")

        self._worker = AnalysisWorker(code)
        self._worker.progress.connect(lambda msg: self._progress_label.setText(
            f"[{self._batch_total - len(self._batch_queue)}/{self._batch_total}] {msg}"
        ))
        self._worker.finished.connect(self._on_analysis_finished)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _on_analysis_finished(self, analysis):
        try:
            from ..database import PerformanceDB
            with PerformanceDB() as db:
                db.import_raid(analysis)
        except (sqlite3.Error, OSError) as e:
            self.status_message.emit(f"DB save failed: {e}")

        enc_count = len(analysis.encounters) if analysis.encounters else 0
        report_id = analysis.metadata.report_id
        title = analysis.metadata.title
        self.status_message.emit(
            f"Saved: {title} ({report_id}) — {enc_count} encounters")

        self._refresh_cached_codes()
        self._apply_day_filter()
        self.raid_downloaded.emit()
        self._run_next_in_batch()

    def _on_analysis_error(self, error_msg: str):
        code = self._batch_total - len(self._batch_queue)
        self.status_message.emit(f"Analysis failed ({code}/{self._batch_total}): {error_msg}")
        self._run_next_in_batch()

    def _on_batch_complete(self):
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        self._fetch_btn.setEnabled(True)
        self._refresh_cached_codes()
        self._apply_day_filter()
        done = self._batch_total
        self._batch_total = 0
        if done > 1:
            self.status_message.emit(f"Batch complete: {done} report(s) processed")
