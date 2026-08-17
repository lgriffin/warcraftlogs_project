"""
Main application window with sidebar navigation and drill-down support.
"""

import os
import sqlite3

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..database import PerformanceDB
from ..version import __version__
from .characters_hub import CharactersHub
from .dashboard_view import DashboardView
from .insights_view import InsightsView
from .nav_stack import NavigationStack
from .raid_analysis_widget import RaidAnalysisWidget
from .raid_group_view import RaidGroupView
from .raids_hub import RaidsHub
from .settings_view import SettingsView
from .styles import COLORS


class _UpdateCheckWorker(QThread):
    """Runs the update check off the main thread."""

    update_available = Signal(object)  # UpdateInfo or None

    def __init__(self, force: bool = False, parent=None):
        super().__init__(parent)
        self._force = force

    def run(self):
        from ..updater import check_for_update

        info = check_for_update(force=self._force)
        if info:
            self.update_available.emit(info)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WarcraftLogs Analyzer")
        self.setMinimumSize(1440, 960)
        self.resize(1800, 1140)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Sidebar ──
        self._sidebar = QWidget()
        self._sidebar.setFixedWidth(200)
        self._sidebar.setStyleSheet(f"QWidget {{ background-color: {COLORS['bg_mid']}; }}")
        self._sidebar_expanded = True
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        title_row = QWidget()
        title_row.setFixedHeight(60)
        title_row.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(0, 0, 4, 0)
        title_row_layout.setSpacing(0)

        self._sidebar_title = QLabel("WCL Analyzer")
        self._sidebar_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sidebar_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._sidebar_title.setStyleSheet(f"color: {COLORS['text_gold']}; background: transparent; padding: 10px;")
        title_row_layout.addWidget(self._sidebar_title, 1)

        self._sidebar_toggle = QPushButton("«")
        self._sidebar_toggle.setFixedSize(28, 28)
        self._sidebar_toggle.setToolTip("Toggle sidebar (Ctrl+B)")
        self._sidebar_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['text_dim']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_hover']};
                color: {COLORS['text']};
            }}
        """)
        self._sidebar_toggle.clicked.connect(self._toggle_sidebar)
        title_row_layout.addWidget(self._sidebar_toggle)

        sidebar_layout.addWidget(title_row)

        self.nav_list = QListWidget()
        self.nav_list.setIconSize(QSize(20, 20))
        self.nav_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_mid']};
                color: {COLORS['text']};
                border: none;
                font-size: 13px;
                padding-top: 10px;
            }}
            QListWidget::item {{
                padding: 14px 20px;
                border-left: 3px solid transparent;
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_card']};
                border-left: 3px solid {COLORS['accent']};
                color: {COLORS['text_gold']};
            }}
            QListWidget::item:hover:!selected {{
                background-color: {COLORS['bg_card']};
            }}
        """)

        nav_items = [
            ("Dashboard", "Overview and quick stats (Ctrl+1)"),
            ("Raids", "Download, browse, diff, and compare raids (Ctrl+2)"),
            ("Characters", "Search, profile, and compare characters (Ctrl+3)"),
            ("Insights", "Performance trends and boss analytics (Ctrl+4)"),
            ("Raid Groups", "Manage raid groups and members (Ctrl+5)"),
        ]
        for name, tooltip in nav_items:
            item = QListWidgetItem(name)
            item.setToolTip(tooltip)
            item.setSizeHint(QSize(200, 48))
            self.nav_list.addItem(item)

        sidebar_layout.addWidget(self.nav_list, 1)

        self._settings_btn = QPushButton("Settings")
        self._settings_btn.setToolTip("Settings (Ctrl+,)")
        self._settings_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_dim']};
                border: none;
                border-top: 1px solid {COLORS['border']};
                padding: 14px 20px;
                font-size: 13px;
                font-weight: normal;
                text-align: left;
                border-radius: 0;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_hover']};
                color: {COLORS['text']};
            }}
        """)
        self._settings_btn.clicked.connect(self._show_settings)
        sidebar_layout.addWidget(self._settings_btn)

        self._version_label = QLabel(f"v{__version__}")
        self._version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version_label.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 10px; font-size: 11px;")
        sidebar_layout.addWidget(self._version_label)

        layout.addWidget(self._sidebar)

        # ── Content area ──
        content_wrapper = QWidget()
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet(f"background-color: {COLORS['bg_card']};")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 8, 16, 8)

        self._guild_name_label = QLabel()
        self._guild_name_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._guild_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._guild_name_label.setStyleSheet(f"color: {COLORS['text_gold']}; background: transparent;")
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
        self.stack.setStyleSheet(f"QStackedWidget {{ background-color: {COLORS['bg_dark']}; }}")

        self.dashboard_view = DashboardView()
        self.raids_hub = RaidsHub()
        self.characters_hub = CharactersHub()
        self.insights_view = InsightsView()
        self.raid_group_view = RaidGroupView()
        self.settings_view = SettingsView()

        self.stack.addWidget(self.dashboard_view)
        self.stack.addWidget(self.raids_hub)
        self.stack.addWidget(self.characters_hub)
        self.stack.addWidget(self.insights_view)
        self.stack.addWidget(self.raid_group_view)
        self.stack.set_base_count(5)

        # Settings is outside the main nav — shown via _show_settings
        self.stack.addWidget(self.settings_view)

        content_layout.addWidget(self.stack, 1)
        layout.addWidget(content_wrapper, 1)

        # ── Status bar ──
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_dim']};
                font-size: 11px;
                padding: 2px 10px;
            }}
        """)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # ── Connect signals ──
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        self.nav_list.setCurrentRow(0)

        self.dashboard_view.status_message.connect(self.status_bar.showMessage)
        self.dashboard_view.open_raid.connect(self._drill_into_raid)
        self.dashboard_view.navigate_to_raids.connect(lambda: self.nav_list.setCurrentRow(1))

        self.raids_hub.status_message.connect(self.status_bar.showMessage)
        self.raids_hub.open_raid.connect(self._drill_into_raid)
        self.raids_hub.raid_downloaded.connect(self._on_raid_downloaded)

        self.characters_hub.status_message.connect(self.status_bar.showMessage)
        self.characters_hub.analyze_report.connect(self._analyze_report)

        self.insights_view.status_message.connect(self.status_bar.showMessage)

        self.raid_group_view.status_message.connect(self.status_bar.showMessage)
        self.raid_group_view.open_raid.connect(self._drill_into_raid)

        self.settings_view.status_message.connect(self._on_settings_saved)

        self._load_guild_info()

        self._pending_update = None
        self._update_label = None
        self._auto_check_updates()
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        for i in range(5):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            shortcut.activated.connect(lambda idx=i: self.nav_list.setCurrentRow(idx))
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self._show_settings)
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self._toggle_sidebar)

    def _toggle_sidebar(self):
        self._sidebar_expanded = not self._sidebar_expanded
        if self._sidebar_expanded:
            self._sidebar.setFixedWidth(200)
            self._sidebar_toggle.setText("«")
            self._sidebar_title.setVisible(True)
            self._settings_btn.setText("Settings")
            self._version_label.setVisible(True)
        else:
            self._sidebar.setFixedWidth(48)
            self._sidebar_toggle.setText("»")
            self._sidebar_title.setVisible(False)
            self._settings_btn.setText("")
            self._version_label.setVisible(False)

    def _auto_check_updates(self):
        try:
            from ..config import load_config

            config = load_config()
            if not config.get("auto_check_updates", True):
                return
        except Exception:
            pass
        QTimer.singleShot(3000, self._run_update_check)

    def _run_update_check(self, force: bool = False):
        if getattr(self, "_update_worker", None) and self._update_worker.isRunning():
            return

        self._update_worker = _UpdateCheckWorker(force=force, parent=self)
        self._update_worker.update_available.connect(self._on_update_available)
        self._update_worker.start()

    def _on_update_available(self, info):
        self._pending_update = info
        if self._update_label:
            self._update_label.deleteLater()

        self._update_label = QLabel(f"  Update available: v{info.version} — click to update  ")
        self._update_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['accent']};
                font-size: 11px;
                font-weight: bold;
                padding: 2px 8px;
                background: transparent;
            }}
            QLabel:hover {{
                color: {COLORS['accent_hover']};
                text-decoration: underline;
            }}
        """)
        self._update_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._update_label.mousePressEvent = lambda _: self._show_update_dialog()
        self.status_bar.addPermanentWidget(self._update_label)

    def _show_update_dialog(self):
        if not self._pending_update:
            return
        from .update_dialog import UpdateDialog

        dlg = UpdateDialog(self._pending_update, parent=self)
        dlg.exec()

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
        widget.raid_refreshed.connect(self._on_raid_refreshed)
        widget.cross_analyze.connect(self._drill_into_cross_analysis)
        widget.deep_dive.connect(self._drill_into_deep_dive)
        self.stack.push_view(widget)

    def _drill_into_deep_dive(self, report_id: str, encounter_index: int):
        from ..auth import TokenManager
        from ..client import WarcraftLogsClient
        from ..config import load_config
        from .encounter_deep_dive_view import EncounterDeepDiveView

        try:
            with PerformanceDB() as db:
                analysis = db.get_raid_analysis(report_id)
        except (sqlite3.Error, OSError) as e:
            self.status_bar.showMessage(f"Failed to load raid: {e}")
            return

        if not analysis or not analysis.encounters:
            self.status_bar.showMessage("No encounter data available for deep dive")
            return

        try:
            config = load_config()
            token_mgr = TokenManager(config["client_id"], config["client_secret"])
            client = WarcraftLogsClient(token_mgr)
        except Exception as e:
            self.status_bar.showMessage(f"Failed to create API client: {e}")
            return

        widget = EncounterDeepDiveView(
            client=client,
            report_id=report_id,
            encounters=analysis.encounters,
            composition=analysis.composition,
            consumable_usage=analysis.consumables,
            initial_index=encounter_index,
        )
        widget.status_message.connect(self.status_bar.showMessage)
        widget.request_back.connect(self.stack.pop_view)
        self.stack.push_view(widget)

    def _drill_into_cross_analysis(self, report_id: str):
        from .raid_cross_analysis_widget import RaidCrossAnalysisWidget

        widget = RaidCrossAnalysisWidget(report_id)
        widget.status_message.connect(self.status_bar.showMessage)
        widget.request_back.connect(self.stack.pop_view)
        widget.open_raid.connect(self._drill_into_raid)
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

    def _on_raid_refreshed(self, report_id: str):
        self.stack.pop_view()
        self._drill_into_raid(report_id)

    def _show_settings(self):
        self.nav_list.clearSelection()
        self.stack.show_base_page(5)

    def _analyze_report(self, report_code: str):
        self.nav_list.setCurrentRow(1)
        self.raids_hub.download_view._report_input.setText(report_code)
        self.raids_hub.download_view._analyze_single()

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

        if getattr(self, "_guild_info_worker", None) and self._guild_info_worker.isRunning():
            return

        self._guild_info_worker = GuildInfoWorker(guild_id)
        self._guild_info_worker.finished.connect(self._on_guild_info_loaded)
        self._guild_info_worker.start()

    def closeEvent(self, event):
        worker_attrs = ("_worker", "_guild_worker", "_wowhead_worker", "_auth_wait_thread")
        views = [
            self,
            self.raids_hub.download_view,
            self.characters_hub.character_view,
            self.raids_hub.reference_view,
            self.settings_view,
        ]
        workers = []
        for view in views:
            for attr in worker_attrs:
                w = getattr(view, attr, None)
                if w and w.isRunning():
                    w.quit()
                    workers.append(w)
        for attr in ("_guild_info_worker", "_update_worker"):
            w = getattr(self, attr, None)
            if w and w.isRunning():
                w.quit()
                workers.append(w)
        for w in workers:
            w.wait(5000)
        super().closeEvent(event)

    def _on_guild_info_loaded(self, info: dict):
        name = info.get("name", "")
        server = info.get("server", "")
        if name and server:
            self._guild_name_label.setText(f"<{name}>  {server}")
        elif name:
            self._guild_name_label.setText(f"<{name}>")
        else:
            self._guild_name_label.setText("")
