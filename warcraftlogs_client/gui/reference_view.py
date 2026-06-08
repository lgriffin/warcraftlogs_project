"""
Reference Reports view — import non-guild reports, manage them,
and compare guild vs reference performance.
"""

import sqlite3
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableView, QHeaderView, QTabWidget, QComboBox,
    QMessageBox, QGridLayout, QFrame,
)
from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QFont, QColor

from .styles import COMMON_STYLES, COLORS
from .worker import AnalysisWorker
from ..database import PerformanceDB


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

        self._set_importing(True, f"Downloading report {report_id}...")
        self._worker = AnalysisWorker(report_id)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

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
