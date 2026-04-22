"""
Main application window with sidebar navigation.
"""

import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget,
    QStatusBar, QLabel,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap

from .analyze_view import AnalyzeView
from .history_view import HistoryView
from .raid_group_view import RaidGroupView
from .character_view import CharacterView
from .settings_view import SettingsView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WarcraftLogs Analyzer")
        self.setMinimumSize(1100, 700)
        self.resize(1300, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Sidebar ──
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("""
            QWidget {
                background-color: #1a1a2e;
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # App title
        title = QLabel("WCL Analyzer")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFixedHeight(60)
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("""
            QLabel {
                color: #e94560;
                background-color: #16213e;
                padding: 10px;
            }
        """)
        sidebar_layout.addWidget(title)

        # Nav list
        self.nav_list = QListWidget()
        self.nav_list.setIconSize(QSize(20, 20))
        self.nav_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a2e;
                color: #eee;
                border: none;
                font-size: 13px;
                padding-top: 10px;
            }
            QListWidget::item {
                padding: 14px 20px;
                border-left: 3px solid transparent;
            }
            QListWidget::item:selected {
                background-color: #16213e;
                border-left: 3px solid #e94560;
                color: #fff;
            }
            QListWidget::item:hover:!selected {
                background-color: #16213e;
            }
        """)

        nav_items = [
            ("Analyze Raid", "Run analysis on a WarcraftLogs report"),
            ("History", "View historical character performance"),
            ("Raid Groups", "Manage raid groups and members"),
            ("Character", "View character profile and rankings"),
            ("Settings", "Configure credentials and thresholds"),
        ]
        for name, tooltip in nav_items:
            item = QListWidgetItem(name)
            item.setToolTip(tooltip)
            item.setSizeHint(QSize(200, 48))
            self.nav_list.addItem(item)

        sidebar_layout.addWidget(self.nav_list)
        sidebar_layout.addStretch()

        # Version label at bottom
        version_label = QLabel("v3.0.0\nTBC enabled")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #555; padding: 10px; font-size: 11px;")
        sidebar_layout.addWidget(version_label)

        layout.addWidget(sidebar)

        # ── Content area ──
        content_wrapper = QWidget()
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # ── Top bar with guild logo ──
        top_bar = QWidget()
        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet("background-color: #16213e;")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 8, 16, 8)

        top_bar_layout.addStretch()

        self.guild_logo_label = QLabel()
        self.guild_logo_label.setFixedSize(44, 44)
        self.guild_logo_label.setScaledContents(True)
        self.guild_logo_label.setStyleSheet("background: transparent;")
        self._load_guild_logo()
        top_bar_layout.addWidget(self.guild_logo_label)

        content_layout.addWidget(top_bar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("""
            QStackedWidget {
                background-color: #0f3460;
            }
        """)

        self.analyze_view = AnalyzeView()
        self.history_view = HistoryView()
        self.raid_group_view = RaidGroupView()
        self.character_view = CharacterView()
        self.settings_view = SettingsView()

        self.stack.addWidget(self.analyze_view)
        self.stack.addWidget(self.history_view)
        self.stack.addWidget(self.raid_group_view)
        self.stack.addWidget(self.character_view)
        self.stack.addWidget(self.settings_view)

        content_layout.addWidget(self.stack, 1)
        layout.addWidget(content_wrapper, 1)

        # ── Status bar ──
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #16213e;
                color: #aaa;
                font-size: 11px;
                padding: 2px 10px;
            }
        """)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # ── Connect signals ──
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav_list.setCurrentRow(0)

        self.analyze_view.status_message.connect(self.status_bar.showMessage)
        self.history_view.status_message.connect(self.status_bar.showMessage)
        self.raid_group_view.status_message.connect(self.status_bar.showMessage)
        self.character_view.status_message.connect(self.status_bar.showMessage)
        self.character_view.analyze_report.connect(self._analyze_report)
        self.character_view.view_character_history.connect(self._go_to_character)
        self.analyze_view.navigate_to_character.connect(self._go_to_character)

    def _load_guild_logo(self):
        from .. import paths
        logo_path = str(paths.get_logo_path())

        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            self.guild_logo_label.setPixmap(pixmap)
        else:
            self.guild_logo_label.setText("")

    def _go_to_character(self, name: str):
        """Switch to History view and show the selected character."""
        self.nav_list.setCurrentRow(1)
        self.history_view.navigate_to_character(name)

    def _analyze_report(self, report_code: str):
        """Switch to Analyze view and start analysis for a report."""
        self.nav_list.setCurrentRow(0)
        self.analyze_view.set_report_id(report_code)
