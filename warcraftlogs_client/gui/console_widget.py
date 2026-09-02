"""
Console log viewer — captures Python logging output for in-app debugging.
"""

import logging

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .styles import COLORS


class _LogSignalBridge(QObject):
    log_message = Signal(str)


class GuiLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self._bridge = _LogSignalBridge()
        self.log_message = self._bridge.log_message

    def emit(self, record):
        try:
            msg = self.format(record)
            self._bridge.log_message.emit(msg)
        except Exception:
            self.handleError(record)


class ConsoleDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Console", parent)
        self.setObjectName("ConsoleDock")
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QWidget()
        toolbar.setFixedHeight(28)
        toolbar.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 0, 8, 0)
        toolbar_layout.setSpacing(4)

        toolbar_layout.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedSize(60, 22)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS["bg_input"]};
                color: {COLORS["text_dim"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 3px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {COLORS["bg_hover"]};
                color: {COLORS["text"]};
            }}
        """)
        clear_btn.clicked.connect(lambda: self._log_view.clear())
        toolbar_layout.addWidget(clear_btn)

        layout.addWidget(toolbar)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(5000)
        self._log_view.setFont(QFont("Consolas", 10))
        self._log_view.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {COLORS["bg_dark"]};
                color: {COLORS["text"]};
                border: none;
                padding: 4px 8px;
            }}
        """)
        layout.addWidget(self._log_view)

        self.setWidget(container)

        self.setStyleSheet(f"""
            QDockWidget {{
                color: {COLORS["text_gold"]};
                font-size: 12px;
                font-weight: bold;
            }}
            QDockWidget::title {{
                background-color: {COLORS["bg_card"]};
                padding: 4px 8px;
                border-bottom: 1px solid {COLORS["border"]};
            }}
        """)

        self._handler = GuiLogHandler()
        fmt = "%(asctime)s  %(name)s  %(levelname)s: %(message)s"
        self._handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(self._handler)
        self._handler.log_message.connect(self._append_log)

    @Slot(str)
    def _append_log(self, msg: str):
        self._log_view.appendPlainText(msg)

    def cleanup(self):
        logging.getLogger().removeHandler(self._handler)
