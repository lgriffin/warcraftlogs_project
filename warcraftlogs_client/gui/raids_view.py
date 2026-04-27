"""
Raids view — browse analyzed raids from the database, drill into full analysis.
"""

import sqlite3

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS
from .raid_list_widget import RaidListWidget


class RaidsView(QWidget):
    status_message = Signal(str)
    open_raid = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
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

        self._raid_list = RaidListWidget()
        self._raid_list.raid_selected.connect(self._on_raid_selected)
        self._raid_list.status_message.connect(self.status_message.emit)
        layout.addWidget(self._raid_list, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self._raid_list.load_raids()

    def _on_raid_selected(self, report_id: str):
        self.open_raid.emit(report_id)
