"""
Character Profile view — configure your main character, view WCL rankings,
recent reports, and performance trends from parsed raid history.
"""

import json
import os
import sqlite3
import webbrowser

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QHeaderView, QGroupBox, QProgressBar,
    QListWidget, QListWidgetItem, QLineEdit,
    QFormLayout, QMessageBox, QScrollArea, QTabWidget, QComboBox,
)
from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QFont, QColor

from .styles import COMMON_STYLES, COLORS
from .charts import SpiderChartWidget, CalendarHeatmapWidget
from .table_models import HistoryTableModel, GearTableModel
from .worker import CharacterProfileWorker, WowheadResolverWorker
from .charts import (
    build_healer_chart, build_healer_overheal_chart,
    build_tank_chart, build_tank_mitigation_chart,
    build_dps_chart, build_spell_trend_chart,
    build_consumable_trend_chart,
)
from ..models import CharacterProfile, ZoneRankingResult, EncounterRanking
from ..database import PerformanceDB


class _CollapsibleSection(QWidget):
    """A header bar that toggles visibility of its content widget."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle_btn = QPushButton(f"  {title}")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(True)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_header']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 13px;
                font-weight: bold;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {COLORS['border']};
            }}
        """)
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 8, 0, 0)
        content_layout.setSpacing(8)
        layout.addWidget(self._content)

        self._title = title
        self._update_arrow()

    def content_layout(self) -> QVBoxLayout:
        return self._content.layout()

    def set_collapsed(self, collapsed: bool):
        self._toggle_btn.setChecked(not collapsed)
        self._content.setVisible(not collapsed)
        self._update_arrow()

    def _on_toggle(self):
        visible = self._toggle_btn.isChecked()
        self._content.setVisible(visible)
        self._update_arrow()

    def _update_arrow(self):
        arrow = "v" if self._toggle_btn.isChecked() else ">"
        self._toggle_btn.setText(f"  {arrow}  {self._title}")


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


from .. import paths as _paths
CONFIG_PATH = str(_paths.get_config_path())


