"""
Character Profile view — configure your main character, view WCL rankings,
recent reports, and stats.
"""

import json
import os
import webbrowser

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QHeaderView, QGroupBox, QProgressBar,
    QSplitter, QListWidget, QListWidgetItem, QLineEdit,
    QFormLayout, QMessageBox, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QFont, QColor, QDesktopServices
from PySide6.QtCore import QUrl

from .styles import COMMON_STYLES, COLORS
from .charts import SpiderChartWidget, CalendarHeatmapWidget
from .table_models import HistoryTableModel
from .worker import CharacterProfileWorker
from ..models import CharacterProfile, ZoneRankingResult, EncounterRanking
from ..database import PerformanceDB


class _RankingsTableModel(QAbstractTableModel):
    COLUMNS = ["Boss", "Best %", "Median %", "Kills", "Fastest", "Spec"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[EncounterRanking] = []

    def set_data(self, rankings: list[EncounterRanking]):
        self.beginResetModel()
        self._rows = rankings
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        r = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return r.encounter_name
            if col == 1:
                return f"{r.best_percent:.1f}%"
            if col == 2:
                return f"{r.median_percent:.1f}%"
            if col == 3:
                return r.total_kills
            if col == 4:
                return r.fastest_kill_formatted
            if col == 5:
                return r.spec

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col >= 1:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 1:
                return _percent_color(r.best_percent)

        return None


def _percent_color(pct: float):
    if pct >= 99:
        return QColor("#e268a8")
    if pct >= 95:
        return QColor("#ff8000")
    if pct >= 75:
        return QColor("#a335ee")
    if pct >= 50:
        return QColor("#0070dd")
    if pct >= 25:
        return QColor("#1eff00")
    return QColor("#9d9d9d")


CONFIG_PATH = "config.json"


class CharacterView(QWidget):
    status_message = Signal(str)
    analyze_report = Signal(str)
    view_character_history = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMMON_STYLES)
        self._worker = None
        self._profile = None
        self._build_ui()
        self._load_character_config()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {COLORS['bg_dark']}; }}
            QScrollArea > QWidget > QWidget {{ background-color: {COLORS['bg_dark']}; }}
        """)
        outer.addWidget(scroll)

        container = QWidget()
        container.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QLabel("Character Profile")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(header)

        # ── Character config ──
        config_group = QGroupBox("Character Settings")
        config_layout = QFormLayout(config_group)
        config_layout.setSpacing(10)

        self._char_name_input = QLineEdit()
        self._char_name_input.setPlaceholderText("e.g. Hadur")
        config_layout.addRow("Character Name:", self._char_name_input)

        self._char_server_input = QLineEdit()
        self._char_server_input.setPlaceholderText("e.g. spineshatter")
        config_layout.addRow("Server:", self._char_server_input)

        self._char_region_input = QLineEdit()
        self._char_region_input.setPlaceholderText("e.g. eu")
        config_layout.addRow("Region:", self._char_region_input)

        self._wcl_api_url_input = QLineEdit()
        self._wcl_api_url_input.setPlaceholderText("https://fresh.warcraftlogs.com/api/v2/client")
        config_layout.addRow("WCL API URL:", self._wcl_api_url_input)

        api_note = QLabel("Use fresh.warcraftlogs.com for Classic Fresh/SoD, www.warcraftlogs.com for retail/era.")
        api_note.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        api_note.setWordWrap(True)
        config_layout.addRow(api_note)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(80)
        save_btn.clicked.connect(self._save_character_config)
        btn_row.addWidget(save_btn)

        self._refresh_btn = QPushButton("Save && Refresh")
        self._refresh_btn.setFixedWidth(130)
        self._refresh_btn.clicked.connect(self._save_and_refresh)
        btn_row.addWidget(self._refresh_btn)

        btn_row.addStretch()
        config_layout.addRow(btn_row)

        layout.addWidget(config_group)

        # ── WCL profile link ──
        self._wcl_link = QLabel("")
        self._wcl_link.setOpenExternalLinks(True)
        self._wcl_link.setStyleSheet(f"color: {COLORS['accent']}; font-size: 12px;")
        layout.addWidget(self._wcl_link)

        # Progress
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # ── No-config message ──
        self._no_config_label = QLabel(
            "Enter your character name, server, and region above, then click Save & Refresh."
        )
        self._no_config_label.setWordWrap(True)
        self._no_config_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_config_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 14px; padding: 40px;")
        self._no_config_label.setVisible(False)
        layout.addWidget(self._no_config_label)

        # ── Main content ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: summary + rankings
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)

        # Summary card
        self._summary_group = QGroupBox("Summary")
        summary_layout = QVBoxLayout(self._summary_group)
        self._summary_labels = {}
        for key in ["Name", "Class", "Level", "Faction", "Guild",
                     "Best Avg", "Median Avg", "All Stars"]:
            row = QHBoxLayout()
            label = QLabel(f"{key}:")
            label.setFixedWidth(100)
            label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
            value = QLabel("-")
            value.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
            value.setWordWrap(True)
            self._summary_labels[key] = value
            row.addWidget(label)
            row.addWidget(value)
            row.addStretch()
            summary_layout.addLayout(row)

        history_btn = QPushButton("View History")
        history_btn.setFixedWidth(120)
        history_btn.clicked.connect(self._on_view_history)
        summary_layout.addWidget(history_btn)

        left_layout.addWidget(self._summary_group)

        # Rankings table
        rankings_label = QLabel("Encounter Rankings")
        rankings_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        rankings_label.setStyleSheet(f"color: {COLORS['text_header']};")
        left_layout.addWidget(rankings_label)

        self._rankings_model = _RankingsTableModel()
        self._rankings_table = QTableView()
        self._rankings_table.setModel(self._rankings_model)
        self._rankings_table.setAlternatingRowColors(True)
        self._rankings_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._rankings_table.setSortingEnabled(True)
        self._rankings_table.verticalHeader().setVisible(False)
        self._rankings_table.horizontalHeader().setStretchLastSection(True)
        self._rankings_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self._rankings_table.setStyleSheet(
            f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        left_layout.addWidget(self._rankings_table, 1)

        splitter.addWidget(left)

        # Right: recent reports
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)

        reports_label = QLabel("Recent Reports")
        reports_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        reports_label.setStyleSheet(f"color: {COLORS['text_header']};")
        right_layout.addWidget(reports_label)

        self._reports_list = QListWidget()
        self._reports_list.setStyleSheet(f"""
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
        self._reports_list.doubleClicked.connect(self._on_report_double_clicked)
        right_layout.addWidget(self._reports_list, 1)

        splitter.addWidget(right)
        splitter.setSizes([600, 400])

        layout.addWidget(splitter, 1)

        # ── Local Performance section ──
        self._local_perf_group = QGroupBox("Local Performance (from imported raids)")
        local_layout = QVBoxLayout(self._local_perf_group)

        # Summary row
        self._local_summary = QHBoxLayout()
        self._local_labels = {}
        for key in ["Raids Tracked", "Consistency", "Consumable Compliance"]:
            box = QVBoxLayout()
            title = QLabel(key)
            title.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val = QLabel("-")
            val.setStyleSheet(f"color: {COLORS['text']}; font-size: 16px; font-weight: bold;")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._local_labels[key] = val
            box.addWidget(title)
            box.addWidget(val)
            self._local_summary.addLayout(box)
        local_layout.addLayout(self._local_summary)

        # Tabs: Personal Bests | Radar | Calendar
        from PySide6.QtWidgets import QTabWidget
        self._local_tabs = QTabWidget()

        # Personal Bests tab
        self._local_bests_model = HistoryTableModel()
        bests_table = QTableView()
        bests_table.setModel(self._local_bests_model)
        bests_table.setAlternatingRowColors(True)
        bests_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        bests_table.verticalHeader().setVisible(False)
        bests_table.horizontalHeader().setStretchLastSection(True)
        bests_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        bests_table.setStyleSheet(
            f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        self._local_tabs.addTab(bests_table, "Personal Bests")

        # Radar tab
        self._local_spider_tab = QWidget()
        self._local_spider_layout = QVBoxLayout(self._local_spider_tab)
        self._local_spider_layout.setContentsMargins(0, 4, 0, 0)
        self._local_spider_widget = None
        self._local_tabs.addTab(self._local_spider_tab, "Radar")

        # Calendar tab
        self._local_calendar_tab = QWidget()
        self._local_calendar_layout = QVBoxLayout(self._local_calendar_tab)
        self._local_calendar_layout.setContentsMargins(0, 4, 0, 0)
        self._local_calendar_widget = None
        self._local_tabs.addTab(self._local_calendar_tab, "Calendar")

        local_layout.addWidget(self._local_tabs, 1)
        layout.addWidget(self._local_perf_group, 1)

    def _load_character_config(self):
        if not os.path.exists(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
            self._char_name_input.setText(config.get("character_name", ""))
            self._char_server_input.setText(config.get("character_server", ""))
            self._char_region_input.setText(config.get("character_region", "eu"))
            self._wcl_api_url_input.setText(
                config.get("wcl_api_url", "https://fresh.warcraftlogs.com/api/v2/client"))
        except Exception:
            pass

    def _save_character_config(self):
        config = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as f:
                    config = json.load(f)
            except Exception:
                pass

        config["character_name"] = self._char_name_input.text().strip()
        config["character_server"] = self._char_server_input.text().strip()
        config["character_region"] = self._char_region_input.text().strip() or "eu"
        config["wcl_api_url"] = (
            self._wcl_api_url_input.text().strip()
            or "https://fresh.warcraftlogs.com/api/v2/client"
        )

        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=4)
            self.status_message.emit("Character settings saved")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Could not save config:\n{e}")

    def _save_and_refresh(self):
        self._save_character_config()
        self._fetch_profile()

    def _update_wcl_link(self, name: str, server: str, region: str):
        api_url = self._wcl_api_url_input.text().strip()
        if "fresh." in api_url:
            base = "https://fresh.warcraftlogs.com"
        else:
            base = "https://www.warcraftlogs.com"
        url = f"{base}/character/{region}/{server}/{name}"
        self._wcl_link.setText(
            f'<a href="{url}" style="color: {COLORS["accent"]};">'
            f'View on WarcraftLogs: {url}</a>'
        )

    def _fetch_profile(self):
        char_name = self._char_name_input.text().strip()
        server = self._char_server_input.text().strip()
        region = self._char_region_input.text().strip() or "eu"
        api_url = (
            self._wcl_api_url_input.text().strip()
            or "https://fresh.warcraftlogs.com/api/v2/client"
        )

        if not char_name or not server:
            self._no_config_label.setVisible(True)
            self.status_message.emit("Enter character name and server above")
            return

        self._no_config_label.setVisible(False)
        self._update_wcl_link(char_name, server, region)
        self._refresh_btn.setEnabled(False)
        self._progress.setVisible(True)
        self.status_message.emit(f"Fetching profile for {char_name}...")

        self._worker = CharacterProfileWorker(char_name, server, region, api_url)
        self._worker.finished.connect(self._on_profile_loaded)
        self._worker.error.connect(self._on_profile_error)
        self._worker.start()

    def _on_profile_loaded(self, profile: CharacterProfile):
        self._profile = profile
        self._refresh_btn.setEnabled(True)
        self._progress.setVisible(False)

        self._summary_labels["Name"].setText(profile.name)
        self._summary_labels["Class"].setText(profile.class_name)
        self._summary_labels["Level"].setText(str(profile.level))
        self._summary_labels["Faction"].setText(profile.faction)
        self._summary_labels["Guild"].setText(profile.guild_name or "-")

        if profile.zone_rankings:
            zr = profile.zone_rankings[0]
            self._summary_labels["Best Avg"].setText(f"{zr.best_average:.1f}%")
            self._summary_labels["Median Avg"].setText(f"{zr.median_average:.1f}%")

            if zr.all_stars:
                star = zr.all_stars[0]
                self._summary_labels["All Stars"].setText(
                    f"{star.points:.0f}/{star.possible_points:.0f} pts  "
                    f"(#{star.rank:,} of {star.total:,} — {star.rank_percent:.1f}%)"
                )

            self._rankings_model.set_data(zr.encounter_rankings)
        else:
            self._summary_labels["Best Avg"].setText("-")
            self._summary_labels["Median Avg"].setText("-")
            self._summary_labels["All Stars"].setText("-")
            self._rankings_model.set_data([])

        self._reports_list.clear()
        cached_codes = set()
        try:
            with PerformanceDB() as db:
                cached_codes = db.get_imported_report_codes()
        except Exception:
            pass

        for r in profile.recent_reports:
            saved = "[Saved] " if r.code in cached_codes else ""
            item = QListWidgetItem(
                f"{saved}{r.date_formatted}  |  {r.zone_name}  |  {r.title}")
            item.setData(Qt.ItemDataRole.UserRole, r.code)
            if r.code in cached_codes:
                item.setForeground(QColor(COLORS['success']))
            self._reports_list.addItem(item)

        self._load_local_performance(profile.name)
        self.status_message.emit(f"Loaded profile for {profile.name}")

    def _load_local_performance(self, name: str):
        try:
            with PerformanceDB() as db:
                history = db.get_character_history(name)
                consistency = db.get_character_consistency(name)
                compliance = db.get_character_consumable_compliance(name)
                bests = db.get_character_personal_bests(name)
                spider_data = db.get_character_spider_data(name)
                calendar_data = db.get_character_raid_calendar(name)
        except Exception:
            return

        if history and history.total_raids > 0:
            self._local_labels["Raids Tracked"].setText(str(history.total_raids))
        else:
            self._local_labels["Raids Tracked"].setText("-")

        if consistency:
            scores = []
            for key in ("healing_consistency", "damage_consistency", "mitigation_consistency"):
                if key in consistency:
                    scores.append(consistency[key])
            if scores:
                avg = sum(scores) / len(scores)
                self._local_labels["Consistency"].setText(f"{avg:.1f}%")
            else:
                self._local_labels["Consistency"].setText("-")
        else:
            self._local_labels["Consistency"].setText("-")

        if compliance and compliance.get("total_raids", 0) > 0:
            pct = compliance["compliance_pct"]
            avg = compliance["avg_per_raid"]
            self._local_labels["Consumable Compliance"].setText(
                f"{pct:.0f}% ({avg:.1f}/raid)")
        else:
            self._local_labels["Consumable Compliance"].setText("-")

        if bests:
            self._local_bests_model.set_data(bests, ["label", "raid_date", "title", "value"])
        else:
            self._local_bests_model.set_data([], [])

        if self._local_spider_widget:
            self._local_spider_layout.removeWidget(self._local_spider_widget)
            self._local_spider_widget.deleteLater()
            self._local_spider_widget = None
        if spider_data:
            self._local_spider_widget = SpiderChartWidget(spider_data)
            self._local_spider_layout.addWidget(self._local_spider_widget)

        if self._local_calendar_widget:
            self._local_calendar_layout.removeWidget(self._local_calendar_widget)
            self._local_calendar_widget.deleteLater()
            self._local_calendar_widget = None
        if calendar_data:
            self._local_calendar_widget = CalendarHeatmapWidget(calendar_data)
            self._local_calendar_layout.addWidget(self._local_calendar_widget)

    def _on_profile_error(self, error_msg: str):
        self._refresh_btn.setEnabled(True)
        self._progress.setVisible(False)
        self.status_message.emit(f"Failed to load profile: {error_msg}")

    def _on_view_history(self):
        name = self._char_name_input.text().strip()
        if name:
            self.view_character_history.emit(name)

    def _on_report_double_clicked(self, index):
        item = self._reports_list.item(index.row())
        if item:
            code = item.data(Qt.ItemDataRole.UserRole)
            if code:
                self.analyze_report.emit(code)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._profile:
            char_name = self._char_name_input.text().strip()
            server = self._char_server_input.text().strip()
            if char_name and server:
                self._fetch_profile()
            else:
                self._no_config_label.setVisible(True)
