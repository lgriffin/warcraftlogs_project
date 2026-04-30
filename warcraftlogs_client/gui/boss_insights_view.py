"""
Boss Insights view — aggregate encounter performance across raids.

Pick a boss and day filter to see kill stats, min/median/max metrics,
and top performer breakdowns.
"""

import sqlite3
from statistics import median

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS
from ..database import PerformanceDB


DAY_OPTIONS = [
    "All Days", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday", "Sunday",
]


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
    label.setStyleSheet(f"color: {COLORS['text_header']}; padding: 8px 0 4px 0;")
    return label


def _fmt(val: int) -> str:
    return f"{val:,}"


def _fmt_duration(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


class BossInsightsView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded = False
        self._encounters_data: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.setStyleSheet(COMMON_STYLES)

        header = QHBoxLayout()
        title = QLabel("Boss Insights")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        header.addWidget(title)
        header.addSpacing(20)

        header.addWidget(QLabel("Boss:"))
        self._boss_combo = QComboBox()
        self._boss_combo.setMinimumWidth(250)
        self._boss_combo.currentIndexChanged.connect(self._on_boss_changed)
        header.addWidget(self._boss_combo)
        header.addSpacing(12)

        header.addWidget(QLabel("Day:"))
        self._day_combo = QComboBox()
        self._day_combo.addItems(DAY_OPTIONS)
        self._day_combo.currentIndexChanged.connect(self._on_day_changed)
        header.addWidget(self._day_combo)

        header.addStretch()
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {COLORS['bg_dark']}; }}
            QScrollArea > QWidget > QWidget {{ background-color: {COLORS['bg_dark']}; }}
        """)

        content = QWidget()
        content.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(16)

        # Kill summary
        self._summary_label = QLabel()
        self._summary_label.setFont(QFont("Segoe UI", 13))
        self._summary_label.setStyleSheet(
            f"color: {COLORS['text']}; background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; padding: 12px;")
        self._content_layout.addWidget(self._summary_label)

        # Min / Median / Max stats
        self._content_layout.addWidget(_section_label("Key Stats (across all kills)"))

        self._stats_table = QTableWidget()
        self._stats_table.setColumnCount(4)
        self._stats_table.setHorizontalHeaderLabels(["Metric", "Min", "Median", "Max"])
        self._stats_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 4):
            self._stats_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch)
        self._stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._stats_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._stats_table.setAlternatingRowColors(True)
        self._stats_table.verticalHeader().setVisible(False)
        self._stats_table.setMaximumHeight(180)
        self._content_layout.addWidget(self._stats_table)

        # Top performers
        self._content_layout.addWidget(_section_label("Top Performers"))

        self._perf_table = QTableWidget()
        self._perf_table.setColumnCount(7)
        self._perf_table.setHorizontalHeaderLabels([
            "Name", "Class", "Role", "Avg Damage", "Avg Healing",
            "Avg Dmg Taken", "Kills",
        ])
        self._perf_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 7):
            self._perf_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._perf_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._perf_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._perf_table.setAlternatingRowColors(True)
        self._perf_table.setSortingEnabled(True)
        self._perf_table.verticalHeader().setVisible(False)
        self._content_layout.addWidget(self._perf_table, 1)

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._load_boss_list()

    def _get_day_filter(self) -> str | None:
        day = self._day_combo.currentText()
        return None if day == "All Days" else day

    def _on_day_changed(self):
        self._loaded = True
        self._load_boss_list()

    def _load_boss_list(self):
        self._boss_combo.blockSignals(True)
        self._boss_combo.clear()
        try:
            with PerformanceDB() as db:
                self._encounters_data = db.get_distinct_encounters(
                    raid_day=self._get_day_filter())
        except (sqlite3.Error, OSError):
            self._encounters_data = []

        if not self._encounters_data:
            self._boss_combo.addItem("No encounters found")
            self._summary_label.setText("No encounter data available. Re-analyze raids to capture boss encounters.")
            self._stats_table.setRowCount(0)
            self._perf_table.setRowCount(0)
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

    def _on_boss_changed(self, index: int):
        if index < 0 or index >= len(self._encounters_data):
            return
        encounter_id = self._encounters_data[index]["encounter_id"]
        self._load_data(encounter_id)

    def _load_data(self, encounter_id: int):
        day = self._get_day_filter()
        try:
            with PerformanceDB() as db:
                history = db.get_encounter_history(encounter_id, raid_day=day)
                breakdown = db.get_encounter_player_breakdown(
                    encounter_id, raid_day=day)
        except (sqlite3.Error, OSError) as e:
            self.status_message.emit(f"Error loading boss data: {e}")
            return

        self._refresh_summary(history)
        self._refresh_stats(history)
        self._refresh_performers(breakdown)
        self.status_message.emit(
            f"Boss Insights: {len(history)} kills, {len(breakdown)} players")

    def _refresh_summary(self, history: list[dict]):
        if not history:
            self._summary_label.setText("No kills found for this boss with current filters.")
            return

        kill_count = len(history)
        durations = [h["duration_ms"] for h in history]
        avg_dur = sum(durations) // kill_count
        total_dmg = sum(h["total_damage"] for h in history)
        total_heal = sum(h["total_healing"] for h in history)

        self._summary_label.setText(
            f"Kills: {kill_count}    |    "
            f"Avg Duration: {_fmt_duration(avg_dur)}    |    "
            f"Avg Raid Damage: {_fmt(total_dmg // kill_count)}    |    "
            f"Avg Raid Healing: {_fmt(total_heal // kill_count)}")

    def _refresh_stats(self, history: list[dict]):
        if not history:
            self._stats_table.setRowCount(0)
            return

        durations = [h["duration_ms"] for h in history]
        damages = [h["total_damage"] for h in history]
        healings = [h["total_healing"] for h in history]
        sizes = [h["player_count"] for h in history]

        metrics = [
            ("Duration", durations, _fmt_duration),
            ("Total Damage", damages, _fmt),
            ("Total Healing", healings, _fmt),
            ("Raid Size", sizes, str),
        ]

        self._stats_table.setRowCount(len(metrics))
        for i, (name, values, formatter) in enumerate(metrics):
            sorted_vals = sorted(values)
            med_val = int(median(sorted_vals))

            self._stats_table.setItem(i, 0, QTableWidgetItem(name))
            for j, val in enumerate([sorted_vals[0], med_val, sorted_vals[-1]]):
                item = QTableWidgetItem(formatter(val))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._stats_table.setItem(i, j + 1, item)

    def _refresh_performers(self, breakdown: list[dict]):
        self._perf_table.setSortingEnabled(False)
        self._perf_table.setRowCount(len(breakdown))
        for i, row in enumerate(breakdown):
            self._perf_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self._perf_table.setItem(i, 1, QTableWidgetItem(row["player_class"]))
            self._perf_table.setItem(i, 2, QTableWidgetItem(row["role"]))
            for j, key in enumerate(["avg_damage", "avg_healing", "avg_damage_taken"]):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.DisplayRole, _fmt(row[key]))
                item.setData(Qt.ItemDataRole.UserRole, row[key])
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._perf_table.setItem(i, j + 3, item)
            kills_item = QTableWidgetItem()
            kills_item.setData(Qt.ItemDataRole.DisplayRole, str(row["kills"]))
            kills_item.setData(Qt.ItemDataRole.UserRole, row["kills"])
            kills_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._perf_table.setItem(i, 6, kills_item)
        self._perf_table.setSortingEnabled(True)