class CharacterView(QWidget):
    status_message = Signal(str)
    analyze_report = Signal(str)
    view_character_history = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMMON_STYLES)
        self._worker = None
        self._profile = None
        self._chart_widgets = {}
        self._all_healer_trend = []
        self._all_healer_spell_trend = []
        self._all_tank_trend = []
        self._all_dps_trend = []
        self._all_dps_ability_trend = []
        self._all_consumable_trend = []
        self._cached_healer_trend = []
        self._cached_healer_spell_trend = []
        self._cached_tank_trend = []
        self._cached_dps_trend = []
        self._cached_dps_ability_trend = []
        self._cached_consumable_trend = []
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
        layout.setSpacing(12)

        header = QLabel("Character Profile")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(header)

        # ── Character Settings (collapsible) ──
        self._config_section = _CollapsibleSection("Character Settings")
        config_inner = QWidget()
        config_layout = QFormLayout(config_inner)
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

        self._config_section.content_layout().addWidget(config_inner)
        layout.addWidget(self._config_section)

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

        # ── Summary card (always visible, compact) ──
        self._summary_group = QGroupBox("Summary")
        summary_layout = QHBoxLayout(self._summary_group)
        summary_layout.setSpacing(24)

        self._summary_labels = {}
        for key in ["Name", "Class", "Level", "Faction", "Guild",
                     "Best Avg", "Median Avg", "All Stars"]:
            col_widget = QWidget()
            col_layout = QVBoxLayout(col_widget)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(2)
            label = QLabel(key)
            label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel("-")
            value.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setWordWrap(True)
            self._summary_labels[key] = value
            col_layout.addWidget(label)
            col_layout.addWidget(value)
            summary_layout.addWidget(col_widget)

        layout.addWidget(self._summary_group)

        # ── Local DB stats row (raids tracked, avg stats) ──
        self._db_stats_group = QGroupBox("Raid History Stats")
        db_stats_layout = QHBoxLayout(self._db_stats_group)
        db_stats_layout.setSpacing(24)

        self._db_stats_labels = {}
        for key in ["Raids Tracked", "Active Period", "Avg Healing",
                     "Avg Damage", "Avg Mitigation", "Consumables Used"]:
            col_widget = QWidget()
            col_layout = QVBoxLayout(col_widget)
            col_layout.setContentsMargins(0, 0, 0, 0)
            col_layout.setSpacing(2)
            label = QLabel(key)
            label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel("-")
            value.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setWordWrap(True)
            self._db_stats_labels[key] = value
            col_layout.addWidget(label)
            col_layout.addWidget(value)
            db_stats_layout.addWidget(col_widget)

        layout.addWidget(self._db_stats_group)

        # ── Encounter Rankings (collapsible) ──
        self._rankings_section = _CollapsibleSection("Encounter Rankings")

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
        self._rankings_table.setMaximumHeight(250)

        self._rankings_section.content_layout().addWidget(self._rankings_table)
        layout.addWidget(self._rankings_section)

        # ── Recent Reports (collapsible) ──
        self._reports_section = _CollapsibleSection("Recent Reports")

        self._reports_list = QListWidget()
        self._reports_list.setMaximumHeight(200)
        self._reports_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 6px 12px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_dark']};
                border-left: 3px solid {COLORS['accent']};
            }}
        """)
        self._reports_list.doubleClicked.connect(self._on_report_double_clicked)

        self._reports_section.content_layout().addWidget(self._reports_list)
        self._reports_section.set_collapsed(True)
        layout.addWidget(self._reports_section)

        # ── Gear (collapsible) ──
        self._gear_section = _CollapsibleSection("Gear")
        self._gear_model = GearTableModel()
        self._gear_table = QTableView()
        self._gear_table.setModel(self._gear_model)
        self._gear_table.setAlternatingRowColors(True)
        self._gear_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._gear_table.verticalHeader().setVisible(False)
        self._gear_table.horizontalHeader().setStretchLastSection(True)
        self._gear_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self._gear_table.setStyleSheet(
            f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        self._gear_table.setMaximumHeight(400)
        self._gear_table.setMouseTracking(True)
        self._gear_table.clicked.connect(self._on_gear_clicked)

        self._gear_section.content_layout().addWidget(self._gear_table)
        self._gear_section.set_collapsed(True)
        layout.addWidget(self._gear_section)

        # ── Performance Trends (main content) ──
        trends_label = QLabel("Performance Trends")
        trends_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        trends_label.setStyleSheet(f"color: {COLORS['text_header']}; margin-top: 8px;")
        layout.addWidget(trends_label)

        self._no_trends_label = QLabel(
            "No raid history data yet. Analyze raids from the Analyze tab to build trend data."
        )
        self._no_trends_label.setWordWrap(True)
        self._no_trends_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_trends_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 13px; padding: 20px;")
        self._no_trends_label.setVisible(False)
        layout.addWidget(self._no_trends_label)

        combo_style = f"""
            QComboBox {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                min-width: 160px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                selection-background-color: {COLORS['bg_dark']};
            }}
        """

        raid_size_row = QHBoxLayout()
        raid_size_label = QLabel("Raid Size:")
        raid_size_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        raid_size_row.addWidget(raid_size_label)
        self._raid_size_combo = QComboBox()
        self._raid_size_combo.addItems(["All Raids", "10-man", "25-man"])
        self._raid_size_combo.setStyleSheet(combo_style)
        self._raid_size_combo.currentIndexChanged.connect(self._on_raid_size_changed)
        raid_size_row.addWidget(self._raid_size_combo)
        raid_size_row.addStretch()
        layout.addLayout(raid_size_row)

        self._trend_tabs = QTabWidget()

        # Healing tab
        healer_tab = QWidget()
        healer_layout = QVBoxLayout(healer_tab)
        healer_layout.setContentsMargins(0, 4, 0, 0)
        healer_bar = QHBoxLayout()
        healer_bar.addWidget(QLabel("Chart:"))
        self._healer_chart_combo = QComboBox()
        self._healer_chart_combo.addItems([
            "Healing & Overhealing", "Overheal %",
            "Spell Healing", "Spell Casts",
        ])
        self._healer_chart_combo.setStyleSheet(combo_style)
        self._healer_chart_combo.currentIndexChanged.connect(self._rebuild_healer_chart)
        healer_bar.addWidget(self._healer_chart_combo)
        healer_bar.addStretch()
        healer_layout.addLayout(healer_bar)
        self._healer_chart_container = QVBoxLayout()
        healer_layout.addLayout(self._healer_chart_container)
        self._healer_trend_model = HistoryTableModel()
        healer_layout.addWidget(self._make_trend_table(self._healer_trend_model), 1)
        self._trend_tabs.addTab(healer_tab, "Healing")

        # Tank tab
        tank_tab = QWidget()
        tank_layout = QVBoxLayout(tank_tab)
        tank_layout.setContentsMargins(0, 4, 0, 0)
        tank_bar = QHBoxLayout()
        tank_bar.addWidget(QLabel("Chart:"))
        self._tank_chart_combo = QComboBox()
        self._tank_chart_combo.addItems(["Damage & Mitigation", "Mitigation %"])
        self._tank_chart_combo.setStyleSheet(combo_style)
        self._tank_chart_combo.currentIndexChanged.connect(self._rebuild_tank_chart)
        tank_bar.addWidget(self._tank_chart_combo)
        tank_bar.addStretch()
        tank_layout.addLayout(tank_bar)
        self._tank_chart_container = QVBoxLayout()
        tank_layout.addLayout(self._tank_chart_container)
        self._tank_trend_model = HistoryTableModel()
        tank_layout.addWidget(self._make_trend_table(self._tank_trend_model), 1)
        self._trend_tabs.addTab(tank_tab, "Tank")

        # DPS tab
        dps_tab = QWidget()
        dps_layout = QVBoxLayout(dps_tab)
        dps_layout.setContentsMargins(0, 4, 0, 0)
        dps_bar = QHBoxLayout()
        dps_bar.addWidget(QLabel("Chart:"))
        self._dps_chart_combo = QComboBox()
        self._dps_chart_combo.addItems(["Total Damage", "Ability Damage", "Ability Casts"])
        self._dps_chart_combo.setStyleSheet(combo_style)
        self._dps_chart_combo.currentIndexChanged.connect(self._rebuild_dps_chart)
        dps_bar.addWidget(self._dps_chart_combo)
        dps_bar.addStretch()
        dps_layout.addLayout(dps_bar)
        self._dps_chart_container = QVBoxLayout()
        dps_layout.addLayout(self._dps_chart_container)
        self._dps_trend_model = HistoryTableModel()
        dps_layout.addWidget(self._make_trend_table(self._dps_trend_model), 1)
        self._trend_tabs.addTab(dps_tab, "DPS")

        # Consumables tab
        consumes_tab = QWidget()
        consumes_layout = QVBoxLayout(consumes_tab)
        consumes_layout.setContentsMargins(0, 4, 0, 0)
        self._consumes_chart_container = QVBoxLayout()
        consumes_layout.addLayout(self._consumes_chart_container)
        consumes_table_label = QLabel("Last 5 Raids")
        consumes_table_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; margin-top: 4px;")
        consumes_layout.addWidget(consumes_table_label)
        self._consumes_trend_model = HistoryTableModel()
        consumes_layout.addWidget(self._make_trend_table(self._consumes_trend_model), 1)
        self._trend_tabs.addTab(consumes_tab, "Consumables")

        self._trend_tabs.setMinimumHeight(420)
        layout.addWidget(self._trend_tabs)

        # ── Local Performance section ──
        self._local_perf_group = QGroupBox("Local Performance (from imported raids)")
        local_layout = QVBoxLayout(self._local_perf_group)

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

        self._local_tabs = QTabWidget()

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

        self._local_spider_tab = QWidget()
        self._local_spider_layout = QVBoxLayout(self._local_spider_tab)
        self._local_spider_layout.setContentsMargins(0, 4, 0, 0)
        self._local_spider_widget = None
        self._local_tabs.addTab(self._local_spider_tab, "Radar")

        self._local_calendar_tab = QWidget()
        self._local_calendar_layout = QVBoxLayout(self._local_calendar_tab)
        self._local_calendar_layout.setContentsMargins(0, 4, 0, 0)
        self._local_calendar_widget = None
        self._local_tabs.addTab(self._local_calendar_tab, "Calendar")

        local_layout.addWidget(self._local_tabs, 1)
        layout.addWidget(self._local_perf_group, 1)

    def _make_trend_table(self, model) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setStyleSheet(
            f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        return table

    # ── Config persistence ──

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
            if config.get("character_name") and config.get("character_server"):
                self._config_section.set_collapsed(True)
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    def _save_character_config(self):
        config = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError):
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
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.critical(self, "Save Error", f"Could not save config:\n{e}")

    def _save_and_refresh(self):
        self._save_character_config()
        self._config_section.set_collapsed(True)
        self._fetch_profile()

    # ── WCL profile fetch ──

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
                    f"(#{star.rank:,} of {star.total:,})"
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
        except (sqlite3.Error, OSError):
            pass

        for r in profile.recent_reports:
            saved = "[Saved] " if r.code in cached_codes else ""
            item = QListWidgetItem(
                f"{saved}{r.date_formatted}  |  {r.zone_name}  |  {r.title}")
            item.setData(Qt.ItemDataRole.UserRole, r.code)
            if r.code in cached_codes:
                item.setForeground(QColor(COLORS['success']))
            self._reports_list.addItem(item)

        self._gear_model.set_data(profile.gear_items)
        if profile.gear_items:
            item_ids = [g.item_id for g in profile.gear_items if g.item_id]
            gem_ids = [gid for g in profile.gear_items for gid in g.gems if gid]
            self._wowhead_worker = WowheadResolverWorker(item_ids + gem_ids)
            self._wowhead_worker.finished.connect(self._on_wowhead_resolved)
            self._wowhead_worker.start()

        self._load_local_performance(profile.name)
        self._load_trends(profile.name)
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
        except (sqlite3.Error, OSError):
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
        char_name = self._char_name_input.text().strip()
        if char_name:
            self._load_trends(char_name)

    # ── Performance trends from local DB ──

    def _load_trends(self, character_name: str):
        try:
            from ..database import PerformanceDB
            with PerformanceDB() as db:
                history = db.get_character_history(character_name)
                if not history or history.total_raids == 0:
                    self._no_trends_label.setVisible(True)
                    self._trend_tabs.setVisible(False)
                    self._db_stats_group.setVisible(False)
                    return

                self._no_trends_label.setVisible(False)
                self._trend_tabs.setVisible(True)
                self._db_stats_group.setVisible(True)

                self._db_stats_labels["Raids Tracked"].setText(str(history.total_raids))
                if history.first_seen and history.last_seen:
                    period = (f"{history.first_seen.strftime('%Y-%m-%d')} to "
                              f"{history.last_seen.strftime('%Y-%m-%d')}")
                    self._db_stats_labels["Active Period"].setText(period)
                else:
                    self._db_stats_labels["Active Period"].setText("-")
                self._db_stats_labels["Avg Healing"].setText(
                    f"{history.avg_healing:,.0f}" if history.avg_healing else "-")
                self._db_stats_labels["Avg Damage"].setText(
                    f"{history.avg_damage:,.0f}" if history.avg_damage else "-")
                self._db_stats_labels["Avg Mitigation"].setText(
                    f"{history.avg_mitigation_percent:.1f}%" if history.avg_mitigation_percent else "-")
                self._db_stats_labels["Consumables Used"].setText(
                    str(history.total_consumables_used))

                self._all_healer_trend = db.get_healer_trend(character_name)
                self._all_healer_spell_trend = (
                    db.get_healer_spell_trend(character_name) if self._all_healer_trend else [])
                self._all_tank_trend = db.get_tank_trend(character_name)
                self._all_dps_trend = db.get_dps_trend(character_name)
                self._all_dps_ability_trend = (
                    db.get_dps_ability_trend(character_name) if self._all_dps_trend else [])
                self._all_consumable_trend = db.get_consumable_trend(character_name)

                consumes_summary = db.get_consumable_summary(character_name, limit=5)
                if consumes_summary:
                    all_consumable_names = set()
                    for row in consumes_summary:
                        for k in row:
                            if k not in ("raid_date", "title", "report_id"):
                                all_consumable_names.add(k)
                    cols = ["raid_date", "title"] + sorted(all_consumable_names)
                    self._consumes_trend_model.set_data(consumes_summary, cols)
                else:
                    self._consumes_trend_model.set_data([], [])

                self._apply_raid_size_filter()

        except (sqlite3.Error, OSError, KeyError) as e:
            self._no_trends_label.setText(
                f"Could not load trend data: {e}")
            self._no_trends_label.setVisible(True)
            self._trend_tabs.setVisible(False)
            self._db_stats_group.setVisible(False)

    # ── Raid size filtering ──

    @staticmethod
    def _filter_by_raid_size(rows: list[dict], mode: int) -> list[dict]:
        if mode == 0:
            return rows
        if mode == 1:
            return [r for r in rows if r.get("raid_size") is not None and r["raid_size"] <= 15]
        return [r for r in rows if r.get("raid_size") is not None and r["raid_size"] > 15]

    def _on_raid_size_changed(self):
        self._apply_raid_size_filter()

    def _apply_raid_size_filter(self):
        mode = self._raid_size_combo.currentIndex()

        self._cached_healer_trend = self._filter_by_raid_size(self._all_healer_trend, mode)
        self._cached_healer_spell_trend = self._filter_by_raid_size(self._all_healer_spell_trend, mode)
        self._cached_tank_trend = self._filter_by_raid_size(self._all_tank_trend, mode)
        self._cached_dps_trend = self._filter_by_raid_size(self._all_dps_trend, mode)
        self._cached_dps_ability_trend = self._filter_by_raid_size(self._all_dps_ability_trend, mode)
        self._cached_consumable_trend = self._filter_by_raid_size(self._all_consumable_trend, mode)

        if self._cached_healer_trend:
            self._healer_trend_model.set_data(
                self._cached_healer_trend,
                ["raid_date", "title", "raid_size", "total_healing", "total_overhealing", "overheal_percent"])
        else:
            self._healer_trend_model.set_data([], [])
        self._rebuild_healer_chart()

        if self._cached_tank_trend:
            self._tank_trend_model.set_data(
                self._cached_tank_trend,
                ["raid_date", "title", "raid_size", "total_damage_taken", "total_mitigated", "mitigation_percent"])
        else:
            self._tank_trend_model.set_data([], [])
        self._rebuild_tank_chart()

        if self._cached_dps_trend:
            self._dps_trend_model.set_data(
                self._cached_dps_trend,
                ["raid_date", "title", "raid_size", "role", "total_damage"])
        else:
            self._dps_trend_model.set_data([], [])
        self._rebuild_dps_chart()

        if self._cached_consumable_trend:
            self._rebuild_consumable_chart()
        else:
            self._consumes_trend_model.set_data([], [])
            self._clear_chart(self._consumes_chart_container, "consumes")

        if self._cached_healer_trend:
            self._trend_tabs.setCurrentIndex(0)
        elif self._cached_tank_trend:
            self._trend_tabs.setCurrentIndex(1)
        elif self._cached_dps_trend:
            self._trend_tabs.setCurrentIndex(2)
        elif self._cached_consumable_trend:
            self._trend_tabs.setCurrentIndex(3)

    # ── Chart rebuild handlers ──

    def _clear_chart(self, container_layout: QVBoxLayout, key: str):
        old = self._chart_widgets.get(key)
        if old:
            container_layout.removeWidget(old)
            old.deleteLater()
            self._chart_widgets.pop(key, None)

    def _set_chart(self, container_layout: QVBoxLayout, key: str, chart_view):
        self._clear_chart(container_layout, key)
        self._chart_widgets[key] = chart_view
        container_layout.insertWidget(0, chart_view)

    def _rebuild_healer_chart(self):
        choice = self._healer_chart_combo.currentIndex()
        trend = self._cached_healer_trend
        spell_trend = self._cached_healer_spell_trend

        if not trend:
            self._clear_chart(self._healer_chart_container, "healer")
            return

        if choice == 0:
            view = build_healer_chart(trend)
        elif choice == 1:
            view = build_healer_overheal_chart(trend)
        elif choice == 2:
            view = build_spell_trend_chart(
                spell_trend, "total_healing", "Spell Healing Over Time", "Healing")
        elif choice == 3:
            view = build_spell_trend_chart(
                spell_trend, "casts", "Spell Casts Over Time", "Casts")
        else:
            return
        self._set_chart(self._healer_chart_container, "healer", view)

    def _rebuild_tank_chart(self):
        choice = self._tank_chart_combo.currentIndex()
        trend = self._cached_tank_trend

        if not trend:
            self._clear_chart(self._tank_chart_container, "tank")
            return

        if choice == 0:
            view = build_tank_chart(trend)
        elif choice == 1:
            view = build_tank_mitigation_chart(trend)
        else:
            return
        self._set_chart(self._tank_chart_container, "tank", view)

    def _rebuild_dps_chart(self):
        choice = self._dps_chart_combo.currentIndex()
        trend = self._cached_dps_trend
        ability_trend = self._cached_dps_ability_trend

        if not trend:
            self._clear_chart(self._dps_chart_container, "dps")
            return

        if choice == 0:
            view = build_dps_chart(trend)
        elif choice == 1:
            view = build_spell_trend_chart(
                ability_trend, "total_damage", "Ability Damage Over Time", "Damage")
        elif choice == 2:
            view = build_spell_trend_chart(
                ability_trend, "casts", "Ability Casts Over Time", "Casts")
        else:
            return
        self._set_chart(self._dps_chart_container, "dps", view)

    def _rebuild_consumable_chart(self):
        trend = self._cached_consumable_trend
        if not trend:
            self._clear_chart(self._consumes_chart_container, "consumes")
            return
        view = build_consumable_trend_chart(trend)
        self._set_chart(self._consumes_chart_container, "consumes", view)

    # ── Event handlers ──

    def _on_view_history(self):
        name = self._char_name_input.text().strip()
        if name:
            self.view_character_history.emit(name)

    @staticmethod
    def _wowhead_slug(name: str) -> str:
        import re
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    def _wowhead_item_url(self, item_id: int) -> str:
        name = self._gear_model._names.get(item_id)
        slug = f"/{self._wowhead_slug(name)}" if name else ""
        return f"https://www.wowhead.com/tbc/item={item_id}{slug}"

    def _on_gear_clicked(self, index: QModelIndex):
        if index.row() >= len(self._gear_model._items):
            return
        item = self._gear_model._items[index.row()]
        col = index.column()
        if col == 1 and item.item_id:
            webbrowser.open(self._wowhead_item_url(item.item_id))
        elif col == 4 and item.gems:
            webbrowser.open(self._wowhead_item_url(item.gems[0]))

    def _on_wowhead_resolved(self, result: dict):
        self._gear_model.set_resolved(result["items"], result["tooltips"])

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
            elif char_name:
                self._load_trends(char_name)
            else:
                self._no_config_label.setVisible(True)
