"""
Reference Reports view — import non-guild reports, manage them,
and compare guild vs reference performance.
"""

import sqlite3
from collections import defaultdict
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableView, QHeaderView, QTabWidget, QComboBox,
    QMessageBox, QGridLayout, QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex, QThread
from PySide6.QtGui import QFont, QColor

from .styles import COMMON_STYLES, COLORS
from .worker import ReferenceAnalysisWorker
from ..database import PerformanceDB
from ..user_auth import UserTokenManager, start_oauth_flow


class _ReferenceRaidModel(QAbstractTableModel):
    HEADERS = ["Date", "Title", "Zone", "Label", "Size", "Report ID"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("raid_date", "")[:10]
            elif col == 1:
                return row.get("title", "")
            elif col == 2:
                return row.get("zone", "") or ""
            elif col == 3:
                return row.get("label", "") or ""
            elif col == 4:
                size = row.get("raid_size")
                return str(size) if size else ""
            elif col == 5:
                return row.get("report_id", "")
        elif role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS["text"])
        return None

    def get_report_id(self, row_index: int) -> str:
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index].get("report_id", "")
        return ""


class _MetricCard(QFrame):
    """A small card showing a label, guild value, reference value, and delta."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 12px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        lbl = QLabel(title)
        lbl.setFont(QFont("Segoe UI", 10))
        lbl.setStyleSheet(f"color: {COLORS['text_dim']}; border: none;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        self._guild_lbl = QLabel("—")
        self._guild_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self._guild_lbl.setStyleSheet(f"color: {COLORS['accent']}; border: none;")
        self._guild_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._guild_lbl)

        self._ref_lbl = QLabel("—")
        self._ref_lbl.setFont(QFont("Segoe UI", 14))
        self._ref_lbl.setStyleSheet(f"color: {COLORS['text']}; border: none;")
        self._ref_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._ref_lbl)

        self._delta_lbl = QLabel("")
        self._delta_lbl.setFont(QFont("Segoe UI", 10))
        self._delta_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._delta_lbl.setStyleSheet("border: none;")
        layout.addWidget(self._delta_lbl)

    def set_values(self, guild_val, ref_val, fmt: str = "{:,.0f}",
                   higher_is_better: bool = True):
        if guild_val is not None:
            self._guild_lbl.setText(f"Guild: {fmt.format(guild_val)}")
        else:
            self._guild_lbl.setText("Guild: —")

        if ref_val is not None:
            self._ref_lbl.setText(f"Ref: {fmt.format(ref_val)}")
        else:
            self._ref_lbl.setText("Ref: —")

        if guild_val is not None and ref_val is not None and ref_val != 0:
            delta_pct = (guild_val - ref_val) / abs(ref_val) * 100
            is_positive = (delta_pct > 0) == higher_is_better
            color = COLORS["success"] if is_positive else COLORS["error"]
            sign = "+" if delta_pct > 0 else ""
            self._delta_lbl.setText(f"{sign}{delta_pct:.1f}%")
            self._delta_lbl.setStyleSheet(f"color: {color}; border: none;")
        else:
            self._delta_lbl.setText("")


class _EncounterComparisonModel(QAbstractTableModel):
    HEADERS = [
        "Boss", "Guild Kills", "Ref Kills",
        "Guild Avg Duration", "Ref Avg Duration",
        "Guild Avg Damage", "Ref Avg Damage",
        "Guild Avg Healing", "Ref Avg Healing",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("name", "")
            g = row.get("guild", {})
            r = row.get("reference", {})
            if col == 1:
                return str(g.get("kill_count", 0) or 0)
            elif col == 2:
                return str(r.get("kill_count", 0) or 0)
            elif col == 3:
                return self._fmt_duration(g.get("avg_duration"))
            elif col == 4:
                return self._fmt_duration(r.get("avg_duration"))
            elif col == 5:
                return self._fmt_number(g.get("avg_damage"))
            elif col == 6:
                return self._fmt_number(r.get("avg_damage"))
            elif col == 7:
                return self._fmt_number(g.get("avg_healing"))
            elif col == 8:
                return self._fmt_number(r.get("avg_healing"))
        elif role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS["text"])
        return None

    @staticmethod
    def _fmt_duration(ms):
        if ms is None:
            return "—"
        secs = int(ms / 1000)
        return f"{secs // 60}:{secs % 60:02d}"

    @staticmethod
    def _fmt_number(val):
        if val is None:
            return "—"
        return f"{val:,.0f}"


class _AuthWaitThread(QThread):
    """Waits for OAuth callback server result in a background thread."""
    auth_complete = Signal(str)
    auth_error = Signal(str)

    def __init__(self, server, expected_state, parent=None):
        super().__init__(parent)
        self._server = server
        self._expected_state = expected_state

    def run(self):
        result = self._server.wait()
        self._server.shutdown()

        if result is None:
            self.auth_error.emit("Authentication timed out — please try again.")
            return

        error = result.get("error")
        if error:
            self.auth_error.emit(f"WarcraftLogs denied access: {error}")
            return

        code = result.get("code")
        state = result.get("state")
        if state != self._expected_state:
            self.auth_error.emit("OAuth state mismatch — possible CSRF. Please try again.")
            return

        if not code:
            self.auth_error.emit("No authorization code received.")
            return

        self.auth_complete.emit(code)


class ReferenceView(QWidget):
    status_message = Signal(str)
    open_raid = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet(COMMON_STYLES)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
                background-color: {COLORS['bg_dark']};
            }}
            QTabBar::tab {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_dim']};
                padding: 10px 24px;
                border: none;
                font-size: 13px;
            }}
            QTabBar::tab:selected {{
                background-color: {COLORS['bg_dark']};
                color: {COLORS['text_header']};
                border-bottom: 2px solid {COLORS['accent']};
            }}
        """)

        self._tabs.addTab(self._build_manage_tab(), "Manage")
        self._tabs.addTab(self._build_comparison_tab(), "Guild vs Reference")
        self._tabs.addTab(self._build_head_to_head_tab(), "Head-to-Head")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self._tabs)

    # ── Manage tab ──

    def _build_manage_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Reference Reports")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(title)

        desc = QLabel(
            "Import reports from other guilds for benchmarking. "
            "These will NOT appear in your guild's raids, characters, or insights."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        layout.addWidget(desc)

        # Auth status row
        auth_row = QHBoxLayout()
        auth_row.setSpacing(8)
        self._auth_status = QLabel("")
        self._auth_status.setStyleSheet(f"font-size: 12px;")
        auth_row.addWidget(self._auth_status)
        self._auth_btn = QPushButton("Authenticate")
        self._auth_btn.setFixedHeight(28)
        self._auth_btn.setFixedWidth(140)
        self._auth_btn.clicked.connect(self._start_auth)
        auth_row.addWidget(self._auth_btn)
        auth_row.addStretch()
        layout.addLayout(auth_row)
        self._update_auth_status()

        import_row = QHBoxLayout()
        import_row.setSpacing(10)

        self._report_input = QLineEdit()
        self._report_input.setPlaceholderText("Paste a WarcraftLogs report ID...")
        self._report_input.returnPressed.connect(self._import_reference)
        import_row.addWidget(self._report_input, 2)

        self._label_input = QLineEdit()
        self._label_input.setPlaceholderText("Label (optional, e.g. 'Top guild Kara')")
        import_row.addWidget(self._label_input, 1)

        self._import_btn = QPushButton("Import as Reference")
        self._import_btn.setFixedHeight(36)
        self._import_btn.clicked.connect(self._import_reference)
        import_row.addWidget(self._import_btn)

        layout.addLayout(import_row)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 12px; font-weight: bold;")
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        self._ref_model = _ReferenceRaidModel()
        self._ref_table = QTableView()
        self._ref_table.setModel(self._ref_model)
        self._ref_table.setAlternatingRowColors(True)
        self._ref_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._ref_table.verticalHeader().setVisible(False)
        self._ref_table.horizontalHeader().setStretchLastSection(True)
        self._ref_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self._ref_table.doubleClicked.connect(self._on_raid_double_clicked)
        layout.addWidget(self._ref_table, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        delete_btn = QPushButton("Delete Selected")
        delete_btn.setProperty("secondary", True)
        delete_btn.setFixedHeight(30)
        delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(delete_btn)

        layout.addLayout(btn_row)

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(self._summary_label)

        return tab

    # ── Comparison tab ──

    def _build_comparison_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Guild vs Reference Comparison")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(title)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        filter_row.addWidget(QLabel("Zone:"))
        self._zone_combo = QComboBox()
        self._zone_combo.addItem("All Zones")
        self._zone_combo.setMinimumWidth(150)
        self._zone_combo.currentIndexChanged.connect(self._refresh_comparison)
        filter_row.addWidget(self._zone_combo)

        filter_row.addWidget(QLabel("Raid Size:"))
        self._size_combo = QComboBox()
        self._size_combo.addItems(["All Sizes", "25-man", "10-man"])
        self._size_combo.currentIndexChanged.connect(self._refresh_comparison)
        filter_row.addWidget(self._size_combo)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.setFixedHeight(30)
        refresh_btn.clicked.connect(self._refresh_comparison)
        filter_row.addWidget(refresh_btn)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Metric cards
        cards_grid = QGridLayout()
        cards_grid.setSpacing(12)

        self._card_dps = _MetricCard("Avg DPS per Player")
        self._card_healing = _MetricCard("Avg Healing per Healer")
        self._card_overheal = _MetricCard("Avg Overheal %")
        self._card_mitigation = _MetricCard("Avg Tank Mitigation %")
        self._card_raids = _MetricCard("Raids Analyzed")

        cards_grid.addWidget(self._card_dps, 0, 0)
        cards_grid.addWidget(self._card_healing, 0, 1)
        cards_grid.addWidget(self._card_overheal, 0, 2)
        cards_grid.addWidget(self._card_mitigation, 1, 0)
        cards_grid.addWidget(self._card_raids, 1, 1)

        layout.addLayout(cards_grid)

        # Encounter comparison table
        enc_label = QLabel("Per-Encounter Comparison (shared bosses)")
        enc_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        enc_label.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(enc_label)

        self._encounter_model = _EncounterComparisonModel()
        self._encounter_table = QTableView()
        self._encounter_table.setModel(self._encounter_model)
        self._encounter_table.setAlternatingRowColors(True)
        self._encounter_table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows)
        self._encounter_table.verticalHeader().setVisible(False)
        self._encounter_table.horizontalHeader().setStretchLastSection(True)
        self._encounter_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._encounter_table, 1)

        self._no_data_label = QLabel(
            "Import reference reports in the Manage tab to see comparison data.")
        self._no_data_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 13px;")
        self._no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._no_data_label)

        return tab

    # ── Events ──

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_manage_tab()

    def _on_tab_changed(self, index):
        if index == 0:
            self._refresh_manage_tab()
        elif index == 1:
            self._refresh_zone_combos()
            self._refresh_comparison()
        elif index == 2:
            self._h2h_panel.populate_combos()

    # ── Head-to-Head tab ──

    def _build_head_to_head_tab(self) -> QWidget:
        self._h2h_panel = _HeadToHeadPanel()
        self._h2h_panel.status_message.connect(self.status_message.emit)
        return self._h2h_panel

    # ── Manage actions ──

    @staticmethod
    def _extract_report_id(text: str) -> str:
        text = text.strip()
        if "/" in text:
            parts = text.rstrip("/").split("/")
            return parts[-1].split("#")[0]
        return text

    def _import_reference(self):
        raw = self._report_input.text().strip()
        if not raw:
            return

        report_id = self._extract_report_id(raw)
        if not report_id:
            return

        try:
            with PerformanceDB() as db:
                existing_source = db.get_raid_source(report_id)
                if existing_source:
                    QMessageBox.warning(
                        self, "Already Imported",
                        f"Report {report_id} is already imported as a "
                        f"{existing_source} report.")
                    return
        except (sqlite3.Error, OSError):
            pass

        user_tm = UserTokenManager()
        if not user_tm.is_authenticated():
            reply = QMessageBox.question(
                self, "Authentication Required",
                "WarcraftLogs user authentication is required to access "
                "other guilds' report data.\n\n"
                "Click Yes to open your browser and authenticate.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._pending_report_id = report_id
                self._start_auth()
            return

        self._start_import(report_id)

    def _start_import(self, report_id: str):
        self._set_importing(True, f"Downloading report {report_id}...")
        self._worker = ReferenceAnalysisWorker(report_id)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.auth_required.connect(self._on_auth_required)
        self._worker.start()

    def _on_auth_required(self):
        self._set_importing(False)
        QMessageBox.warning(
            self, "Authentication Required",
            "Your WarcraftLogs session has expired.\n"
            "Please authenticate again using the button above.")

    def _set_importing(self, busy: bool, message: str = ""):
        self._import_btn.setEnabled(not busy)
        self._import_btn.setText("Importing..." if busy else "Import as Reference")
        self._progress_label.setVisible(busy)
        self._progress_label.setText(message)

    def _on_progress(self, message: str):
        self._progress_label.setText(message)

    def _on_analysis_done(self, analysis):
        self._progress_label.setText("Saving to database...")
        try:
            with PerformanceDB() as db:
                db.import_raid(analysis, source="reference")
                label = self._label_input.text().strip()
                if label:
                    db.update_raid_label(analysis.metadata.report_id, label)
        except (sqlite3.Error, OSError) as e:
            self._set_importing(False)
            self.status_message.emit(f"Import failed: {e}")
            return

        self._set_importing(False)
        self._report_input.clear()
        self._label_input.clear()
        self._refresh_manage_tab()
        enc_count = len(analysis.encounters) if analysis.encounters else 0
        healer_count = len(analysis.healers)
        dps_count = len(analysis.dps)
        tank_count = len(analysis.tanks)
        self.status_message.emit(
            f"Imported '{analysis.metadata.title}' — "
            f"{healer_count} healers, {tank_count} tanks, {dps_count} DPS, "
            f"{enc_count} encounters")

    def _on_analysis_error(self, error_msg: str):
        self._set_importing(False)
        self.status_message.emit(f"Analysis failed: {error_msg}")
        QMessageBox.warning(self, "Import Failed",
                            f"Failed to download report:\n{error_msg}")

    # ── Auth flow ──

    def _update_auth_status(self):
        user_tm = UserTokenManager()
        if user_tm.is_authenticated():
            self._auth_status.setText("Authenticated with WarcraftLogs")
            self._auth_status.setStyleSheet(f"color: {COLORS['success']}; font-size: 12px;")
            self._auth_btn.setText("Disconnect")
        else:
            self._auth_status.setText("Not authenticated — required for importing reference reports")
            self._auth_status.setStyleSheet(f"color: {COLORS['error']}; font-size: 12px;")
            self._auth_btn.setText("Authenticate")

    def _start_auth(self):
        user_tm = UserTokenManager()
        if user_tm.is_authenticated():
            user_tm.revoke()
            self._update_auth_status()
            self.status_message.emit("Disconnected from WarcraftLogs")
            return

        try:
            from ..config import load_config
            config = load_config()
            client_id = config["client_id"]
        except Exception as e:
            QMessageBox.warning(self, "Configuration Error",
                                f"Could not load API credentials:\n{e}")
            return

        self._auth_btn.setEnabled(False)
        self._auth_btn.setText("Waiting...")
        self.status_message.emit("Opening browser for WarcraftLogs authentication...")

        self._oauth_server, self._oauth_state = start_oauth_flow(client_id)

        self._auth_wait_thread = _AuthWaitThread(
            self._oauth_server, self._oauth_state)
        self._auth_wait_thread.auth_complete.connect(self._on_auth_complete)
        self._auth_wait_thread.auth_error.connect(self._on_auth_error)
        self._auth_wait_thread.start()

    def _on_auth_complete(self, code: str):
        try:
            from ..config import load_config
            config = load_config()
            user_tm = UserTokenManager()
            user_tm.complete_auth(code, config["client_id"], config["client_secret"])
        except Exception as e:
            self._auth_btn.setEnabled(True)
            self._update_auth_status()
            QMessageBox.warning(self, "Authentication Failed",
                                f"Token exchange failed:\n{e}")
            return

        self._auth_btn.setEnabled(True)
        self._update_auth_status()
        self.status_message.emit("Successfully authenticated with WarcraftLogs!")

        pending = getattr(self, "_pending_report_id", None)
        if pending:
            self._pending_report_id = None
            self._start_import(pending)

    def _on_auth_error(self, error: str):
        self._auth_btn.setEnabled(True)
        self._update_auth_status()
        self.status_message.emit(f"Authentication failed: {error}")
        QMessageBox.warning(self, "Authentication Failed", error)

    def _on_raid_double_clicked(self, index):
        report_id = self._ref_model.get_report_id(index.row())
        if report_id:
            self.open_raid.emit(report_id)

    def _delete_selected(self):
        indexes = self._ref_table.selectionModel().selectedRows()
        if not indexes:
            return
        report_id = self._ref_model.get_report_id(indexes[0].row())
        if not report_id:
            return

        reply = QMessageBox.question(
            self, "Delete Reference Report",
            f"Delete reference report {report_id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            with PerformanceDB() as db:
                db.delete_raid(report_id)
        except (sqlite3.Error, OSError) as e:
            self.status_message.emit(f"Delete failed: {e}")
            return

        self._refresh_manage_tab()
        self.status_message.emit(f"Reference report {report_id} deleted.")

    def _refresh_manage_tab(self):
        try:
            with PerformanceDB() as db:
                raids = db.get_reference_raids()
        except (sqlite3.Error, OSError):
            raids = []

        self._ref_model.set_data(raids)
        count = len(raids)
        if count:
            dates = [r.get("raid_date", "")[:10] for r in raids if r.get("raid_date")]
            date_range = f"{min(dates)} to {max(dates)}" if dates else ""
            self._summary_label.setText(
                f"{count} reference report{'s' if count != 1 else ''} | {date_range}")
        else:
            self._summary_label.setText("No reference reports imported yet.")

    # ── Comparison actions ──

    def _refresh_zone_combos(self):
        current = self._zone_combo.currentText()
        self._zone_combo.blockSignals(True)
        self._zone_combo.clear()
        self._zone_combo.addItem("All Zones")

        try:
            with PerformanceDB() as db:
                guild_zones = set(db.get_distinct_zones("guild"))
                ref_zones = set(db.get_distinct_zones("reference"))
                common_zones = sorted(guild_zones & ref_zones)
                all_zones = sorted(guild_zones | ref_zones)
                for z in all_zones:
                    suffix = "" if z in common_zones else " (one side only)"
                    self._zone_combo.addItem(z + suffix)
        except (sqlite3.Error, OSError):
            pass

        idx = self._zone_combo.findText(current)
        if idx >= 0:
            self._zone_combo.setCurrentIndex(idx)
        self._zone_combo.blockSignals(False)

    def _refresh_comparison(self):
        zone_text = self._zone_combo.currentText()
        zone = None
        if zone_text and zone_text != "All Zones":
            zone = zone_text.replace(" (one side only)", "")

        size_text = self._size_combo.currentText()
        raid_size = None if size_text == "All Sizes" else size_text

        try:
            with PerformanceDB() as db:
                guild = db.get_comparison_aggregates("guild", zone=zone, raid_size=raid_size)
                ref = db.get_comparison_aggregates("reference", zone=zone, raid_size=raid_size)
        except (sqlite3.Error, OSError):
            guild = {"raid_count": 0}
            ref = {"raid_count": 0}

        has_data = guild.get("raid_count", 0) > 0 and ref.get("raid_count", 0) > 0
        self._no_data_label.setVisible(not has_data)

        self._card_dps.set_values(
            guild.get("avg_damage"), ref.get("avg_damage"))
        self._card_healing.set_values(
            guild.get("avg_healing"), ref.get("avg_healing"))
        self._card_overheal.set_values(
            guild.get("avg_overheal"), ref.get("avg_overheal"),
            fmt="{:.1f}%", higher_is_better=False)
        self._card_mitigation.set_values(
            guild.get("avg_mitigation"), ref.get("avg_mitigation"),
            fmt="{:.1f}%")
        self._card_raids.set_values(
            guild.get("raid_count"), ref.get("raid_count"),
            fmt="{:.0f}", higher_is_better=True)

        self._refresh_encounter_table()

    def _refresh_encounter_table(self):
        try:
            with PerformanceDB() as db:
                common = db.get_common_encounters()
                rows = []
                for enc in common:
                    comparison = db.get_encounter_comparison(enc["encounter_id"])
                    rows.append({
                        "name": enc["name"],
                        "guild": comparison.get("guild", {}),
                        "reference": comparison.get("reference", {}),
                    })
        except (sqlite3.Error, OSError):
            rows = []

        self._encounter_model.set_data(rows)


# ── Head-to-Head comparison helpers ──

def _compute_class_performance(analysis):
    """Aggregate performance by (class, role) from a RaidAnalysis."""
    by_class_role = defaultdict(list)
    for h in analysis.healers:
        by_class_role[(h.player_class, "healer")].append(h.total_healing)
    for t in analysis.tanks:
        by_class_role[(t.player_class, "tank")].append(t.mitigation_percent)
    for d in analysis.dps:
        by_class_role[(d.player_class, d.role)].append(d.total_damage)

    results = []
    for (cls, role), values in sorted(by_class_role.items()):
        results.append({
            "class": cls,
            "role": role,
            "count": len(values),
            "avg_metric": sum(values) / len(values) if values else 0,
        })
    return results


def _compute_consumable_summary(analysis):
    """Aggregate consumable usage by consumable name from a RaidAnalysis."""
    by_name = defaultdict(lambda: {"users": set(), "total": 0})
    for cu in analysis.consumables:
        by_name[cu.consumable_name]["users"].add(cu.player_name)
        by_name[cu.consumable_name]["total"] += cu.count
    result = {}
    for name, data in by_name.items():
        n_users = len(data["users"])
        result[name] = {
            "total_uses": data["total"],
            "unique_users": n_users,
        }
    return result


def _match_encounters(guild_analysis, ref_analysis):
    """Match encounters by encounter_id and compute comparison rows."""
    guild_enc = {}
    for e in (guild_analysis.encounters or []):
        total_dmg = sum(p.total_damage for p in e.players) if e.players else 0
        total_heal = sum(p.total_healing for p in e.players) if e.players else 0
        guild_enc[e.encounter_id] = {
            "name": e.name,
            "duration_ms": e.duration_ms,
            "total_damage": total_dmg,
            "total_healing": total_heal,
        }

    ref_enc = {}
    for e in (ref_analysis.encounters or []):
        total_dmg = sum(p.total_damage for p in e.players) if e.players else 0
        total_heal = sum(p.total_healing for p in e.players) if e.players else 0
        ref_enc[e.encounter_id] = {
            "name": e.name,
            "duration_ms": e.duration_ms,
            "total_damage": total_dmg,
            "total_healing": total_heal,
        }

    shared_ids = set(guild_enc.keys()) & set(ref_enc.keys())
    rows = []
    for eid in sorted(shared_ids):
        rows.append({
            "name": guild_enc[eid]["name"],
            "guild": guild_enc[eid],
            "ref": ref_enc[eid],
        })
    return rows


# ── Head-to-Head table models ──

class _ClassComparisonModel(QAbstractTableModel):
    HEADERS = ["Class", "Role", "Guild #", "Ref #", "Guild Avg", "Ref Avg", "Delta %"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("class", "")
            elif col == 1:
                return row.get("role", "").title()
            elif col == 2:
                return str(row.get("guild_count", 0))
            elif col == 3:
                return str(row.get("ref_count", 0))
            elif col == 4:
                return self._fmt(row.get("guild_avg"), row.get("role"))
            elif col == 5:
                return self._fmt(row.get("ref_avg"), row.get("role"))
            elif col == 6:
                return self._fmt_delta(row.get("guild_avg"), row.get("ref_avg"))
        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 6:
                return self._delta_color(row.get("guild_avg"), row.get("ref_avg"),
                                         row.get("role") != "tank")
            return QColor(COLORS["text"])
        return None

    @staticmethod
    def _fmt(val, role):
        if val is None:
            return "—"
        if role == "tank":
            return f"{val:.1f}%"
        return f"{val:,.0f}"

    @staticmethod
    def _fmt_delta(guild, ref):
        if guild is None or ref is None or ref == 0:
            return "—"
        delta = (guild - ref) / abs(ref) * 100
        sign = "+" if delta > 0 else ""
        return f"{sign}{delta:.1f}%"

    @staticmethod
    def _delta_color(guild, ref, higher_is_better=True):
        if guild is None or ref is None or ref == 0:
            return QColor(COLORS["text_dim"])
        delta = guild - ref
        is_positive = (delta > 0) == higher_is_better
        return QColor(COLORS["success"] if is_positive else COLORS["error"])


class _ConsumableComparisonModel(QAbstractTableModel):
    HEADERS = ["Consumable", "Guild Uses", "Guild Users", "Ref Uses", "Ref Users", "Delta"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("name", "")
            elif col == 1:
                return str(row.get("guild_uses", 0))
            elif col == 2:
                return str(row.get("guild_users", 0))
            elif col == 3:
                return str(row.get("ref_uses", 0))
            elif col == 4:
                return str(row.get("ref_users", 0))
            elif col == 5:
                delta = row.get("guild_uses", 0) - row.get("ref_uses", 0)
                sign = "+" if delta > 0 else ""
                return f"{sign}{delta}"
        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 5:
                delta = row.get("guild_uses", 0) - row.get("ref_uses", 0)
                if delta > 0:
                    return QColor(COLORS["success"])
                elif delta < 0:
                    return QColor(COLORS["error"])
                return QColor(COLORS["text_dim"])
            return QColor(COLORS["text"])
        return None


class _H2HEncounterModel(QAbstractTableModel):
    HEADERS = [
        "Boss", "Guild Duration", "Ref Duration",
        "Guild Dmg", "Ref Dmg", "Guild Healing", "Ref Healing",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        g = row.get("guild", {})
        r = row.get("ref", {})

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("name", "")
            elif col == 1:
                return self._fmt_duration(g.get("duration_ms"))
            elif col == 2:
                return self._fmt_duration(r.get("duration_ms"))
            elif col == 3:
                return self._fmt_number(g.get("total_damage"))
            elif col == 4:
                return self._fmt_number(r.get("total_damage"))
            elif col == 5:
                return self._fmt_number(g.get("total_healing"))
            elif col == 6:
                return self._fmt_number(r.get("total_healing"))
        elif role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS["text"])
        return None

    @staticmethod
    def _fmt_duration(ms):
        if ms is None:
            return "—"
        secs = int(ms / 1000)
        return f"{secs // 60}:{secs % 60:02d}"

    @staticmethod
    def _fmt_number(val):
        if val is None:
            return "—"
        return f"{val:,.0f}"


# ── Head-to-Head panel ──

class _HeadToHeadPanel(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(COMMON_STYLES)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Head-to-Head Raid Comparison")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(title)

        desc = QLabel(
            "Select a reference raid and a guild raid to compare "
            "class performance, consumable usage, and encounter metrics."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        layout.addWidget(desc)

        selector_row = QHBoxLayout()
        selector_row.setSpacing(10)

        selector_row.addWidget(QLabel("Reference Raid:"))
        self._ref_combo = QComboBox()
        self._ref_combo.setMinimumWidth(300)
        selector_row.addWidget(self._ref_combo, 1)

        vs_label = QLabel("vs")
        vs_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        vs_label.setStyleSheet(f"color: {COLORS['accent']};")
        selector_row.addWidget(vs_label)

        selector_row.addWidget(QLabel("Guild Raid:"))
        self._guild_combo = QComboBox()
        self._guild_combo.setMinimumWidth(300)
        selector_row.addWidget(self._guild_combo, 1)

        self._compare_btn = QPushButton("Compare")
        self._compare_btn.setFixedHeight(36)
        self._compare_btn.clicked.connect(self._run_comparison)
        selector_row.addWidget(self._compare_btn)

        layout.addLayout(selector_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {COLORS['bg_dark']};
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {COLORS['bg_dark']};
            }}
        """)
        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(16)

        self._placeholder = QLabel("Select two raids and click Compare.")
        self._placeholder.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 13px;")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(self._placeholder)
        self._content_layout.addStretch()

        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)

    def populate_combos(self):
        try:
            with PerformanceDB() as db:
                ref_raids = db.get_reference_raids()
                guild_raids = db.get_guild_raids_for_comparison()
        except (sqlite3.Error, OSError):
            ref_raids = []
            guild_raids = []

        self._ref_combo.blockSignals(True)
        current_ref = self._ref_combo.currentData(Qt.ItemDataRole.UserRole)
        self._ref_combo.clear()
        for r in ref_raids:
            label_parts = [r.get("raid_date", "")[:10], r.get("title", "")]
            if r.get("zone"):
                label_parts.append(r["zone"])
            if r.get("raid_size"):
                label_parts.append(f"{r['raid_size']}-man")
            if r.get("label"):
                label_parts.append(f"[{r['label']}]")
            display = " — ".join(label_parts[:2])
            if len(label_parts) > 2:
                display += f" ({', '.join(label_parts[2:])})"
            self._ref_combo.addItem(display, r["report_id"])
        if current_ref:
            idx = self._ref_combo.findData(current_ref, Qt.ItemDataRole.UserRole)
            if idx >= 0:
                self._ref_combo.setCurrentIndex(idx)
        self._ref_combo.blockSignals(False)

        self._guild_combo.blockSignals(True)
        current_guild = self._guild_combo.currentData(Qt.ItemDataRole.UserRole)
        self._guild_combo.clear()
        for r in guild_raids:
            label_parts = [r.get("raid_date", "")[:10], r.get("title", "")]
            if r.get("zone"):
                label_parts.append(r["zone"])
            if r.get("raid_size"):
                label_parts.append(f"{r['raid_size']}-man")
            display = " — ".join(label_parts[:2])
            if len(label_parts) > 2:
                display += f" ({', '.join(label_parts[2:])})"
            self._guild_combo.addItem(display, r["report_id"])
        if current_guild:
            idx = self._guild_combo.findData(current_guild, Qt.ItemDataRole.UserRole)
            if idx >= 0:
                self._guild_combo.setCurrentIndex(idx)
        self._guild_combo.blockSignals(False)

        self._compare_btn.setEnabled(
            self._ref_combo.count() > 0 and self._guild_combo.count() > 0)

    def _run_comparison(self):
        ref_id = self._ref_combo.currentData(Qt.ItemDataRole.UserRole)
        guild_id = self._guild_combo.currentData(Qt.ItemDataRole.UserRole)
        if not ref_id or not guild_id:
            return

        try:
            with PerformanceDB() as db:
                ref_analysis = db.get_raid_analysis(ref_id)
                guild_analysis = db.get_raid_analysis(guild_id)
                ref_stats = db.get_raid_aggregate_stats(ref_id)
                guild_stats = db.get_raid_aggregate_stats(guild_id)
        except (sqlite3.Error, OSError) as e:
            QMessageBox.warning(self, "Error", f"Failed to load raid data:\n{e}")
            return

        if not ref_analysis or not guild_analysis:
            QMessageBox.warning(self, "Error",
                                "Could not load one or both raids from the database.")
            return

        self._display_comparison(guild_analysis, ref_analysis,
                                 guild_stats or {}, ref_stats or {})
        self.status_message.emit(
            f"Comparing '{guild_analysis.metadata.title}' vs "
            f"'{ref_analysis.metadata.title}'")

    def _clear_content(self):
        old = self._scroll.takeWidget()
        if old:
            old.deleteLater()
        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(16)

    def _display_comparison(self, guild, ref, guild_stats, ref_stats):
        self._clear_content()
        layout = self._content_layout

        # ── Section: Metadata cards ──
        self._add_section_header(layout, "Raid Overview")

        cards_grid = QGridLayout()
        cards_grid.setSpacing(12)

        duration_card = _MetricCard("Duration")
        g_dur = guild_stats.get("duration_ms")
        r_dur = ref_stats.get("duration_ms")
        if g_dur is not None:
            g_dur_fmt = f"{int(g_dur/1000)//60}:{int(g_dur/1000)%60:02d}"
        else:
            g_dur_fmt = None
        if r_dur is not None:
            r_dur_fmt = f"{int(r_dur/1000)//60}:{int(r_dur/1000)%60:02d}"
        else:
            r_dur_fmt = None
        duration_card._guild_lbl.setText(f"Guild: {g_dur_fmt or '—'}")
        duration_card._ref_lbl.setText(f"Ref: {r_dur_fmt or '—'}")
        if g_dur and r_dur and r_dur != 0:
            delta_pct = (g_dur - r_dur) / abs(r_dur) * 100
            sign = "+" if delta_pct > 0 else ""
            is_better = delta_pct < 0
            color = COLORS["success"] if is_better else COLORS["error"]
            duration_card._delta_lbl.setText(f"{sign}{delta_pct:.1f}%")
            duration_card._delta_lbl.setStyleSheet(f"color: {color}; border: none;")

        damage_card = _MetricCard("Total Damage")
        damage_card.set_values(
            guild_stats.get("total_damage"), ref_stats.get("total_damage"))

        healing_card = _MetricCard("Total Healing")
        healing_card.set_values(
            guild_stats.get("total_healing"), ref_stats.get("total_healing"))

        size_card = _MetricCard("Raid Size")
        size_card.set_values(
            guild_stats.get("raid_size"), ref_stats.get("raid_size"),
            fmt="{:.0f}")

        taken_card = _MetricCard("Damage Taken")
        taken_card.set_values(
            guild_stats.get("total_damage_taken"),
            ref_stats.get("total_damage_taken"),
            higher_is_better=False)

        dps_count_g = len(guild.dps) if guild.dps else 1
        dps_count_r = len(ref.dps) if ref.dps else 1
        avg_dps_g = guild_stats.get("total_damage", 0) / dps_count_g if guild_stats.get("total_damage") else None
        avg_dps_r = ref_stats.get("total_damage", 0) / dps_count_r if ref_stats.get("total_damage") else None
        avg_dps_card = _MetricCard("Avg DPS per Player")
        avg_dps_card.set_values(avg_dps_g, avg_dps_r)

        cards_grid.addWidget(duration_card, 0, 0)
        cards_grid.addWidget(damage_card, 0, 1)
        cards_grid.addWidget(healing_card, 0, 2)
        cards_grid.addWidget(size_card, 1, 0)
        cards_grid.addWidget(taken_card, 1, 1)
        cards_grid.addWidget(avg_dps_card, 1, 2)
        layout.addLayout(cards_grid)

        # ── Section: Composition ──
        self._add_section_header(layout, "Raid Composition")
        comp_grid = QGridLayout()
        comp_grid.setSpacing(6)

        guild_classes = defaultdict(int)
        for p in guild.composition.all_players:
            guild_classes[p.player_class] += 1
        ref_classes = defaultdict(int)
        for p in ref.composition.all_players:
            ref_classes[p.player_class] += 1

        all_classes = sorted(set(guild_classes.keys()) | set(ref_classes.keys()))

        for col, header in enumerate(["Class", "Guild", "Ref", "Delta"]):
            lbl = QLabel(header)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLORS['text_dim']};")
            comp_grid.addWidget(lbl, 0, col)

        for i, cls in enumerate(all_classes, start=1):
            gc = guild_classes.get(cls, 0)
            rc = ref_classes.get(cls, 0)
            delta = gc - rc

            cls_lbl = QLabel(cls)
            cls_lbl.setStyleSheet(f"color: {COLORS['text']};")
            gc_lbl = QLabel(str(gc))
            gc_lbl.setStyleSheet(f"color: {COLORS['accent']};")
            rc_lbl = QLabel(str(rc))
            rc_lbl.setStyleSheet(f"color: {COLORS['text']};")

            sign = "+" if delta > 0 else ""
            d_color = COLORS["success"] if delta > 0 else (COLORS["error"] if delta < 0 else COLORS["text_dim"])
            d_lbl = QLabel(f"{sign}{delta}" if delta != 0 else "=")
            d_lbl.setStyleSheet(f"color: {d_color};")

            comp_grid.addWidget(cls_lbl, i, 0)
            comp_grid.addWidget(gc_lbl, i, 1)
            comp_grid.addWidget(rc_lbl, i, 2)
            comp_grid.addWidget(d_lbl, i, 3)

        layout.addLayout(comp_grid)

        # ── Section: Class performance ──
        self._add_section_header(layout, "Class Performance")

        guild_perf = _compute_class_performance(guild)
        ref_perf = _compute_class_performance(ref)

        guild_map = {(r["class"], r["role"]): r for r in guild_perf}
        ref_map = {(r["class"], r["role"]): r for r in ref_perf}
        all_keys = sorted(set(guild_map.keys()) | set(ref_map.keys()))

        class_rows = []
        for key in all_keys:
            gp = guild_map.get(key, {})
            rp = ref_map.get(key, {})
            class_rows.append({
                "class": key[0],
                "role": key[1],
                "guild_count": gp.get("count", 0),
                "ref_count": rp.get("count", 0),
                "guild_avg": gp.get("avg_metric"),
                "ref_avg": rp.get("avg_metric"),
            })

        self._class_model = _ClassComparisonModel()
        self._class_model.set_data(class_rows)
        class_table = self._make_table(self._class_model)
        layout.addWidget(class_table)

        # ── Section: Consumables ──
        self._add_section_header(layout, "Consumable Usage")

        guild_cons = _compute_consumable_summary(guild)
        ref_cons = _compute_consumable_summary(ref)
        all_consumables = sorted(set(guild_cons.keys()) | set(ref_cons.keys()))

        if all_consumables:
            cons_rows = []
            for name in all_consumables:
                gc = guild_cons.get(name, {})
                rc = ref_cons.get(name, {})
                cons_rows.append({
                    "name": name,
                    "guild_uses": gc.get("total_uses", 0),
                    "guild_users": gc.get("unique_users", 0),
                    "ref_uses": rc.get("total_uses", 0),
                    "ref_users": rc.get("unique_users", 0),
                })
            cons_rows.sort(key=lambda r: r["guild_uses"] + r["ref_uses"], reverse=True)

            self._cons_model = _ConsumableComparisonModel()
            self._cons_model.set_data(cons_rows)
            cons_table = self._make_table(self._cons_model)
            layout.addWidget(cons_table)
        else:
            no_cons = QLabel("No consumable data in either raid.")
            no_cons.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
            layout.addWidget(no_cons)

        # ── Section: Encounters ──
        self._add_section_header(layout, "Encounter Comparison (shared bosses)")

        encounter_rows = _match_encounters(guild, ref)
        if encounter_rows:
            self._enc_model = _H2HEncounterModel()
            self._enc_model.set_data(encounter_rows)
            enc_table = self._make_table(self._enc_model)
            layout.addWidget(enc_table)
        else:
            no_enc = QLabel("No common encounters between these raids.")
            no_enc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
            layout.addWidget(no_enc)

        layout.addStretch()
        self._scroll.setWidget(self._content)

    @staticmethod
    def _add_section_header(layout, text):
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(lbl)

    @staticmethod
    def _make_table(model):
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        table.setMaximumHeight(250)
        return table
