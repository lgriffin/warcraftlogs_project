"""
Characters hub — unified view with persistent character list on the left,
inline character history on the right, plus My Character and Compare modes.
"""

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..database import PerformanceDB
from ..models import CharacterHistory
from .character_history_widget import CharacterHistoryWidget
from .character_view import CharacterView
from .compare_view import CompareView
from .styles import CLASS_COLORS, COLORS, COMMON_STYLES


class CharactersHub(QWidget):
    status_message = Signal(str)
    analyze_report = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._characters: list[CharacterHistory] = []
        self._current_history: CharacterHistoryWidget | None = None

        self.character_view = CharacterView()
        self.compare_view = CompareView()

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        self.setStyleSheet(COMMON_STYLES)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Left panel: character list ──
        left = QWidget()
        left.setFixedWidth(280)
        left.setStyleSheet(f"""
            QWidget {{ background-color: {COLORS['bg_mid']}; }}
            QLineEdit {{ margin: 0; }}
        """)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)

        header = QLabel("Characters")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_gold']};")
        left_layout.addWidget(header)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name...")
        self._search.textChanged.connect(self._filter)
        search_row.addWidget(self._search)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.setFixedHeight(34)
        refresh_btn.setToolTip("Refresh character list")
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
        self._list.currentItemChanged.connect(self._on_character_selected)
        left_layout.addWidget(self._list, 1)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)

        self._my_char_btn = QPushButton("My Character")
        self._my_char_btn.setProperty("secondary", True)
        self._my_char_btn.setFixedHeight(34)
        self._my_char_btn.clicked.connect(self._show_my_character)
        mode_row.addWidget(self._my_char_btn)

        self._compare_btn = QPushButton("Compare")
        self._compare_btn.setProperty("secondary", True)
        self._compare_btn.setFixedHeight(34)
        self._compare_btn.clicked.connect(self._show_compare)
        mode_row.addWidget(self._compare_btn)

        left_layout.addLayout(mode_row)
        layout.addWidget(left)

        # ── Right panel: content area ──
        self._right_stack = QStackedWidget()
        self._right_stack.setStyleSheet(f"background-color: {COLORS['bg_dark']};")

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_label = QLabel("Select a character from the list\nto view their history and trends.")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setFont(QFont("Segoe UI", 14))
        empty_label.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 60px;")
        empty_layout.addWidget(empty_label)
        self._right_stack.addWidget(empty)  # index 0

        self._history_container = QWidget()
        self._history_layout = QVBoxLayout(self._history_container)
        self._history_layout.setContentsMargins(0, 0, 0, 0)
        self._right_stack.addWidget(self._history_container)  # index 1

        self._right_stack.addWidget(self.character_view)  # index 2
        self._right_stack.addWidget(self.compare_view)  # index 3

        layout.addWidget(self._right_stack, 1)

    def _connect_signals(self):
        self.character_view.status_message.connect(self.status_message)
        self.character_view.analyze_report.connect(self.analyze_report)
        self.character_view.view_character_history.connect(
            self._select_character_by_name
        )

        self.compare_view.status_message.connect(self.status_message)

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
        self._list.blockSignals(True)
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
        self._count_label.setText(
            f"{visible} character{'s' if visible != 1 else ''}"
        )
        self._list.blockSignals(False)

    def _filter(self):
        self._populate_list()

    def _on_character_selected(self, current, _previous):
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        self._show_character_history(name)

    def _show_character_history(self, name: str):
        if self._current_history:
            self._history_layout.removeWidget(self._current_history)
            self._current_history.deleteLater()
            self._current_history = None

        widget = CharacterHistoryWidget(name, inline=True)
        widget.status_message.connect(self.status_message)
        self._history_layout.addWidget(widget)
        self._current_history = widget
        self._right_stack.setCurrentIndex(1)

    def _select_character_by_name(self, name: str):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                self._list.setCurrentItem(item)
                return
        self._show_character_history(name)

    def _show_my_character(self):
        self._list.clearSelection()
        self._right_stack.setCurrentIndex(2)

    def _show_compare(self):
        self._list.clearSelection()
        self._right_stack.setCurrentIndex(3)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._characters:
            self._load_characters()
