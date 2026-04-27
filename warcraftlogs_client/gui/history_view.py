"""
History view — browse historical character performance and past raid analyses.
"""

import sqlite3
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QTableView, QHeaderView, QGroupBox,
    QSplitter, QListWidget, QListWidgetItem, QTabWidget,
    QTextEdit, QMessageBox, QFileDialog, QStyledItemDelegate, QStyle,
)
from PySide6.QtCore import Qt, Signal, QModelIndex, QRect, QSize
from PySide6.QtGui import QFont, QCursor, QPainter, QColor, QPen, QBrush

from .detail_panel import CharacterDetailPanel

from .styles import COMMON_STYLES, COLORS
from .charts import (
    build_healer_chart, build_healer_overheal_chart,
    build_tank_chart, build_tank_mitigation_chart,
    build_dps_chart, build_spell_trend_chart,
    build_consumable_trend_chart,
    SpiderChartWidget, CalendarHeatmapWidget,
)
from .table_models import (
    HistoryTableModel, HealerTableModel, TankTableModel, DPSTableModel,
)
from ..database import PerformanceDB


TAG_COLORS = [
    "#e94560", "#2ecc71", "#3498db", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#e74c3c", "#00cec9", "#fd79a8",
]


class _TagDelegate(QStyledItemDelegate):
    """Draws character name + raid group tags as colored pills."""

    def paint(self, painter: QPainter, option, index):
        self.initStyleOption(option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(COLORS['bg_dark']))
        else:
            painter.fillRect(option.rect, QColor(COLORS['bg_card']))

        tags = index.data(Qt.ItemDataRole.UserRole + 1) or []
        display = index.data(Qt.ItemDataRole.DisplayRole) or ""

        painter.setPen(QColor(COLORS['text']))
        painter.setFont(option.font)
        text_rect = QRect(option.rect)
        text_rect.setLeft(text_rect.left() + 12)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, display)

        if tags:
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(display)
            x = option.rect.left() + 12 + text_width + 10
            tag_font = QFont(option.font)
            tag_font.setPointSize(max(7, option.font.pointSize() - 2))
            tag_font.setBold(True)
            painter.setFont(tag_font)
            tag_fm = painter.fontMetrics()

            for i, tag in enumerate(tags):
                color = QColor(TAG_COLORS[i % len(TAG_COLORS)])
                tw = tag_fm.horizontalAdvance(tag) + 12
                th = tag_fm.height() + 4
                ty = option.rect.center().y() - th // 2

                pill = QRect(int(x), int(ty), int(tw), int(th))
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(pill, 6, 6)

                painter.setPen(QColor("#fff"))
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, tag)

                x += tw + 4

        painter.restore()

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(base.height(), 32))


