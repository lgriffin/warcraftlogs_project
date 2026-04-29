"""
Main application window with sidebar navigation and drill-down support.
"""

import os
import sqlite3

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem,
    QStatusBar, QLabel,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QPixmap

from .download_view import DownloadView
from .raids_view import RaidsView
from .raid_group_view import RaidGroupView
from .character_view import CharacterView
from .settings_view import SettingsView
from .nav_stack import NavigationStack
from .raid_analysis_widget import RaidAnalysisWidget
from ..database import PerformanceDB


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
        sidebar.setStyleSheet("QWidget { background-color: #1a1a2e; }")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

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
            ("Download", "Fetch guild reports and analyze raids"),
            ("Raids", "Browse analyzed raids"),
            ("Raid Groups", "Manage raid groups and compare classes"),
            ("My Character", "View your character profile and rankings"),
            ("Settings", "Configure credentials and thresholds"),
        ]
        for name, tooltip in nav_items:
            item = QListWidgetItem(name)
            item.setToolTip(tooltip)
            item.setSizeHint(QSize(200, 48))
            self.nav_list.addItem(item)

        sidebar_layout.addWidget(self.nav_list)
        sidebar_layout.addStretch()

        version_label = QLabel("v3.4.0")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("color: #555; padding: 10px; font-size: 11px;")
        sidebar_layout.addWidget(version_label)

        layout.addWidget(sidebar)

        # ── Content area ──
        content_wrapper = QWidget()
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet("background-color: #16213e;")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 8, 16, 8)

        self._guild_name_label = QLabel()
        self._guild_name_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._guild_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._guild_name_label.setStyleSheet("color: #e94560; background: transparent;")
        top_bar_layout.addWidget(self._guild_name_label, 1)

        self.guild_logo_label = QLabel()
        self.guild_logo_label.setFixedSize(44, 44)
        self.guild_logo_label.setScaledContents(True)
        self.guild_logo_label.setStyleSheet("background: transparent;")
        self._load_guild_logo()
        top_bar_layout.addWidget(self.guild_logo_label)

        content_layout.addWidget(top_bar)

        # ── Navigation stack (replaces plain QStackedWidget) ──
        self.stack = NavigationStack()
        self.stack.setStyleSheet("QStackedWidget { background-color: #0f3460; }")

        self.download_view = DownloadView()
        self.raids_view = RaidsView()
        self.raid_group_view = RaidGroupView()
        self.character_view = CharacterView()
        self.settings_view = SettingsView()

        self.stack.addWidget(self.download_view)
        self.stack.addWidget(self.raids_view)
        self.stack.addWidget(self.raid_group_view)
        self.stack.addWidget(self.character_view)
        self.stack.addWidget(self.settings_view)
        self.stack.set_base_count(5)

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
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        self.nav_list.setCurrentRow(0)

        self.download_view.status_message.connect(self.status_bar.showMessage)
        self.download_view.raid_downloaded.connect(self._on_raid_downloaded)
        self.raids_view.status_message.connect(self.status_bar.showMessage)
        self.raids_view.open_raid.connect(self._drill_into_raid)
        self.raid_group_view.status_message.connect(self.status_bar.showMessage)
        self.raid_group_view.open_raid.connect(self._drill_into_raid)
        self.character_view.status_message.connect(self.status_bar.showMessage)
        self.character_view.analyze_report.connect(self._analyze_report)
        self.character_view.view_character_history.connect(self._drill_into_character_history)
        self.settings_view.status_message.connect(self._on_settings_saved)

        self._load_guild_info()

    def _on_nav_changed(self, index: int):
        self.stack.show_base_page(index)

    def _drill_into_raid(self, report_id: str):
        try:
            with PerformanceDB() as db:
                analysis = db.get_raid_analysis(report_id)
        except (sqlite3.Error, OSError) as e:
            self.status_bar.showMessage(f"Failed to load raid: {e}")
            return

        if not analysis:
            self.status_bar.showMessage(f"Raid {report_id} not found in database")
            return

        widget = RaidAnalysisWidget(analysis)
        widget.status_message.connect(self.status_bar.showMessage)
        widget.request_back.connect(self.stack.pop_view)
        widget.navigate_to_character.connect(self._drill_into_character_history)
        widget.raid_deleted.connect(self._on_raid_deleted)
        widget.cross_analyze.connect(self._drill_into_cross_analysis)
        self.stack.push_view(widget)

    def _drill_into_cross_analysis(self, report_id: str):
        from .raid_cross_analysis_widget import RaidCrossAnalysisWidget
        widget = RaidCrossAnalysisWidget(report_id)
        widget.status_message.connect(self.status_bar.showMessage)
        widget.request_back.connect(self.stack.pop_view)
        self.stack.push_view(widget)

    def _drill_into_character_history(self, name: str):
        from .character_history_widget import CharacterHistoryWidget
        widget = CharacterHistoryWidget(name)
        widget.status_message.connect(self.status_bar.showMessage)
        widget.request_back.connect(self.stack.pop_view)
        self.stack.push_view(widget)

    def _on_raid_downloaded(self):
        pass

    def _on_raid_deleted(self, report_id: str):
        pass

    def _analyze_report(self, report_code: str):
        self.nav_list.setCurrentRow(0)
        self.download_view._report_input.setText(report_code)
        self.download_view._analyze_single()

    def _load_guild_logo(self):
        from .. import paths
        logo_path = str(paths.get_logo_path())

        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            self.guild_logo_label.setPixmap(pixmap)
        else:
            self.guild_logo_label.setText("")

    def _on_settings_saved(self, msg: str):
        self.status_bar.showMessage(msg)
        if "saved" in msg.lower():
            self._load_guild_info()

    def _load_guild_info(self):
        try:
            from ..config import load_config
            config = load_config()
            guild_id = config.get("guild_id", 0)
            client_id = config.get("client_id", "")
            if not guild_id or not client_id:
                return
        except Exception:
            return

        from .worker import GuildInfoWorker
        self._guild_info_worker = GuildInfoWorker(guild_id)
        self._guild_info_worker.finished.connect(self._on_guild_info_loaded)
        self._guild_info_worker.start()

    def _on_guild_info_loaded(self, info: dict):
        name = info.get("name", "")
        server = info.get("server", "")
        if name and server:
            self._guild_name_label.setText(f"<{name}>  {server}")
        elif name:
            self._guild_name_label.setText(f"<{name}>")
        else:
            self._guild_name_label.setText("")
