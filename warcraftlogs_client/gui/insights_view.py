"""GM/RL Insights: cross-cutting trends, comparisons, and data exploration."""

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QComboBox,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
    QFileDialog,
)

from .styles import COMMON_STYLES, COLORS
from .charts import (
    build_dps_progression_chart,
    build_heal_damage_ratio_chart,
    build_raid_duration_chart,
    build_overheal_trend_chart,
    ConsumableHeatmapWidget,
)


def _clear_layout_widgets(layout):
    """Remove and delete all widgets from a layout."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
    return lbl


class InsightsView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded = False
        self._db_cache: dict = {}
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(COMMON_STYLES + f"""
            InsightsView, InsightsView QWidget {{
                background-color: {COLORS['bg_dark']};
            }}
            InsightsView QTabWidget::pane {{
                background-color: {COLORS['bg_dark']};
                border: 1px solid {COLORS['border']};
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        header_row = QHBoxLayout()
        header = QLabel("GM / RL Insights")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
        header_row.addWidget(header)

        header_row.addStretch()

        header_row.addWidget(QLabel("Raid Day:"))
        self._day_combo = QComboBox()
        self._day_combo.addItems(["All Days", "Wednesday", "Thursday", "Sunday",
                                  "Monday", "Tuesday", "Friday", "Saturday"])
        self._day_combo.setCurrentText("Wednesday")
        self._day_combo.currentTextChanged.connect(self._on_filter_changed)
        header_row.addWidget(self._day_combo)

        header_row.addWidget(QLabel("Raid Size:"))
        self._size_combo = QComboBox()
        self._size_combo.addItems(["All Sizes", "25-man", "10-man"])
        self._size_combo.currentTextChanged.connect(self._on_filter_changed)
        header_row.addWidget(self._size_combo)

        header_row.addWidget(QLabel("Lookback:"))
        self._last_n_combo = QComboBox()
        self._last_n_combo.addItems(["All Raids", "Last 5", "Last 10", "Last 15", "Last 20"])
        self._last_n_combo.currentTextChanged.connect(self._on_filter_changed)
        header_row.addWidget(self._last_n_combo)

        outer.addLayout(header_row)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_performance_tab(), "Performance")
        self._tabs.addTab(self._build_healers_tab(), "Healers & Tanks")
        self._tabs.addTab(self._build_raid_overview_tab(), "Raid Overview")
        self._tabs.addTab(self._build_heatmap_tab(), "Consumable Heatmap")
        self._tabs.addTab(self._build_usage_tab(), "Consumable Usage")
        outer.addWidget(self._tabs, 1)

    # ── Tab builders ──

    def _build_performance_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        inner = QWidget()
        self._perf_layout = QVBoxLayout(inner)
        self._perf_layout.setContentsMargins(4, 8, 4, 4)
        self._perf_layout.setSpacing(16)

        self._perf_layout.addWidget(_section_label("DPS Performance Summary"))

        self._perf_table = QTableWidget()
        self._perf_table.setColumnCount(6)
        self._perf_table.setHorizontalHeaderLabels(
            ["Name", "Class", "Raids", "Avg Damage", "Avg DPM", "Consistency %"])
        self._perf_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            self._perf_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._perf_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._perf_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._perf_table.setAlternatingRowColors(True)
        self._perf_layout.addWidget(self._perf_table)

        self._dps_prog_container = QVBoxLayout()
        self._perf_layout.addLayout(self._dps_prog_container)

        self._perf_layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_healers_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        inner = QWidget()
        self._healer_layout = QVBoxLayout(inner)
        self._healer_layout.setContentsMargins(4, 8, 4, 4)
        self._healer_layout.setSpacing(16)

        self._overheal_trend_container = QVBoxLayout()
        self._healer_layout.addLayout(self._overheal_trend_container)

        self._healer_layout.addWidget(_section_label("Healer Summary"))

        self._healer_table = QTableWidget()
        self._healer_table.setColumnCount(6)
        self._healer_table.setHorizontalHeaderLabels(
            ["Name", "Class", "Raids", "Avg Healing", "Avg Overheal %", "Dispels"])
        self._healer_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            self._healer_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._healer_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._healer_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._healer_table.setAlternatingRowColors(True)
        self._healer_layout.addWidget(self._healer_table)

        self._healer_layout.addWidget(_section_label("Tank Summary"))

        self._tank_table = QTableWidget()
        self._tank_table.setColumnCount(5)
        self._tank_table.setHorizontalHeaderLabels(
            ["Name", "Class", "Raids", "Avg Mitigation %", "Avg Damage Taken"])
        self._tank_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            self._tank_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._tank_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tank_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tank_table.setAlternatingRowColors(True)
        self._healer_layout.addWidget(self._tank_table)

        self._healer_layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_raid_overview_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        inner = QWidget()
        self._overview_layout = QVBoxLayout(inner)
        self._overview_layout.setContentsMargins(4, 8, 4, 4)
        self._overview_layout.setSpacing(16)

        row1 = QHBoxLayout()
        self._ratio_container = QVBoxLayout()
        row1.addLayout(self._ratio_container)
        self._duration_container = QVBoxLayout()
        row1.addLayout(self._duration_container)
        self._overview_layout.addLayout(row1)

        self._overview_layout.addWidget(_section_label("Attendance"))

        self._attendance_table = QTableWidget()
        self._attendance_table.setColumnCount(5)
        self._attendance_table.setHorizontalHeaderLabels(
            ["Name", "Class", "Raids Attended", "First Seen", "Last Seen"])
        self._attendance_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            self._attendance_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self._attendance_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._attendance_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._attendance_table.setAlternatingRowColors(True)
        self._overview_layout.addWidget(self._attendance_table)

        self._overview_layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_heatmap_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.addWidget(_section_label("Consumable Compliance (avg per raid)"))
        header_row.addStretch()
        self._export_btn = QPushButton("Export as Image")
        self._export_btn.clicked.connect(self._export_heatmap)
        header_row.addWidget(self._export_btn)
        layout.addLayout(header_row)

        self._heatmap_container = QVBoxLayout()
        layout.addLayout(self._heatmap_container)

        layout.addStretch()
        scroll.setWidget(inner)
        return scroll

    def _build_usage_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(12)

        layout.addWidget(_section_label("Consumable Usage Summary"))

        self._usage_table = QTableWidget()
        self._usage_table.setColumnCount(4)
        self._usage_table.setHorizontalHeaderLabels(["Consumable", "Users", "Total Uses", "Avg / User"])
        self._usage_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 4):
            self._usage_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._usage_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._usage_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._usage_table.setAlternatingRowColors(True)
        layout.addWidget(self._usage_table, 1)

        return tab

    # ── Lifecycle ──

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self._load_data()
            self._loaded = True

    def _on_filter_changed(self):
        if self._loaded:
            self._load_data()

    def _get_size_filter(self) -> str | None:
        text = self._size_combo.currentText()
        if text == "All Sizes":
            return None
        return text

    def _get_day_filter(self) -> str | None:
        text = self._day_combo.currentText()
        if text == "All Days":
            return None
        return text

    def _get_last_n_filter(self) -> int | None:
        text = self._last_n_combo.currentText()
        if text == "All Raids":
            return None
        return int(text.split()[-1])

    # ── Data loading ──

    def _load_data(self):
        from ..database import PerformanceDB

        self.status_message.emit("Loading insights data...")
        size = self._get_size_filter()
        day = self._get_day_filter()
        last_n = self._get_last_n_filter()
        try:
            with PerformanceDB() as db:
                self._db_cache = {
                    "dps_prog": db.get_dps_progression(top_n=10, raid_day=day, raid_size=size, last_n=last_n),
                    "dps_cons": db.get_dps_consistency(min_raids=3, raid_day=day, raid_size=size, last_n=last_n),
                    "dps_dpm": db.get_dps_per_minute(min_raids=3, raid_day=day, raid_size=size, last_n=last_n),
                    "raid_overview": db.get_raid_overview_trends(raid_day=day, raid_size=size, last_n=last_n),
                    "attendance": db.get_attendance_stats(min_raids=3, raid_day=day, raid_size=size, last_n=last_n),
                    "usage_rates": db.get_consumable_usage_rates(raid_day=day, raid_size=size, last_n=last_n),
                    "healer_insights": db.get_healer_insights(min_raids=3, raid_day=day, raid_size=size, last_n=last_n),
                    "overheal_trend": db.get_healer_overheal_trend(raid_day=day, raid_size=size, last_n=last_n),
                    "tank_stats": db.get_tank_mitigation_stats(min_raids=3, raid_day=day, raid_size=size, last_n=last_n),
                }
        except Exception as e:
            self.status_message.emit(f"Error loading insights: {e}")
            return

        self._refresh_all()
        self._load_heatmap()
        self.status_message.emit("Insights loaded")

    def _load_heatmap(self):
        from ..database import PerformanceDB

        day = self._get_day_filter()
        size = self._get_size_filter()
        last_n = self._get_last_n_filter()
        try:
            with PerformanceDB() as db:
                compliance = db.get_consumable_compliance(min_raids=2, raid_day=day,
                                                          raid_size=size, last_n=last_n)
        except Exception as e:
            self.status_message.emit(f"Error loading heatmap: {e}")
            return
        _clear_layout_widgets(self._heatmap_container)
        if compliance and compliance.get("characters"):
            heatmap = ConsumableHeatmapWidget(compliance)
            self._heatmap_container.addWidget(heatmap)

    def _export_heatmap(self):
        widget = None
        for i in range(self._heatmap_container.count()):
            w = self._heatmap_container.itemAt(i).widget()
            if isinstance(w, ConsumableHeatmapWidget):
                widget = w
                break
        if not widget:
            self.status_message.emit("No heatmap to export")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Heatmap", "consumable_heatmap.png",
            "PNG Image (*.png);;JPEG Image (*.jpg)")
        if not path:
            return

        pixmap = widget.grab()
        if pixmap.save(path):
            self.status_message.emit(f"Heatmap exported to {path}")
        else:
            self.status_message.emit("Failed to export heatmap")

    # ── Chart refresh ──

    def _refresh_all(self):
        d = self._db_cache

        self._refresh_performance(d.get("dps_prog", []), d.get("dps_cons", []),
                                   d.get("dps_dpm", []))
        self._refresh_healers(d.get("overheal_trend", []), d.get("healer_insights", []),
                               d.get("tank_stats", []))
        self._refresh_overview(d.get("raid_overview", []), d.get("attendance", []))
        self._refresh_usage(d.get("usage_rates", []))

    def _refresh_performance(self, dps_prog, dps_cons, dps_dpm):
        _clear_layout_widgets(self._dps_prog_container)

        dpm_by_name = {row["name"]: row.get("avg_dpm", 0) for row in dps_dpm}
        rows = []
        for row in dps_cons:
            rows.append({
                "name": row["name"],
                "player_class": row.get("player_class", ""),
                "raids": row.get("raids", 0),
                "avg_damage": row.get("avg_damage", 0),
                "avg_dpm": dpm_by_name.get(row["name"], 0),
                "consistency": row.get("consistency", 0),
            })
        rows.sort(key=lambda x: x["avg_damage"], reverse=True)

        self._perf_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self._perf_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self._perf_table.setItem(i, 1, QTableWidgetItem(row["player_class"]))
            for j, (key, fmt) in enumerate([
                ("raids", lambda v: str(int(v))),
                ("avg_damage", lambda v: f"{v:,.0f}"),
                ("avg_dpm", lambda v: f"{v:,.0f}"),
                ("consistency", lambda v: f"{v:.1f}"),
            ]):
                item = QTableWidgetItem(fmt(row[key]))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._perf_table.setItem(i, j + 2, item)

        if dps_prog:
            chart = build_dps_progression_chart(dps_prog, top_n=8)
            chart.setMinimumHeight(300)
            self._dps_prog_container.addWidget(chart)

    def _refresh_healers(self, overheal_trend, healer_insights, tank_stats):
        _clear_layout_widgets(self._overheal_trend_container)

        if overheal_trend:
            chart = build_overheal_trend_chart(overheal_trend)
            self._overheal_trend_container.addWidget(chart)

        self._healer_table.setRowCount(len(healer_insights))
        for i, row in enumerate(healer_insights):
            self._healer_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self._healer_table.setItem(i, 1, QTableWidgetItem(row["player_class"]))
            for j, (key, fmt) in enumerate([
                ("raids", lambda v: str(int(v))),
                ("avg_healing", lambda v: f"{v:,.0f}"),
                ("avg_overheal", lambda v: f"{v:.1f}"),
                ("total_dispels", lambda v: f"{int(v):,}"),
            ]):
                item = QTableWidgetItem(fmt(row.get(key, 0) or 0))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._healer_table.setItem(i, j + 2, item)

        self._tank_table.setRowCount(len(tank_stats))
        for i, row in enumerate(tank_stats):
            self._tank_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self._tank_table.setItem(i, 1, QTableWidgetItem(row["player_class"]))
            for j, (key, fmt) in enumerate([
                ("raids", lambda v: str(int(v))),
                ("avg_mitigation", lambda v: f"{v:.1f}"),
                ("avg_damage_taken", lambda v: f"{v:,.0f}"),
            ]):
                item = QTableWidgetItem(fmt(row.get(key, 0) or 0))
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._tank_table.setItem(i, j + 2, item)

    def _refresh_overview(self, raid_overview, attendance):
        _clear_layout_widgets(self._ratio_container)
        _clear_layout_widgets(self._duration_container)

        if raid_overview:
            self._ratio_container.addWidget(build_heal_damage_ratio_chart(raid_overview))
            self._duration_container.addWidget(build_raid_duration_chart(raid_overview))

        self._attendance_table.setRowCount(len(attendance))
        for i, row in enumerate(attendance):
            self._attendance_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self._attendance_table.setItem(i, 1, QTableWidgetItem(row["player_class"]))
            item = QTableWidgetItem(str(row.get("raid_count", 0)))
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._attendance_table.setItem(i, 2, item)
            first = row.get("first_seen", "")
            last = row.get("last_seen", "")
            self._attendance_table.setItem(i, 3, QTableWidgetItem(first[:10] if first else ""))
            self._attendance_table.setItem(i, 4, QTableWidgetItem(last[:10] if last else ""))

    def _refresh_usage(self, usage_rates):
        if not usage_rates or not self._usage_table:
            return
        self._usage_table.setRowCount(len(usage_rates))
        for i, row in enumerate(usage_rates):
            self._usage_table.setItem(i, 0, QTableWidgetItem(row["consumable_name"]))
            for j, key in enumerate(["total_users", "total_uses", "avg_per_user"]):
                item = QTableWidgetItem(str(row[key]))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._usage_table.setItem(i, j + 1, item)