class HistoryView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMMON_STYLES)
        self._chart_widgets = {}
        self._current_raid_analysis = None
        self._group_map: dict[str, list[str]] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QLabel("History")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(header)

        self.top_tabs = QTabWidget()
        self.top_tabs.addTab(self._build_characters_tab(), "Characters")
        self.top_tabs.addTab(self._build_raids_tab(), "Raids")
        layout.addWidget(self.top_tabs, 1)

    # ── Characters tab ──

    def _build_characters_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 12, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: character list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 8, 0)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search characters...")
        self.search_input.textChanged.connect(self._filter_characters)
        search_layout.addWidget(self.search_input)

        refresh_btn = QPushButton("  Refresh  ")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.clicked.connect(self._load_characters)
        search_layout.addWidget(refresh_btn)
        left_layout.addLayout(search_layout)

        group_filter_layout = QHBoxLayout()
        group_filter_label = QLabel("Group:")
        group_filter_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        group_filter_layout.addWidget(group_filter_label)
        self._group_filter_combo = QComboBox()
        self._group_filter_combo.setMinimumWidth(140)
        self._group_filter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px; padding: 4px 8px;
                font-size: 11px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                selection-background-color: {COLORS['bg_dark']};
            }}
        """)
        self._group_filter_combo.currentIndexChanged.connect(self._apply_group_filter)
        group_filter_layout.addWidget(self._group_filter_combo)
        group_filter_layout.addStretch()
        left_layout.addLayout(group_filter_layout)

        self.char_list = QListWidget()
        self.char_list.setItemDelegate(_TagDelegate(self.char_list))
        self.char_list.setStyleSheet(f"""
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
        self.char_list.currentItemChanged.connect(self._on_character_selected)
        left_layout.addWidget(self.char_list)
        splitter.addWidget(left_panel)

        # Right: character detail
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)

        self.summary_card = QGroupBox("Character Summary")
        summary_layout = QVBoxLayout(self.summary_card)
        self.summary_labels = {}
        for key in ["Name", "Class", "Raid Groups", "Raids Tracked", "Active Period",
                     "Avg Healing", "Avg Damage", "Avg Mitigation", "Consumables Used",
                     "Consistency", "Consumable Compliance"]:
            row = QHBoxLayout()
            label = QLabel(f"{key}:")
            label.setFixedWidth(130)
            label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
            value = QLabel("-")
            value.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
            self.summary_labels[key] = value
            row.addWidget(label)
            row.addWidget(value)
            row.addStretch()
            summary_layout.addLayout(row)
        right_layout.addWidget(self.summary_card)

        self.char_trend_tabs = QTabWidget()

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
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                selection-background-color: {COLORS['bg_dark']};
            }}
        """

        # Healing tab: dropdown + chart + table
        self._healer_tab = QWidget()
        healer_tab_layout = QVBoxLayout(self._healer_tab)
        healer_tab_layout.setContentsMargins(0, 4, 0, 0)
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
        healer_tab_layout.addLayout(healer_bar)
        self._healer_chart_container = QVBoxLayout()
        healer_tab_layout.addLayout(self._healer_chart_container)
        self.healer_trend_model = HistoryTableModel()
        healer_tab_layout.addWidget(self._make_history_table(self.healer_trend_model), 1)
        self.char_trend_tabs.addTab(self._healer_tab, "Healing Trend")

        # Tank tab: dropdown + chart + table
        self._tank_tab = QWidget()
        tank_tab_layout = QVBoxLayout(self._tank_tab)
        tank_tab_layout.setContentsMargins(0, 4, 0, 0)
        tank_bar = QHBoxLayout()
        tank_bar.addWidget(QLabel("Chart:"))
        self._tank_chart_combo = QComboBox()
        self._tank_chart_combo.addItems([
            "Damage & Mitigation", "Mitigation %",
        ])
        self._tank_chart_combo.setStyleSheet(combo_style)
        self._tank_chart_combo.currentIndexChanged.connect(self._rebuild_tank_chart)
        tank_bar.addWidget(self._tank_chart_combo)
        tank_bar.addStretch()
        tank_tab_layout.addLayout(tank_bar)
        self._tank_chart_container = QVBoxLayout()
        tank_tab_layout.addLayout(self._tank_chart_container)
        self.tank_trend_model = HistoryTableModel()
        tank_tab_layout.addWidget(self._make_history_table(self.tank_trend_model), 1)
        self.char_trend_tabs.addTab(self._tank_tab, "Tank Trend")

        # DPS tab: dropdown + chart + table
        self._dps_tab = QWidget()
        dps_tab_layout = QVBoxLayout(self._dps_tab)
        dps_tab_layout.setContentsMargins(0, 4, 0, 0)
        dps_bar = QHBoxLayout()
        dps_bar.addWidget(QLabel("Chart:"))
        self._dps_chart_combo = QComboBox()
        self._dps_chart_combo.addItems([
            "Total Damage", "Ability Damage", "Ability Casts",
        ])
        self._dps_chart_combo.setStyleSheet(combo_style)
        self._dps_chart_combo.currentIndexChanged.connect(self._rebuild_dps_chart)
        dps_bar.addWidget(self._dps_chart_combo)
        dps_bar.addStretch()
        dps_tab_layout.addLayout(dps_bar)
        self._dps_chart_container = QVBoxLayout()
        dps_tab_layout.addLayout(self._dps_chart_container)
        self.dps_trend_model = HistoryTableModel()
        dps_tab_layout.addWidget(self._make_history_table(self.dps_trend_model), 1)
        self.char_trend_tabs.addTab(self._dps_tab, "DPS Trend")

        # Consumables tab: chart + last-5-raids table
        self._consumes_tab = QWidget()
        consumes_tab_layout = QVBoxLayout(self._consumes_tab)
        consumes_tab_layout.setContentsMargins(0, 4, 0, 0)
        self._consumes_chart_container = QVBoxLayout()
        consumes_tab_layout.addLayout(self._consumes_chart_container)
        consumes_table_label = QLabel("Last 5 Raids")
        consumes_table_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; margin-top: 4px;")
        consumes_tab_layout.addWidget(consumes_table_label)
        self.consumes_trend_model = HistoryTableModel()
        consumes_tab_layout.addWidget(self._make_history_table(self.consumes_trend_model), 1)
        self.char_trend_tabs.addTab(self._consumes_tab, "Consumables")

        # Personal Bests/Worsts tab
        self._bests_tab = QWidget()
        bests_tab_layout = QVBoxLayout(self._bests_tab)
        bests_tab_layout.setContentsMargins(0, 4, 0, 0)
        self._bests_model = HistoryTableModel()
        bests_table = self._make_history_table(self._bests_model)
        bests_tab_layout.addWidget(bests_table, 1)
        self.char_trend_tabs.addTab(self._bests_tab, "Personal Bests")

        # Spider Chart tab
        self._spider_tab = QWidget()
        self._spider_tab_layout = QVBoxLayout(self._spider_tab)
        self._spider_tab_layout.setContentsMargins(0, 4, 0, 0)
        self._spider_widget = None
        self.char_trend_tabs.addTab(self._spider_tab, "Radar")

        # Calendar Heatmap tab
        self._calendar_tab = QWidget()
        self._calendar_tab_layout = QVBoxLayout(self._calendar_tab)
        self._calendar_tab_layout.setContentsMargins(0, 4, 0, 0)
        self._calendar_widget = None
        self.char_trend_tabs.addTab(self._calendar_tab, "Calendar")

        # Cache for trend data used by chart rebuilds
        self._cached_healer_trend = []
        self._cached_healer_spell_trend = []
        self._cached_tank_trend = []
        self._cached_dps_trend = []
        self._cached_dps_ability_trend = []
        self._cached_consumable_trend = []
        self._current_char_name = None

        right_layout.addWidget(self.char_trend_tabs, 1)
        splitter.addWidget(right_panel)
        splitter.setSizes([280, 720])

        layout.addWidget(splitter, 1)
        return widget

    # ── Raids tab ──

    def _build_raids_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 12, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: raid list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 8, 0)

        search_layout = QHBoxLayout()
        self.raid_search_input = QLineEdit()
        self.raid_search_input.setPlaceholderText("Search raids...")
        self.raid_search_input.textChanged.connect(self._filter_raids)
        search_layout.addWidget(self.raid_search_input)

        raid_refresh_btn = QPushButton("  Refresh  ")
        raid_refresh_btn.setProperty("secondary", True)
        raid_refresh_btn.clicked.connect(self._load_raids)
        search_layout.addWidget(raid_refresh_btn)
        left_layout.addLayout(search_layout)

        # Day-of-week filter
        day_filter_layout = QHBoxLayout()
        day_filter_layout.setSpacing(4)
        filter_label = QLabel("Days:")
        filter_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        day_filter_layout.addWidget(filter_label)

        self._raid_day_checkboxes = {}
        days = [("Mon", 0), ("Tue", 1), ("Wed", 2), ("Thu", 3),
                ("Fri", 4), ("Sat", 5), ("Sun", 6)]
        defaults_on = {2, 3, 6}
        for label, idx in days:
            day_label = QLabel(label)
            day_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 11px;")
            day_filter_layout.addWidget(day_label)
            cb = QCheckBox()
            cb.setChecked(idx in defaults_on)
            cb.setStyleSheet("font-size: 11px;")
            cb.toggled.connect(self._apply_raid_day_filter)
            self._raid_day_checkboxes[idx] = cb
            day_filter_layout.addWidget(cb)
        day_filter_layout.addStretch()
        left_layout.addLayout(day_filter_layout)

        self.raid_list = QListWidget()
        self.raid_list.setStyleSheet(f"""
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
        self.raid_list.currentItemChanged.connect(self._on_raid_selected)
        left_layout.addWidget(self.raid_list)

        # Delete raid button
        self.delete_raid_btn = QPushButton("Delete Selected Raid")
        self.delete_raid_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['error']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #c0392b;
            }}
        """)
        self.delete_raid_btn.clicked.connect(self._delete_selected_raid)
        left_layout.addWidget(self.delete_raid_btn)

        splitter.addWidget(left_panel)

        # Right: results + detail side panel in a horizontal splitter
        self._raid_right_splitter = QSplitter(Qt.Orientation.Horizontal)

        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setContentsMargins(8, 0, 0, 0)

        raid_info_row = QHBoxLayout()
        self.raid_info_label = QLabel("")
        self.raid_info_label.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                padding: 10px 16px;
                border-radius: 6px;
                font-size: 13px;
            }}
        """)
        self.raid_info_label.setVisible(False)
        raid_info_row.addWidget(self.raid_info_label, 1)

        self.raid_export_btn = QPushButton("  Export Markdown  ")
        self.raid_export_btn.setProperty("secondary", True)
        self.raid_export_btn.setVisible(False)
        self.raid_export_btn.clicked.connect(self._export_raid_markdown)
        raid_info_row.addWidget(self.raid_export_btn)

        results_layout.addLayout(raid_info_row)

        self.raid_detail_tabs = QTabWidget()

        self.raid_healer_model = HealerTableModel()
        self.raid_detail_tabs.addTab(self._make_raid_table(self.raid_healer_model), "Healers")

        self.raid_tank_model = TankTableModel()
        self.raid_detail_tabs.addTab(self._make_raid_table(self.raid_tank_model), "Tanks")

        self.raid_melee_model = DPSTableModel()
        self.raid_detail_tabs.addTab(self._make_raid_table(self.raid_melee_model), "Melee DPS")

        self.raid_ranged_model = DPSTableModel()
        self.raid_detail_tabs.addTab(self._make_raid_table(self.raid_ranged_model), "Ranged DPS")

        # Raid consumables tab with filter dropdown
        raid_consumes_widget = QWidget()
        raid_consumes_layout = QVBoxLayout(raid_consumes_widget)
        raid_consumes_layout.setContentsMargins(0, 4, 0, 0)

        raid_consumes_bar = QHBoxLayout()
        raid_consumes_bar.addWidget(QLabel("Filter:"))
        self._raid_consumes_filter_combo = QComboBox()
        self._raid_consumes_filter_combo.setMinimumWidth(180)
        self._raid_consumes_filter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                selection-background-color: {COLORS['bg_dark']};
            }}
        """)
        self._raid_consumes_filter_combo.currentIndexChanged.connect(self._apply_raid_consumes_filter)
        raid_consumes_bar.addWidget(self._raid_consumes_filter_combo)
        raid_consumes_bar.addStretch()
        raid_consumes_layout.addLayout(raid_consumes_bar)

        self._raid_consumes_model = HistoryTableModel()
        raid_consumes_table = QTableView()
        raid_consumes_table.setModel(self._raid_consumes_model)
        raid_consumes_table.setAlternatingRowColors(True)
        raid_consumes_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        raid_consumes_table.setSortingEnabled(True)
        raid_consumes_table.verticalHeader().setVisible(False)
        raid_consumes_table.horizontalHeader().setStretchLastSection(True)
        raid_consumes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        raid_consumes_table.setStyleSheet(f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        raid_consumes_layout.addWidget(raid_consumes_table, 1)
        self.raid_detail_tabs.addTab(raid_consumes_widget, "Consumables")

        self.raid_comp_text = QTextEdit()
        self.raid_comp_text.setReadOnly(True)
        self.raid_comp_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: none;
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 13px;
                padding: 12px;
            }}
        """)
        self.raid_detail_tabs.addTab(self.raid_comp_text, "Composition")

        results_layout.addWidget(self.raid_detail_tabs, 1)
        self._raid_right_splitter.addWidget(results_widget)

        # Character detail side panel
        self.raid_detail_panel = CharacterDetailPanel()
        self.raid_detail_panel.setMinimumWidth(350)
        self.raid_detail_panel.view_history.connect(self.navigate_to_character)
        self.raid_detail_panel.closed.connect(lambda: self._raid_right_splitter.setSizes([1, 0]))
        self._raid_right_splitter.addWidget(self.raid_detail_panel)
        self._raid_right_splitter.setSizes([1, 0])

        splitter.addWidget(self._raid_right_splitter)
        splitter.setSizes([300, 700])

        layout.addWidget(splitter, 1)
        return widget

    # ── Shared table builders ──

    def _make_history_table(self, model) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setStyleSheet(f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        return table

    def _make_raid_table(self, model) -> QTableView:
        table = _ClickableNameTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setStyleSheet(table.styleSheet() + f"""
            QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}
        """)
        table.name_clicked.connect(self._on_raid_character_clicked)
        return table

    # ── Chart helpers ──

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

    # ── Characters data ──

    def _load_characters(self):
        self.char_list.clear()
        self._all_characters = []
        self._group_map = {}
        try:
            with PerformanceDB() as db:
                self._all_characters = db.get_all_characters()
                groups = db.get_all_raid_groups()
                for g in groups:
                    for member in g.members:
                        self._group_map.setdefault(member, []).append(g.name)

                group_names = [g.name for g in groups]

            self._group_filter_combo.blockSignals(True)
            current = self._group_filter_combo.currentText()
            self._group_filter_combo.clear()
            self._group_filter_combo.addItem("All")
            for gn in group_names:
                self._group_filter_combo.addItem(gn)
            idx = self._group_filter_combo.findText(current)
            if idx >= 0:
                self._group_filter_combo.setCurrentIndex(idx)
            self._group_filter_combo.blockSignals(False)

            for ch in self._all_characters:
                item = QListWidgetItem(f"{ch.name}  ({ch.player_class})")
                item.setData(Qt.ItemDataRole.UserRole, ch.name)
                item.setData(Qt.ItemDataRole.UserRole + 1,
                             self._group_map.get(ch.name, []))
                self.char_list.addItem(item)

            self._apply_group_filter()
            self.status_message.emit(f"Loaded {len(self._all_characters)} characters")
        except (sqlite3.Error, KeyError, ValueError, TypeError, OSError) as e:
            self.status_message.emit(f"No history data yet: {e}")

    def _filter_characters(self, text: str = ""):
        search = (text or self.search_input.text()).lower()
        group = self._group_filter_combo.currentText()
        for i in range(self.char_list.count()):
            item = self.char_list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            text_match = search in item.text().lower()
            group_match = (group == "All" or
                           group in self._group_map.get(name, []))
            item.setHidden(not (text_match and group_match))

    def _apply_group_filter(self):
        self._filter_characters()

    def _on_character_selected(self, current: QListWidgetItem, previous):
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        self._show_character(name)

    def _show_character(self, name: str):
        try:
            with PerformanceDB() as db:
                history = db.get_character_history(name)
                if not history:
                    return

                self._current_char_name = name

                self.summary_labels["Name"].setText(history.name)
                self.summary_labels["Class"].setText(history.player_class)

                char_groups = self._group_map.get(name, [])
                if char_groups:
                    tag_parts = []
                    for i, g in enumerate(char_groups):
                        color = TAG_COLORS[i % len(TAG_COLORS)]
                        tag_parts.append(
                            f'<span style="background-color:{color}; color:#fff; '
                            f'padding:2px 8px; border-radius:4px; font-size:11px; '
                            f'font-weight:bold;">{g}</span>')
                    self.summary_labels["Raid Groups"].setText("  ".join(tag_parts))
                    self.summary_labels["Raid Groups"].setTextFormat(Qt.TextFormat.RichText)
                else:
                    self.summary_labels["Raid Groups"].setText("-")
                    self.summary_labels["Raid Groups"].setTextFormat(Qt.TextFormat.PlainText)

                self.summary_labels["Raids Tracked"].setText(str(history.total_raids))

                if history.first_seen and history.last_seen:
                    period = f"{history.first_seen.strftime('%Y-%m-%d')} to {history.last_seen.strftime('%Y-%m-%d')}"
                    self.summary_labels["Active Period"].setText(period)
                else:
                    self.summary_labels["Active Period"].setText("-")

                self.summary_labels["Avg Healing"].setText(
                    f"{history.avg_healing:,.0f}" if history.avg_healing else "-"
                )
                self.summary_labels["Avg Damage"].setText(
                    f"{history.avg_damage:,.0f}" if history.avg_damage else "-"
                )
                self.summary_labels["Avg Mitigation"].setText(
                    f"{history.avg_mitigation_percent:.1f}%" if history.avg_mitigation_percent else "-"
                )
                self.summary_labels["Consumables Used"].setText(str(history.total_consumables_used))

                # Cache trend data for chart rebuilds
                self._cached_healer_trend = db.get_healer_trend(name)
                self._cached_healer_spell_trend = db.get_healer_spell_trend(name) if self._cached_healer_trend else []
                self._cached_tank_trend = db.get_tank_trend(name)
                self._cached_dps_trend = db.get_dps_trend(name)
                self._cached_dps_ability_trend = db.get_dps_ability_trend(name) if self._cached_dps_trend else []

                # Healing
                if self._cached_healer_trend:
                    self.healer_trend_model.set_data(
                        self._cached_healer_trend,
                        ["raid_date", "title", "total_healing", "total_overhealing", "overheal_percent"]
                    )
                else:
                    self.healer_trend_model.set_data([], [])
                self._rebuild_healer_chart()

                # Tank
                if self._cached_tank_trend:
                    self.tank_trend_model.set_data(
                        self._cached_tank_trend,
                        ["raid_date", "title", "total_damage_taken", "total_mitigated", "mitigation_percent"]
                    )
                else:
                    self.tank_trend_model.set_data([], [])
                self._rebuild_tank_chart()

                # DPS
                if self._cached_dps_trend:
                    self.dps_trend_model.set_data(
                        self._cached_dps_trend,
                        ["raid_date", "title", "role", "total_damage"]
                    )
                else:
                    self.dps_trend_model.set_data([], [])
                self._rebuild_dps_chart()

                # Consumables
                self._cached_consumable_trend = db.get_consumable_trend(name)
                consumes_summary = db.get_consumable_summary(name, limit=5)
                if consumes_summary:
                    all_consumable_names = set()
                    for row in consumes_summary:
                        for k in row:
                            if k not in ("raid_date", "title", "report_id"):
                                all_consumable_names.add(k)
                    cols = ["raid_date", "title"] + sorted(all_consumable_names)
                    self.consumes_trend_model.set_data(consumes_summary, cols)
                else:
                    self.consumes_trend_model.set_data([], [])
                self._rebuild_consumable_chart()

                # Consistency score
                consistency = db.get_character_consistency(name)
                if consistency:
                    scores = []
                    for key in ("healing_consistency", "damage_consistency", "mitigation_consistency"):
                        if key in consistency:
                            scores.append(consistency[key])
                    if scores:
                        avg = sum(scores) / len(scores)
                        self.summary_labels["Consistency"].setText(f"{avg:.1f}%")
                    else:
                        self.summary_labels["Consistency"].setText("-")
                else:
                    self.summary_labels["Consistency"].setText("-")

                # Consumable compliance
                compliance = db.get_character_consumable_compliance(name)
                if compliance and compliance.get("total_raids", 0) > 0:
                    pct = compliance["compliance_pct"]
                    avg = compliance["avg_per_raid"]
                    self.summary_labels["Consumable Compliance"].setText(
                        f"{pct:.0f}% ({avg:.1f}/raid)"
                    )
                else:
                    self.summary_labels["Consumable Compliance"].setText("-")

                # Personal Bests
                bests = db.get_character_personal_bests(name)
                if bests:
                    self._bests_model.set_data(bests, ["label", "raid_date", "title", "value"])
                else:
                    self._bests_model.set_data([], [])

                # Spider / Radar chart
                spider_data = db.get_character_spider_data(name)
                if self._spider_widget:
                    self._spider_tab_layout.removeWidget(self._spider_widget)
                    self._spider_widget.deleteLater()
                    self._spider_widget = None
                if spider_data:
                    self._spider_widget = SpiderChartWidget(spider_data)
                    self._spider_tab_layout.addWidget(self._spider_widget)

                # Calendar heatmap
                calendar_data = db.get_character_raid_calendar(name)
                if self._calendar_widget:
                    self._calendar_tab_layout.removeWidget(self._calendar_widget)
                    self._calendar_widget.deleteLater()
                    self._calendar_widget = None
                if calendar_data:
                    self._calendar_widget = CalendarHeatmapWidget(calendar_data)
                    self._calendar_tab_layout.addWidget(self._calendar_widget)

                # Auto-select best tab
                if self._cached_healer_trend:
                    self.char_trend_tabs.setCurrentIndex(0)
                elif self._cached_tank_trend:
                    self.char_trend_tabs.setCurrentIndex(1)
                elif self._cached_dps_trend:
                    self.char_trend_tabs.setCurrentIndex(2)

                self.status_message.emit(f"Showing history for {name}")
        except (sqlite3.Error, KeyError, ValueError, TypeError, OSError) as e:
            self.status_message.emit(f"Error loading history: {e}")

    # ── Chart rebuild handlers ──

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

    # ── Raids data ──

    def _load_raids(self):
        self._all_raids_raw = []
        try:
            with PerformanceDB() as db:
                self._all_raids_raw = db.get_raid_list()
            self._apply_raid_day_filter()
            self.status_message.emit(f"Loaded {len(self._all_raids_raw)} raids")
        except (sqlite3.Error, KeyError, ValueError, TypeError, OSError) as e:
            self.status_message.emit(f"No raid data yet: {e}")

    def _apply_raid_day_filter(self):
        self.raid_list.clear()
        if not hasattr(self, '_all_raids_raw'):
            return

        allowed_days = {idx for idx, cb in self._raid_day_checkboxes.items() if cb.isChecked()}

        for raid in self._all_raids_raw:
            date_str = raid.get("raid_date", "")
            try:
                dt = datetime.fromisoformat(date_str)
                if dt.weekday() not in allowed_days:
                    continue
                day_name = dt.strftime("%a")
                date_short = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                day_name = "?"
                date_short = date_str[:10]

            title = raid.get("title", "Unknown")
            item = QListWidgetItem(f"{date_short} {day_name}  {title}")
            item.setData(Qt.ItemDataRole.UserRole, raid["report_id"])
            self.raid_list.addItem(item)

    def _filter_raids(self, text: str):
        search = text.lower()
        for i in range(self.raid_list.count()):
            item = self.raid_list.item(i)
            item.setHidden(search not in item.text().lower())

    def _on_raid_selected(self, current: QListWidgetItem, previous):
        if not current:
            return
        report_id = current.data(Qt.ItemDataRole.UserRole)
        self._show_raid(report_id)

    def _show_raid(self, report_id: str):
        try:
            with PerformanceDB() as db:
                analysis = db.get_raid_analysis(report_id)
            if not analysis:
                self.status_message.emit(f"No data found for raid {report_id}")
                return

            self._current_raid_analysis = analysis
            self.raid_detail_panel.clear()
            self._raid_right_splitter.setSizes([1, 0])

            m = analysis.metadata
            comp = analysis.composition
            self.raid_info_label.setText(
                f"{m.title}  |  {m.date_formatted}  |  "
                f"Owner: {m.owner}  |  "
                f"{len(comp.tanks)}T / {len(comp.healers)}H / "
                f"{len(comp.melee)}M / {len(comp.ranged)}R"
            )
            self.raid_info_label.setVisible(True)
            self.raid_export_btn.setVisible(True)

            self.raid_healer_model.set_data(analysis.healers)
            self.raid_tank_model.set_data(analysis.tanks)
            self.raid_melee_model.set_data([d for d in analysis.dps if d.role == "melee"])
            self.raid_ranged_model.set_data([d for d in analysis.dps if d.role == "ranged"])

            self._populate_raid_consumables_tab(analysis)
            self._render_raid_composition(analysis)

            if analysis.healers:
                self.raid_detail_tabs.setCurrentIndex(0)
            elif analysis.tanks:
                self.raid_detail_tabs.setCurrentIndex(1)

            self.status_message.emit(f"Showing raid: {m.title}")
        except (sqlite3.Error, KeyError, ValueError, TypeError, OSError) as e:
            self.status_message.emit(f"Error loading raid: {e}")

    def _on_raid_character_clicked(self, name: str):
        if not self._current_raid_analysis:
            return

        analysis = self._current_raid_analysis
        player_consumes = [c for c in analysis.consumables if c.player_name == name]
        tab_idx = self.raid_detail_tabs.currentIndex()

        found = False

        if tab_idx == 1:  # Tanks
            for t in analysis.tanks:
                if t.name == name:
                    self.raid_detail_panel.show_tank(t, player_consumes)
                    found = True
                    break
        elif tab_idx in (2, 3):  # Melee / Ranged DPS
            for d in analysis.dps:
                if d.name == name:
                    self.raid_detail_panel.show_dps(d, player_consumes)
                    found = True
                    break

        if not found:
            for h in analysis.healers:
                if h.name == name:
                    self.raid_detail_panel.show_healer(h, player_consumes)
                    found = True
                    break
        if not found:
            for t in analysis.tanks:
                if t.name == name:
                    self.raid_detail_panel.show_tank(t, player_consumes)
                    found = True
                    break
        if not found:
            for d in analysis.dps:
                if d.name == name:
                    self.raid_detail_panel.show_dps(d, player_consumes)
                    found = True
                    break

        if found:
            total = self._raid_right_splitter.width()
            self._raid_right_splitter.setSizes([total - 400, 400])

    def _populate_raid_consumables_tab(self, analysis):
        self._raid_consumables_raw = analysis.consumables
        consumable_names = sorted({c.consumable_name for c in analysis.consumables})

        self._raid_consumes_filter_combo.blockSignals(True)
        self._raid_consumes_filter_combo.clear()
        self._raid_consumes_filter_combo.addItem("All")
        for name in consumable_names:
            self._raid_consumes_filter_combo.addItem(name)
        self._raid_consumes_filter_combo.blockSignals(False)

        self._apply_raid_consumes_filter()

    def _apply_raid_consumes_filter(self):
        if not hasattr(self, '_raid_consumables_raw'):
            return

        consumes = self._raid_consumables_raw
        selected = self._raid_consumes_filter_combo.currentText()

        if selected and selected != "All":
            consumes = [c for c in consumes if c.consumable_name == selected]

        player_map: dict[str, dict] = {}
        for c in consumes:
            if c.player_name not in player_map:
                player_map[c.player_name] = {"Name": c.player_name, "Role": c.player_role}
            player_map[c.player_name][c.consumable_name] = c.count
            if c.timestamps:
                player_map[c.player_name]["Timestamps"] = c.timestamps_formatted

        rows = list(player_map.values())
        rows.sort(key=lambda r: r["Name"])

        if selected and selected != "All":
            has_ts = any(r.get("Timestamps") for r in rows)
            cols = ["Name", "Role", selected] + (["Timestamps"] if has_ts else [])
            rows.sort(key=lambda r: r.get(selected, 0), reverse=True)
        else:
            consumable_names = sorted({c.consumable_name for c in consumes})
            cols = ["Name", "Role"] + consumable_names

        self._raid_consumes_model.set_data(rows, cols)

    def _delete_selected_raid(self):
        current = self.raid_list.currentItem()
        if not current:
            QMessageBox.information(self, "No Selection", "Please select a raid to delete.")
            return

        report_id = current.data(Qt.ItemDataRole.UserRole)
        title = current.text()

        reply = QMessageBox.question(
            self, "Delete Raid",
            f"Are you sure you want to delete this raid?\n\n{title}\n\n"
            "This will remove all performance data associated with this raid.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            with PerformanceDB() as db:
                db.delete_raid(report_id)
            self.status_message.emit(f"Deleted raid: {title}")
            self._load_raids()
            self.raid_info_label.setVisible(False)
        except (sqlite3.Error, KeyError, ValueError, TypeError, OSError) as e:
            QMessageBox.critical(self, "Delete Error", f"Failed to delete raid:\n{e}")

    def _export_raid_markdown(self):
        if not self._current_raid_analysis:
            return

        title = self._current_raid_analysis.metadata.title
        safe_title = "".join(
            c if c.isalnum() or c in " _-" else "_" for c in title
        ).strip().replace(" ", "_")

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Markdown Report",
            f"{safe_title}.md",
            "Markdown Files (*.md);;All Files (*)",
        )
        if not path:
            return

        try:
            from ..renderers.markdown import export_raid_analysis
            export_raid_analysis(self._current_raid_analysis, output_path=path)
            self.status_message.emit(f"Exported to {path}")
        except (sqlite3.Error, KeyError, ValueError, TypeError, OSError) as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n\n{e}")

    def _render_raid_composition(self, analysis):
        comp = analysis.composition
        lines = []
        lines.append("RAID COMPOSITION")
        lines.append("=" * 50)

        for label, group in [("Tanks", comp.tanks), ("Healers", comp.healers),
                             ("Melee DPS", comp.melee), ("Ranged DPS", comp.ranged)]:
            lines.append(f"\n{label} ({len(group)}):")
            if not group:
                lines.append("  (none)")
                continue
            by_class: dict[str, list[str]] = {}
            for p in group:
                by_class.setdefault(p.player_class, []).append(p.name)
            for cls in sorted(by_class):
                names = ", ".join(sorted(by_class[cls]))
                lines.append(f"  {cls}: {names}")

        lines.append(f"\nTotal: {len(comp.all_players)} players")
        self.raid_comp_text.setPlainText("\n".join(lines))

    # ── Public API ──

    def navigate_to_character(self, name: str):
        """Public entry point: switch to Characters tab and select a character."""
        self.top_tabs.setCurrentIndex(0)
        self._load_characters()

        for i in range(self.char_list.count()):
            item = self.char_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                self.char_list.setCurrentItem(item)
                return

        self._show_character(name)

    def showEvent(self, event):
        super().showEvent(event)
        self._load_characters()
        self._load_raids()


class _ClickableNameTableView(QTableView):
    """QTableView subclass that makes the Name column (col 0) clickable."""

    name_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, index: QModelIndex):
        if index.column() == 0:
            name = index.data(Qt.ItemDataRole.DisplayRole)
            if name:
                self.name_clicked.emit(name)

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid() and index.column() == 0:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(event)
