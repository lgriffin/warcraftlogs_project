"""
Raids view — browse analyzed raids and boss encounter history.
"""

import sqlite3

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSplitter, QComboBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS
from .raid_list_widget import RaidListWidget
from ..database import PerformanceDB


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class RaidsView(QWidget):
    status_message = Signal(str)
    open_raid = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._encounters_data: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.setStyleSheet(COMMON_STYLES)

        title = QLabel("Raids")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: Raid list ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)

        left_title = QLabel("Raid Browser")
        left_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        left_title.setStyleSheet(f"color: {COLORS['text_header']};")
        left_layout.addWidget(left_title)

        self._raid_list = RaidListWidget()
        self._raid_list.raid_selected.connect(self._on_raid_selected)
        self._raid_list.status_message.connect(self.status_message.emit)
        left_layout.addWidget(self._raid_list, 1)

        splitter.addWidget(left)

        # ── Right: Boss history ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        right_title = QLabel("Boss History")
        right_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        right_title.setStyleSheet(f"color: {COLORS['text_header']};")
        right_layout.addWidget(right_title)

        boss_row = QHBoxLayout()
        boss_row.addWidget(QLabel("Boss:"))
        self._boss_combo = QComboBox()
        self._boss_combo.currentIndexChanged.connect(self._on_boss_changed)
        boss_row.addWidget(self._boss_combo, 1)
        right_layout.addLayout(boss_row)

        day_row = QHBoxLayout()
        day_label = QLabel("Days:")
        day_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        day_row.addWidget(day_label)

        defaults = {2, 3, 6}
        self._boss_day_checkboxes: dict[int, QCheckBox] = {}
        for i, name in enumerate(DAY_NAMES):
            cb = QCheckBox(name)
            cb.setChecked(i in defaults)
            cb.toggled.connect(self._reload_boss_data)
            self._boss_day_checkboxes[i] = cb
            day_row.addWidget(cb)
        day_row.addStretch()
        right_layout.addLayout(day_row)

        self._boss_summary = QLabel()
        self._boss_summary.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 12px; padding: 4px 0;")
        right_layout.addWidget(self._boss_summary)

        self._boss_table = QTableWidget()
        self._boss_table.setColumnCount(7)
        self._boss_table.setHorizontalHeaderLabels([
            "Name", "Class", "Role", "Avg Damage", "Avg Healing",
            "Avg Dmg Taken", "Kills",
        ])
        self._boss_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 7):
            self._boss_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._boss_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._boss_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._boss_table.setAlternatingRowColors(True)
        self._boss_table.setSortingEnabled(True)
        self._boss_table.verticalHeader().setVisible(False)
        right_layout.addWidget(self._boss_table, 1)

        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self._raid_list.load_raids()
        self._load_boss_list()

    def _on_raid_selected(self, report_id: str):
        self.open_raid.emit(report_id)

    def _get_selected_day(self) -> str | None:
        checked = [i for i, cb in self._boss_day_checkboxes.items() if cb.isChecked()]
        if len(checked) == 7 or len(checked) == 0:
            return None
        day_names = [DAY_FULL[i] for i in checked]
        return ",".join(day_names)

    def _load_boss_list(self):
        self._boss_combo.blockSignals(True)
        self._boss_combo.clear()
        try:
            with PerformanceDB() as db:
                day_filter = self._get_selected_day()
                self._encounters_data = db.get_distinct_encounters(
                    raid_day=day_filter)
        except (sqlite3.Error, OSError):
            self._encounters_data = []

        if not self._encounters_data:
            self._boss_combo.addItem("No encounters found")
            self._boss_summary.setText("")
            self._boss_table.setRowCount(0)
            self._boss_combo.blockSignals(False)
            return

        for enc in self._encounters_data:
            self._boss_combo.addItem(
                f"{enc['name']} ({enc['kill_count']} kills)",
                enc["encounter_id"],
            )
        self._boss_combo.blockSignals(False)
        self._boss_combo.setCurrentIndex(0)
        self._on_boss_changed(0)

    def _reload_boss_data(self):
        self._load_boss_list()

    def _on_boss_changed(self, index: int):
        if index < 0 or index >= len(self._encounters_data):
            return

        encounter_id = self._encounters_data[index]["encounter_id"]
        day_filter = self._get_selected_day()

        try:
            with PerformanceDB() as db:
                history = db.get_encounter_history(
                    encounter_id, raid_day=day_filter)
                breakdown = db.get_encounter_player_breakdown(
                    encounter_id, raid_day=day_filter)
        except (sqlite3.Error, OSError) as e:
            self.status_message.emit(f"Error loading boss history: {e}")
            return

        if history:
            kill_count = len(history)
            avg_duration_ms = sum(h["duration_ms"] for h in history) // kill_count
            avg_s = avg_duration_ms // 1000
            avg_dmg = sum(h["total_damage"] for h in history) // kill_count
            avg_heal = sum(h["total_healing"] for h in history) // kill_count
            self._boss_summary.setText(
                f"Kills: {kill_count}  |  "
                f"Avg Duration: {avg_s // 60}:{avg_s % 60:02d}  |  "
                f"Avg Raid Damage: {avg_dmg:,}  |  "
                f"Avg Raid Healing: {avg_heal:,}")
        else:
            self._boss_summary.setText("No kill data")

        self._boss_table.setSortingEnabled(False)
        self._boss_table.setRowCount(len(breakdown))
        for i, row in enumerate(breakdown):
            self._boss_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self._boss_table.setItem(i, 1, QTableWidgetItem(row["player_class"]))
            self._boss_table.setItem(i, 2, QTableWidgetItem(row["role"]))
            for j, key in enumerate(["avg_damage", "avg_healing", "avg_damage_taken"]):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.DisplayRole, f"{row[key]:,}")
                item.setData(Qt.ItemDataRole.UserRole, row[key])
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._boss_table.setItem(i, j + 3, item)
            kills_item = QTableWidgetItem()
            kills_item.setData(Qt.ItemDataRole.DisplayRole, str(row["kills"]))
            kills_item.setData(Qt.ItemDataRole.UserRole, row["kills"])
            kills_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._boss_table.setItem(i, 6, kills_item)
        self._boss_table.setSortingEnabled(True)
