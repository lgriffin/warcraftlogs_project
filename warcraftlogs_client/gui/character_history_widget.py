"""
Character history drill-down widget.

Shows a character's historical performance: summary stats, healing/tank/DPS
trend charts, consumable usage, personal bests, spider chart, and calendar.
Used as a pushed view in the NavigationStack when a player name is clicked.
"""

import sqlite3

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTableView, QHeaderView, QTabWidget, QComboBox,
    QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS
from .charts import (
    build_healer_chart, build_healer_overheal_chart,
    build_tank_chart, build_tank_mitigation_chart,
    build_dps_chart, build_spell_trend_chart,
    build_consumable_trend_chart,
    SpiderChartWidget, CalendarHeatmapWidget,
)
from .table_models import HistoryTableModel
from ..database import PerformanceDB


class CharacterHistoryWidget(QWidget):
    status_message = Signal(str)
    request_back = Signal()

    def __init__(self, character_name: str, parent=None):
        super().__init__(parent)
        self._name = character_name
        self._chart_widgets: dict[str, QWidget] = {}
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
        self._spider_widget = None
        self._calendar_widget = None
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setStyleSheet(COMMON_STYLES)

        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; "
            f"border-bottom: 1px solid {COLORS['border']};"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        back_btn = QPushButton("< Back")
        back_btn.setProperty("secondary", True)
        back_btn.setFixedHeight(32)
        back_btn.clicked.connect(self.request_back.emit)
        header_layout.addWidget(back_btn)

        self._title_label = QLabel()
        self._title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {COLORS['text_header']};")
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()
        layout.addWidget(header)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 16, 24, 16)
        content_layout.setSpacing(12)

        self.summary_card = QGroupBox("Character Summary")
        summary_layout = QVBoxLayout(self.summary_card)
        self.summary_labels: dict[str, QLabel] = {}
        for key in [
            "Name", "Class", "Raids Tracked", "Active Period",
            "Avg Healing", "Avg Damage", "Avg Mitigation",
            "Consumables Used", "Consistency", "Consumable Compliance",
        ]:
            row = QHBoxLayout()
            label = QLabel(f"{key}:")
            label.setFixedWidth(150)
            label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
            value = QLabel("-")
            value.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
            self.summary_labels[key] = value
            row.addWidget(label)
            row.addWidget(value)
            row.addStretch()
            summary_layout.addLayout(row)
        content_layout.addWidget(self.summary_card)

        combo_style = f"""
            QComboBox {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px; padding: 4px 8px;
                font-size: 11px; min-width: 160px;
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
        content_layout.addLayout(raid_size_row)

        self._tabs = QTabWidget()

        # Healing tab
        healer_tab = QWidget()
        hl = QVBoxLayout(healer_tab)
        hl.setContentsMargins(0, 4, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Chart:"))
        self._healer_chart_combo = QComboBox()
        self._healer_chart_combo.addItems([
            "Healing & Overhealing", "Overheal %", "Spell Healing", "Spell Casts",
        ])
        self._healer_chart_combo.setStyleSheet(combo_style)
        self._healer_chart_combo.currentIndexChanged.connect(self._rebuild_healer_chart)
        bar.addWidget(self._healer_chart_combo)
        bar.addStretch()
        hl.addLayout(bar)
        self._healer_chart_container = QVBoxLayout()
        hl.addLayout(self._healer_chart_container)
        self._healer_trend_model = HistoryTableModel()
        hl.addWidget(self._make_table(self._healer_trend_model), 1)
        self._tabs.addTab(healer_tab, "Healing Trend")

        # Tank tab
        tank_tab = QWidget()
        tl = QVBoxLayout(tank_tab)
        tl.setContentsMargins(0, 4, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Chart:"))
        self._tank_chart_combo = QComboBox()
        self._tank_chart_combo.addItems(["Damage & Mitigation", "Mitigation %"])
        self._tank_chart_combo.setStyleSheet(combo_style)
        self._tank_chart_combo.currentIndexChanged.connect(self._rebuild_tank_chart)
        bar.addWidget(self._tank_chart_combo)
        bar.addStretch()
        tl.addLayout(bar)
        self._tank_chart_container = QVBoxLayout()
        tl.addLayout(self._tank_chart_container)
        self._tank_trend_model = HistoryTableModel()
        tl.addWidget(self._make_table(self._tank_trend_model), 1)
        self._tabs.addTab(tank_tab, "Tank Trend")

        # DPS tab
        dps_tab = QWidget()
        dl = QVBoxLayout(dps_tab)
        dl.setContentsMargins(0, 4, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Chart:"))
        self._dps_chart_combo = QComboBox()
        self._dps_chart_combo.addItems(["Total Damage", "Ability Damage", "Ability Casts"])
        self._dps_chart_combo.setStyleSheet(combo_style)
        self._dps_chart_combo.currentIndexChanged.connect(self._rebuild_dps_chart)
        bar.addWidget(self._dps_chart_combo)
        bar.addStretch()
        dl.addLayout(bar)
        self._dps_chart_container = QVBoxLayout()
        dl.addLayout(self._dps_chart_container)
        self._dps_trend_model = HistoryTableModel()
        dl.addWidget(self._make_table(self._dps_trend_model), 1)
        self._tabs.addTab(dps_tab, "DPS Trend")

        # Consumables tab
        consumes_tab = QWidget()
        cl = QVBoxLayout(consumes_tab)
        cl.setContentsMargins(0, 4, 0, 0)
        self._consumes_chart_container = QVBoxLayout()
        cl.addLayout(self._consumes_chart_container)
        lbl = QLabel("Last 5 Raids")
        lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; margin-top: 4px;")
        cl.addWidget(lbl)
        self._consumes_trend_model = HistoryTableModel()
        cl.addWidget(self._make_table(self._consumes_trend_model), 1)
        self._tabs.addTab(consumes_tab, "Consumables")

        # Personal Bests
        bests_tab = QWidget()
        bl = QVBoxLayout(bests_tab)
        bl.setContentsMargins(0, 4, 0, 0)
        self._bests_model = HistoryTableModel()
        bl.addWidget(self._make_table(self._bests_model), 1)
        self._tabs.addTab(bests_tab, "Personal Bests")

        # Spider chart
        self._spider_tab = QWidget()
        self._spider_tab_layout = QVBoxLayout(self._spider_tab)
        self._spider_tab_layout.setContentsMargins(0, 4, 0, 0)
        self._tabs.addTab(self._spider_tab, "Radar")

        # Calendar heatmap
        self._calendar_tab = QWidget()
        self._calendar_tab_layout = QVBoxLayout(self._calendar_tab)
        self._calendar_tab_layout.setContentsMargins(0, 4, 0, 0)
        self._tabs.addTab(self._calendar_tab, "Calendar")

        content_layout.addWidget(self._tabs, 1)
        layout.addWidget(content, 1)

    def _make_table(self, model) -> QTableView:
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setStyleSheet(f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        return table

    def _load_data(self):
        try:
            with PerformanceDB() as db:
                history = db.get_character_history(self._name)
                if not history:
                    self._title_label.setText(f"{self._name} — No history found")
                    return

                self._title_label.setText(f"{history.name}  ({history.player_class})")
                self.summary_labels["Name"].setText(history.name)
                self.summary_labels["Class"].setText(history.player_class)
                self.summary_labels["Raids Tracked"].setText(str(history.total_raids))

                if history.first_seen and history.last_seen:
                    period = (
                        f"{history.first_seen.strftime('%Y-%m-%d')} to "
                        f"{history.last_seen.strftime('%Y-%m-%d')}"
                    )
                    self.summary_labels["Active Period"].setText(period)

                self.summary_labels["Avg Healing"].setText(
                    f"{history.avg_healing:,.0f}" if history.avg_healing else "-"
                )
                self.summary_labels["Avg Damage"].setText(
                    f"{history.avg_damage:,.0f}" if history.avg_damage else "-"
                )
                self.summary_labels["Avg Mitigation"].setText(
                    f"{history.avg_mitigation_percent:.1f}%"
                    if history.avg_mitigation_percent else "-"
                )
                self.summary_labels["Consumables Used"].setText(
                    str(history.total_consumables_used)
                )

                self._all_healer_trend = db.get_healer_trend(self._name)
                self._all_healer_spell_trend = (
                    db.get_healer_spell_trend(self._name)
                    if self._all_healer_trend else []
                )
                self._all_tank_trend = db.get_tank_trend(self._name)
                self._all_dps_trend = db.get_dps_trend(self._name)
                self._all_dps_ability_trend = (
                    db.get_dps_ability_trend(self._name)
                    if self._all_dps_trend else []
                )
                self._all_consumable_trend = db.get_consumable_trend(self._name)

                consumes_summary = db.get_consumable_summary(self._name, limit=5)
                if consumes_summary:
                    all_names = set()
                    for row in consumes_summary:
                        for k in row:
                            if k not in ("raid_date", "title", "report_id"):
                                all_names.add(k)
                    cols = ["raid_date", "title"] + sorted(all_names)
                    self._consumes_trend_model.set_data(consumes_summary, cols)
                else:
                    self._consumes_trend_model.set_data([], [])

                self._apply_raid_size_filter()

                consistency = db.get_character_consistency(self._name)
                if consistency:
                    scores = []
                    for key in ("healing_consistency", "damage_consistency", "mitigation_consistency"):
                        if key in consistency:
                            scores.append(consistency[key])
                    if scores:
                        avg = sum(scores) / len(scores)
                        self.summary_labels["Consistency"].setText(f"{avg:.1f}%")

                compliance = db.get_character_consumable_compliance(self._name)
                if compliance and compliance.get("total_raids", 0) > 0:
                    pct = compliance["compliance_pct"]
                    avg = compliance["avg_per_raid"]
                    self.summary_labels["Consumable Compliance"].setText(
                        f"{pct:.0f}% ({avg:.1f}/raid)"
                    )

                bests = db.get_character_personal_bests(self._name)
                if bests:
                    self._bests_model.set_data(bests, ["label", "raid_date", "title", "value"])

                spider_data = db.get_character_spider_data(self._name)
                if spider_data:
                    self._spider_widget = SpiderChartWidget(spider_data)
                    self._spider_tab_layout.addWidget(self._spider_widget)

                calendar_data = db.get_character_raid_calendar(self._name)
                if calendar_data:
                    self._calendar_widget = CalendarHeatmapWidget(calendar_data)
                    self._calendar_tab_layout.addWidget(self._calendar_widget)

                if self._cached_healer_trend:
                    self._tabs.setCurrentIndex(0)
                elif self._cached_tank_trend:
                    self._tabs.setCurrentIndex(1)
                elif self._cached_dps_trend:
                    self._tabs.setCurrentIndex(2)

                self.status_message.emit(f"Showing history for {self._name}")
        except (sqlite3.Error, KeyError, ValueError, TypeError, OSError) as e:
            self.status_message.emit(f"Error loading history: {e}")

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
            self._tabs.setCurrentIndex(0)
        elif self._cached_tank_trend:
            self._tabs.setCurrentIndex(1)
        elif self._cached_dps_trend:
            self._tabs.setCurrentIndex(2)
        elif self._cached_consumable_trend:
            self._tabs.setCurrentIndex(3)

    # ── Chart helpers ──

    def _clear_chart(self, container: QVBoxLayout, key: str):
        old = self._chart_widgets.get(key)
        if old:
            container.removeWidget(old)
            old.deleteLater()
            self._chart_widgets.pop(key, None)

    def _set_chart(self, container: QVBoxLayout, key: str, chart_view):
        self._clear_chart(container, key)
        self._chart_widgets[key] = chart_view
        container.insertWidget(0, chart_view)

    def _rebuild_healer_chart(self):
        trend = self._cached_healer_trend
        spell_trend = self._cached_healer_spell_trend
        if not trend:
            self._clear_chart(self._healer_chart_container, "healer")
            return
        choice = self._healer_chart_combo.currentIndex()
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
        trend = self._cached_tank_trend
        if not trend:
            self._clear_chart(self._tank_chart_container, "tank")
            return
        choice = self._tank_chart_combo.currentIndex()
        if choice == 0:
            view = build_tank_chart(trend)
        elif choice == 1:
            view = build_tank_mitigation_chart(trend)
        else:
            return
        self._set_chart(self._tank_chart_container, "tank", view)

    def _rebuild_dps_chart(self):
        trend = self._cached_dps_trend
        ability_trend = self._cached_dps_ability_trend
        if not trend:
            self._clear_chart(self._dps_chart_container, "dps")
            return
        choice = self._dps_chart_combo.currentIndex()
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
