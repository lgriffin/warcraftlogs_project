"""
Find Character view — search and browse all characters in the local database.
"""

import sqlite3

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QGroupBox,
    QSplitter, QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from .styles import COMMON_STYLES, COLORS
from ..database import PerformanceDB
from ..models import CharacterHistory


CLASS_COLORS = {
    "Warrior": "#C79C6E",
    "Paladin": "#F58CBA",
    "Priest": "#FFFFFF",
    "Shaman": "#0070DE",
    "Druid": "#FF7D0A",
    "Rogue": "#FFF569",
    "Mage": "#69CCF0",
    "Warlock": "#9482C9",
    "Hunter": "#ABD473",
}


class FindCharacterView(QWidget):
    status_message = Signal(str)
    view_character_history = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMMON_STYLES)
        self._characters: list[CharacterHistory] = []
        self._selected: CharacterHistory | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QLabel("Find Character")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: search + list ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)

        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name...")
        self._search.textChanged.connect(self._filter)
        search_row.addWidget(self._search)

        refresh_btn = QPushButton("  Refresh  ")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.clicked.connect(self._load_characters)
        search_row.addWidget(refresh_btn)
        left_layout.addLayout(search_row)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        left_layout.addWidget(self._count_label)

        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_dark']};
                border-left: 3px solid {COLORS['accent']};
            }}
        """)
        self._list.currentItemChanged.connect(self._on_selected)
        left_layout.addWidget(self._list)
        splitter.addWidget(left)

        # ── Right: detail panel ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {COLORS['bg_dark']}; }}
        """)

        self._detail = QWidget()
        self._detail.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.setSpacing(12)

        self._no_selection = QLabel("Select a character from the list to see details.")
        self._no_selection.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_selection.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 14px; padding: 40px;")
        detail_layout.addWidget(self._no_selection)

        self._detail_group = QGroupBox("Character Summary")
        summary_layout = QVBoxLayout(self._detail_group)
        summary_layout.setSpacing(8)

        self._detail_labels: dict[str, QLabel] = {}
        for key in ["Name", "Class", "Raids Tracked", "Active Period",
                     "Avg Healing", "Avg Damage", "Avg Mitigation",
                     "Consumables Used"]:
            row = QHBoxLayout()
            label = QLabel(f"{key}:")
            label.setFixedWidth(140)
            label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
            value = QLabel("-")
            value.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
            self._detail_labels[key] = value
            row.addWidget(label)
            row.addWidget(value, 1)
            summary_layout.addLayout(row)

        self._detail_group.setVisible(False)
        detail_layout.addWidget(self._detail_group)

        self._history_btn = QPushButton("View Full History")
        self._history_btn.setFixedHeight(36)
        self._history_btn.setVisible(False)
        self._history_btn.clicked.connect(self._open_history)
        detail_layout.addWidget(self._history_btn)

        detail_layout.addStretch()

        scroll.setWidget(self._detail)
        right_layout.addWidget(scroll)
        splitter.addWidget(right)

        splitter.setSizes([350, 500])
        layout.addWidget(splitter, 1)

    def _load_characters(self):
        try:
            with PerformanceDB() as db:
                self._characters = db.get_all_characters()
        except (sqlite3.Error, OSError) as e:
            self.status_message.emit(f"Failed to load characters: {e}")
            self._characters = []

        self._populate_list()
        self.status_message.emit(f"Loaded {len(self._characters)} characters")

    def _populate_list(self):
        self._list.clear()
        query = self._search.text().strip().lower()

        visible = 0
        for ch in self._characters:
            if query and query not in ch.name.lower():
                continue
            class_color = CLASS_COLORS.get(ch.player_class, "#eee")
            raids_text = f"{ch.total_raids} raids" if ch.total_raids else "0 raids"
            display = f"{ch.name}  [{ch.player_class}]  ({raids_text})"

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, ch.name)
            item.setForeground(QColor(class_color))
            self._list.addItem(item)
            visible += 1

        self._count_label.setText(f"{visible} character{'s' if visible != 1 else ''}")

    def _filter(self):
        self._populate_list()

    def _on_selected(self, current, _previous):
        if not current:
            self._detail_group.setVisible(False)
            self._history_btn.setVisible(False)
            self._no_selection.setVisible(True)
            self._selected = None
            return

        name = current.data(Qt.ItemDataRole.UserRole)
        ch = next((c for c in self._characters if c.name == name), None)
        if not ch:
            return

        self._selected = ch
        self._no_selection.setVisible(False)
        self._detail_group.setVisible(True)
        self._history_btn.setVisible(True)

        class_color = CLASS_COLORS.get(ch.player_class, "#eee")
        self._detail_labels["Name"].setText(ch.name)
        self._detail_labels["Name"].setStyleSheet(
            f"color: {class_color}; font-size: 15px; font-weight: bold;")
        self._detail_labels["Class"].setText(ch.player_class)
        self._detail_labels["Class"].setStyleSheet(
            f"color: {class_color}; font-size: 13px; font-weight: bold;")
        self._detail_labels["Raids Tracked"].setText(str(ch.total_raids))

        if ch.first_seen and ch.last_seen:
            period = (f"{ch.first_seen.strftime('%Y-%m-%d')} to "
                      f"{ch.last_seen.strftime('%Y-%m-%d')}")
        else:
            period = "-"
        self._detail_labels["Active Period"].setText(period)
        self._detail_labels["Avg Healing"].setText(
            f"{ch.avg_healing:,.0f}" if ch.avg_healing else "-")
        self._detail_labels["Avg Damage"].setText(
            f"{ch.avg_damage:,.0f}" if ch.avg_damage else "-")
        self._detail_labels["Avg Mitigation"].setText(
            f"{ch.avg_mitigation_percent:.1f}%" if ch.avg_mitigation_percent else "-")
        self._detail_labels["Consumables Used"].setText(
            str(ch.total_consumables_used))

    def _open_history(self):
        if self._selected:
            self.view_character_history.emit(self._selected.name)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._characters:
            self._load_characters()
