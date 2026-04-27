"""
Reusable raid list widget with day-of-week filter and search.

Emits raid_selected(report_id) when a raid is clicked.
"""

import sqlite3
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QCheckBox, QListWidget, QListWidgetItem,
    QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import COLORS
from ..database import PerformanceDB


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_ABBREV = {d: d[:3] for d in DAY_NAMES}


class RaidListWidget(QWidget):
    raid_selected = Signal(str)
    status_message = Signal(str)

    def __init__(self, default_days: list[str] = None, parent=None):
        super().__init__(parent)
        self._all_raids: list[dict] = []
        self._default_days = default_days or ["Wednesday", "Thursday", "Sunday"]
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search raids...")
        self._search_input.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search_input)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.setFixedHeight(32)
        refresh_btn.clicked.connect(self.load_raids)
        search_row.addWidget(refresh_btn)
        layout.addLayout(search_row)

        day_row = QHBoxLayout()
        day_label = QLabel("Days:")
        day_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        day_row.addWidget(day_label)

        self._day_checkboxes: dict[int, QCheckBox] = {}
        for i, name in enumerate(DAY_NAMES):
            cb = QCheckBox(DAY_ABBREV[name])
            cb.setChecked(name in self._default_days)
            cb.toggled.connect(self._apply_filter)
            self._day_checkboxes[i] = cb
            day_row.addWidget(cb)
        day_row.addStretch()
        layout.addLayout(day_row)

        self._raid_list = QListWidget()
        self._raid_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                font-size: 12px;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_dark']};
                border-left: 3px solid {COLORS['accent']};
            }}
            QListWidget::item:hover:!selected {{
                background-color: {COLORS['bg_input']};
            }}
        """)
        self._raid_list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._raid_list, 1)

    def load_raids(self, raids: list[dict] = None):
        if raids is not None:
            self._all_raids = raids
        else:
            try:
                with PerformanceDB() as db:
                    self._all_raids = db.get_raid_list(limit=200)
                self.status_message.emit(f"Loaded {len(self._all_raids)} raids")
            except (sqlite3.Error, OSError) as e:
                self.status_message.emit(f"Error loading raids: {e}")
                self._all_raids = []
        self._apply_filter()

    def set_day_filter(self, days: list[str]):
        for i, name in enumerate(DAY_NAMES):
            cb = self._day_checkboxes.get(i)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(name in days)
                cb.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self):
        self._raid_list.clear()
        search = self._search_input.text().lower()
        allowed_days = {i for i, cb in self._day_checkboxes.items() if cb.isChecked()}

        for raid in self._all_raids:
            try:
                dt = datetime.fromisoformat(raid["raid_date"])
            except (ValueError, TypeError):
                continue

            if dt.weekday() not in allowed_days:
                continue

            display = f"{dt.strftime('%Y-%m-%d')}  {dt.strftime('%A')[:3]}  {raid['title']}"
            if search and search not in display.lower():
                continue

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, raid["report_id"])
            self._raid_list.addItem(item)

    def _on_item_changed(self, current, previous):
        if current:
            report_id = current.data(Qt.ItemDataRole.UserRole)
            if report_id:
                self.raid_selected.emit(report_id)
