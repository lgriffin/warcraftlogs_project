"""
Command palette — Ctrl+K quick navigation overlay.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .styles import COLORS

COMMANDS = [
    {"key": "dashboard", "label": "Dashboard", "hint": "Ctrl+1", "desc": "Overview and quick stats"},
    {"key": "raids", "label": "Raids", "hint": "Ctrl+2", "desc": "Download, browse, diff, and compare raids"},
    {"key": "raids.download", "label": "Raids > Download", "hint": "", "desc": "Fetch and analyze guild reports"},
    {"key": "raids.browse", "label": "Raids > Browse", "hint": "", "desc": "Browse analyzed raids"},
    {"key": "raids.diff", "label": "Raids > Raid Diff", "hint": "", "desc": "Compare two raids side-by-side"},
    {"key": "raids.reference", "label": "Raids > Reference", "hint": "", "desc": "Import and compare reference reports"},
    {"key": "characters", "label": "Characters", "hint": "Ctrl+3", "desc": "Search and view character history"},
    {"key": "characters.my", "label": "Characters > My Character", "hint": "", "desc": "View your character profile and WCL data"},
    {"key": "characters.compare", "label": "Characters > Compare", "hint": "", "desc": "Compare multiple characters side-by-side"},
    {"key": "insights", "label": "Insights", "hint": "Ctrl+4", "desc": "Performance trends and boss analytics"},
    {"key": "raid_groups", "label": "Raid Groups", "hint": "Ctrl+5", "desc": "Manage raid groups and members"},
    {"key": "settings", "label": "Settings", "hint": "Ctrl+,", "desc": "Application settings"},
    {"key": "toggle_sidebar", "label": "Toggle Sidebar", "hint": "Ctrl+B", "desc": "Expand or collapse the sidebar"},
]


class CommandPalette(QDialog):
    navigate = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setFixedWidth(520)
        self.setMaximumHeight(420)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build_ui()
        self._populate()

    def _build_ui(self):
        self.setStyleSheet(f"""
            CommandPalette {{
                background-color: {COLORS['bg_card']};
                border: 2px solid {COLORS['accent_dim']};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type to search...")
        self._input.setFont(QFont("Segoe UI", 14))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_header']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['accent']};
            }}
        """)
        self._input.textChanged.connect(self._filter)
        layout.addWidget(self._input)

        hint = QLabel("Navigate to...")
        hint.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; padding: 0 4px;"
        )
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent;
                border: none;
                outline: none;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 10px 12px;
                border-radius: 4px;
                color: {COLORS['text']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_hover']};
                color: {COLORS['text_gold']};
            }}
            QListWidget::item:hover:!selected {{
                background-color: {COLORS['bg_input']};
            }}
        """)
        self._list.itemActivated.connect(self._on_activated)
        layout.addWidget(self._list)

    def _populate(self, query: str = ""):
        self._list.clear()
        q = query.lower()
        for cmd in COMMANDS:
            text = f"{cmd['label']} {cmd['desc']}".lower()
            if q and q not in text:
                continue
            hint_part = f"    {cmd['hint']}" if cmd["hint"] else ""
            display = f"{cmd['label']}{hint_part}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, cmd["key"])
            item.setToolTip(cmd["desc"])
            self._list.addItem(item)

        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        self._list.setFixedHeight(
            min(self._list.count() * 42, 320)
        )
        self.adjustSize()

    def _filter(self, text: str):
        self._populate(text)

    def _on_activated(self, item: QListWidgetItem):
        key = item.data(Qt.ItemDataRole.UserRole)
        self.navigate.emit(key)
        self.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self._list.currentItem()
            if current:
                self._on_activated(current)
        elif event.key() == Qt.Key.Key_Down:
            row = self._list.currentRow()
            if row < self._list.count() - 1:
                self._list.setCurrentRow(row + 1)
        elif event.key() == Qt.Key.Key_Up:
            row = self._list.currentRow()
            if row > 0:
                self._list.setCurrentRow(row - 1)
        else:
            super().keyPressEvent(event)
