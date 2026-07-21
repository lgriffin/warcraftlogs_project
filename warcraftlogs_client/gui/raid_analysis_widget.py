"""
Reusable raid analysis display widget.

Shows full raid breakdown with role tabs, consumables, composition,
and a slide-out detail panel when a player name is clicked.
"""

import sqlite3

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..models import EncounterSummary, RaidAnalysis
from .analysis_helpers import (
    NumericSortProxy,
    SingleBossTrashModel,
    SingleEngineeringModel,
    build_heatmap_data,
    classify_consumable_usage,
    compute_engineering_stats,
)
from .charts import DebuffTimelineWidget
from .detail_panel import CharacterDetailPanel
from .styles import COLORS, COMMON_STYLES
from .table_models import (
    CancelledCastTableModel,
    DPSTableModel,
    HealerTableModel,
    HistoryTableModel,
    InterruptTableModel,
    TankTableModel,
)


class _ClickableNameTableView(QTableView):
    name_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.clicked.connect(self._on_click)

    def mouseMoveEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid() and index.column() == 0:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseMoveEvent(event)

    def _on_click(self, index):
        if index.column() == 0:
            name = index.data(Qt.ItemDataRole.DisplayRole)
            if name:
                self.name_clicked.emit(name)


class RaidAnalysisWidget(QWidget):
    status_message = Signal(str)
    navigate_to_character = Signal(str)
    request_back = Signal()
    raid_deleted = Signal(str)
    raid_refreshed = Signal(str)
    cross_analyze = Signal(str)

    def __init__(self, analysis: RaidAnalysis, show_back: bool = True, show_delete: bool = True, parent=None):
        super().__init__(parent)
        self._analysis = analysis
        self._show_back = show_back
        self._show_delete = show_delete
        self._build_ui()
        self._populate(analysis)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setStyleSheet(COMMON_STYLES)

        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(f"background-color: {COLORS['bg_card']}; border-bottom: 1px solid {COLORS['border']};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        if self._show_back:
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

        wcl_btn = QPushButton("View on WCL")
        wcl_btn.setProperty("secondary", True)
        wcl_btn.setFixedHeight(32)
        wcl_btn.clicked.connect(self._open_wcl_url)
        header_layout.addWidget(wcl_btn)

        export_btn = QPushButton("Export")
        export_btn.setProperty("secondary", True)
        export_btn.setFixedHeight(32)
        export_btn.clicked.connect(self._export_markdown)
        header_layout.addWidget(export_btn)

        cross_btn = QPushButton("Cross-Analyze")
        cross_btn.setProperty("secondary", True)
        cross_btn.setFixedHeight(32)
        cross_btn.clicked.connect(lambda: self.cross_analyze.emit(self._analysis.metadata.report_id))
        header_layout.addWidget(cross_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(32)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2980b9;
                color: white; border: none; border-radius: 4px;
                padding: 8px 16px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3498db; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        refresh_btn.clicked.connect(self._refresh_raid)
        header_layout.addWidget(refresh_btn)
        self._refresh_btn = refresh_btn

        if self._show_delete:
            delete_btn = QPushButton("Delete")
            delete_btn.setFixedHeight(32)
            delete_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS["error"]};
                    color: white; border: none; border-radius: 4px;
                    padding: 8px 16px; font-size: 12px; font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #c0392b; }}
            """)
            delete_btn.clicked.connect(self._delete_raid)
            header_layout.addWidget(delete_btn)

        layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter = splitter

        tabs_container = QWidget()
        tabs_layout = QVBoxLayout(tabs_container)
        tabs_layout.setContentsMargins(16, 12, 8, 16)

        self._tabs = QTabWidget()

        self._healer_model = HealerTableModel()
        healer_table = self._make_table(self._healer_model)
        self._tabs.addTab(healer_table, "Healers")

        self._tank_model = TankTableModel()
        tank_table = self._make_table(self._tank_model)
        self._tabs.addTab(tank_table, "Tanks")

        self._melee_model = DPSTableModel()
        melee_table = self._make_table(self._melee_model)
        self._tabs.addTab(melee_table, "Melee DPS")

        self._ranged_model = DPSTableModel()
        ranged_table = self._make_table(self._ranged_model)
        self._tabs.addTab(ranged_table, "Ranged DPS")

        consumes_widget = QWidget()
        consumes_layout = QVBoxLayout(consumes_widget)
        consumes_layout.setContentsMargins(0, 8, 0, 0)

        self._consumes_filter = QComboBox()
        self._consumes_filter.addItems(["All Roles", "Healers", "Tanks", "Melee", "Ranged"])
        self._consumes_filter.currentIndexChanged.connect(self._filter_consumables)
        consumes_layout.addWidget(self._consumes_filter)

        self._consumes_model = HistoryTableModel()
        consumes_table = QTableView()
        consumes_table.setModel(self._consumes_model)
        consumes_table.setAlternatingRowColors(True)
        consumes_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        consumes_table.setSortingEnabled(True)
        consumes_table.verticalHeader().setVisible(False)
        consumes_table.horizontalHeader().setStretchLastSection(True)
        consumes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        consumes_layout.addWidget(consumes_table)
        self._tabs.addTab(consumes_widget, "Consumables")

        # ── Interrupts tab ──
        int_widget = QWidget()
        int_layout = QVBoxLayout(int_widget)
        int_layout.setContentsMargins(0, 8, 0, 0)
        self._int_model = InterruptTableModel()
        int_table = QTableView()
        int_table.setModel(self._int_model)
        int_table.setAlternatingRowColors(True)
        int_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        int_table.setSortingEnabled(True)
        int_table.verticalHeader().setVisible(False)
        int_table.horizontalHeader().setStretchLastSection(True)
        int_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        int_layout.addWidget(int_table)
        self._int_tab_index = self._tabs.addTab(int_widget, "Interrupts")

        # ── Cast Efficiency tab ──
        cc_widget = QWidget()
        cc_layout = QVBoxLayout(cc_widget)
        cc_layout.setContentsMargins(0, 8, 0, 0)
        self._cc_model = CancelledCastTableModel()
        cc_table = QTableView()
        cc_table.setModel(self._cc_model)
        cc_table.setAlternatingRowColors(True)
        cc_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        cc_table.setSortingEnabled(True)
        cc_table.verticalHeader().setVisible(False)
        cc_table.horizontalHeader().setStretchLastSection(True)
        cc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        cc_layout.addWidget(cc_table)
        self._cc_tab_index = self._tabs.addTab(cc_widget, "Cast Efficiency")

        # ── Debuff Uptime tab ──
        du_widget = QWidget()
        du_layout = QVBoxLayout(du_widget)
        du_layout.setContentsMargins(0, 8, 0, 0)

        du_header = QHBoxLayout()
        du_header.addWidget(QLabel("Boss Fight:"))
        self._du_combo = QComboBox()
        self._du_combo.currentIndexChanged.connect(self._on_debuff_fight_changed)
        du_header.addWidget(self._du_combo, 1)
        du_layout.addLayout(du_header)

        self._du_scroll = QScrollArea()
        self._du_scroll.setWidgetResizable(True)
        self._du_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLORS['bg_card']}; }}"
        )
        du_layout.addWidget(self._du_scroll)

        self._du_timeline = DebuffTimelineWidget()
        self._du_scroll.setWidget(self._du_timeline)
        self._du_tab_index = self._tabs.addTab(du_widget, "Debuff Uptime")

        # ── Totem Uptime tab ──
        tu_widget = QWidget()
        tu_layout = QVBoxLayout(tu_widget)
        tu_layout.setContentsMargins(0, 8, 0, 0)

        tu_header = QHBoxLayout()
        tu_header.addWidget(QLabel("Boss Fight:"))
        self._tu_combo = QComboBox()
        self._tu_combo.currentIndexChanged.connect(self._on_totem_fight_changed)
        tu_header.addWidget(self._tu_combo, 1)
        tu_layout.addLayout(tu_header)

        self._tu_scroll = QScrollArea()
        self._tu_scroll.setWidgetResizable(True)
        self._tu_scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {COLORS['bg_card']}; }}"
        )
        tu_layout.addWidget(self._tu_scroll)

        self._tu_timeline = DebuffTimelineWidget()
        self._tu_scroll.setWidget(self._tu_timeline)
        self._tu_tab_index = self._tabs.addTab(tu_widget, "Totem Uptime")

        # ── Boss vs Trash tab ──
        bt_widget = QWidget()
        bt_layout = QVBoxLayout(bt_widget)
        bt_layout.setContentsMargins(0, 8, 0, 0)
        self._bt_model = SingleBossTrashModel()
        self._bt_table = self._make_sortable_table(self._bt_model)
        bt_layout.addWidget(self._bt_table)
        self._bt_tab_index = self._tabs.addTab(bt_widget, "Boss vs Trash")

        # ── Engineering tab ──
        eng_widget = QWidget()
        eng_layout = QVBoxLayout(eng_widget)
        eng_layout.setContentsMargins(0, 8, 0, 0)
        self._eng_model = SingleEngineeringModel()
        self._eng_table = self._make_sortable_table(self._eng_model)
        eng_layout.addWidget(self._eng_table)
        self._eng_tab_index = self._tabs.addTab(eng_widget, "Engineering")

        # ── Consumable Timeline tab ──
        tl_widget = QWidget()
        tl_layout = QVBoxLayout(tl_widget)
        tl_layout.setContentsMargins(0, 8, 0, 0)
        self._tl_combo = QComboBox()
        self._tl_combo.currentIndexChanged.connect(self._on_timeline_consumable_changed)
        tl_layout.addWidget(self._tl_combo)

        self._tl_heatmap_scroll = QScrollArea()
        self._tl_heatmap_scroll.setWidgetResizable(True)
        self._tl_heatmap_scroll.setFixedHeight(200)
        self._tl_heatmap_scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {COLORS['bg_card']}; }}")
        tl_layout.addWidget(self._tl_heatmap_scroll)
        self._tl_tab_index = self._tabs.addTab(tl_widget, "Timeline")

        encounters_widget = QWidget()
        enc_layout = QVBoxLayout(encounters_widget)
        enc_layout.setContentsMargins(0, 8, 0, 0)

        enc_header = QHBoxLayout()
        enc_header.addWidget(QLabel("Encounter:"))
        self._enc_combo = QComboBox()
        self._enc_combo.currentIndexChanged.connect(self._on_encounter_changed)
        enc_header.addWidget(self._enc_combo, 1)
        self._enc_summary = QLabel()
        self._enc_summary.setStyleSheet(f"color: {COLORS['text']}; padding: 0 8px;")
        enc_header.addWidget(self._enc_summary)
        enc_layout.addLayout(enc_header)

        self._enc_table = QTableWidget()
        self._enc_table.setColumnCount(7)
        self._enc_table.setHorizontalHeaderLabels(
            ["Name", "Class", "Role", "Damage Done", "Healing Done", "Damage Taken", "Active Time%"]
        )
        self._enc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 7):
            self._enc_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._enc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._enc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._enc_table.setAlternatingRowColors(True)
        enc_layout.addWidget(self._enc_table)

        self._encounters_tab_index = self._tabs.addTab(encounters_widget, "Encounters")
        self._encounters: list[EncounterSummary] = []

        self._comp_text = QTextEdit()
        self._comp_text.setReadOnly(True)
        self._comp_text.setFont(QFont("Consolas", 11))
        self._comp_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS["bg_card"]};
                color: {COLORS["text"]};
                border: none;
                padding: 12px;
            }}
        """)
        self._tabs.addTab(self._comp_text, "Composition")

        tabs_layout.addWidget(self._tabs)
        splitter.addWidget(tabs_container)

        self._detail_panel = CharacterDetailPanel()
        self._detail_panel.view_history.connect(self.navigate_to_character.emit)
        self._detail_panel.closed.connect(lambda: self._splitter.setSizes([1, 0]))
        splitter.addWidget(self._detail_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1, 0])

        layout.addWidget(splitter, 1)

    def _make_table(self, model) -> _ClickableNameTableView:
        table = _ClickableNameTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.name_clicked.connect(self._on_name_clicked)
        return table

    @staticmethod
    def _make_sortable_table(model) -> QTableView:
        proxy = NumericSortProxy()
        proxy.setSourceModel(model)
        table = QTableView()
        table.setModel(proxy)
        table.setSortingEnabled(True)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def _populate(self, analysis: RaidAnalysis):
        m = analysis.metadata
        comp = analysis.composition
        self._title_label.setText(
            f"{m.title}  |  {m.date_formatted}  |  "
            f"{len(comp.tanks)}T / {len(comp.healers)}H / "
            f"{len(comp.melee)}M / {len(comp.ranged)}R"
        )

        self._healer_model.set_data(analysis.healers)
        self._tank_model.set_data(analysis.tanks)
        self._melee_model.set_data([d for d in analysis.dps if d.role == "melee"])
        self._ranged_model.set_data([d for d in analysis.dps if d.role == "ranged"])

        self._all_consumables = analysis.consumables
        self._filter_consumables()

        if analysis.interrupts:
            self._int_model.set_data(analysis.interrupts)
            self._tabs.setTabVisible(self._int_tab_index, True)
        else:
            self._tabs.setTabVisible(self._int_tab_index, False)

        if analysis.cancelled_casts:
            self._cc_model.set_data(analysis.cancelled_casts)
            self._tabs.setTabVisible(self._cc_tab_index, True)
        else:
            self._tabs.setTabVisible(self._cc_tab_index, False)

        self._all_aura_uptimes = analysis.aura_uptimes
        if analysis.aura_uptimes:
            self._tabs.setTabVisible(self._du_tab_index, True)
            fights = []
            seen = set()
            for au in analysis.aura_uptimes:
                key = (au.fight_name, au.fight_start)
                if key not in seen:
                    seen.add(key)
                    fights.append((au.fight_name, au.fight_start, au.fight_end))
            self._du_fights = fights
            self._du_combo.blockSignals(True)
            self._du_combo.clear()
            for name, _, _ in fights:
                self._du_combo.addItem(name)
            self._du_combo.blockSignals(False)
            if fights:
                self._du_combo.setCurrentIndex(0)
                self._on_debuff_fight_changed(0)
        else:
            self._tabs.setTabVisible(self._du_tab_index, False)

        self._all_totem_uptimes = analysis.totem_uptimes
        if analysis.totem_uptimes:
            self._tabs.setTabVisible(self._tu_tab_index, True)
            fights = []
            seen = set()
            for tu in analysis.totem_uptimes:
                key = (tu.fight_name, tu.fight_start)
                if key not in seen:
                    seen.add(key)
                    fights.append((tu.fight_name, tu.fight_start, tu.fight_end))
            self._tu_fights = fights
            self._tu_combo.blockSignals(True)
            self._tu_combo.clear()
            for name, _, _ in fights:
                self._tu_combo.addItem(name)
            self._tu_combo.blockSignals(False)
            if fights:
                self._tu_combo.setCurrentIndex(0)
                self._on_totem_fight_changed(0)
        else:
            self._tabs.setTabVisible(self._tu_tab_index, False)

        self._populate_boss_vs_trash(analysis)
        self._populate_engineering(analysis)
        self._populate_timeline(analysis)
        self._render_composition(analysis)
        self._populate_encounters(analysis)

        if analysis.healers:
            self._tabs.setCurrentIndex(0)
        elif analysis.tanks:
            self._tabs.setCurrentIndex(1)

    def _filter_consumables(self):
        role_filter = self._consumes_filter.currentText()
        role_map = {"Healers": "healer", "Tanks": "tank", "Melee": "melee", "Ranged": "ranged"}

        consumes = self._all_consumables
        if role_filter != "All Roles":
            target = role_map.get(role_filter, "")
            consumes = [c for c in consumes if c.player_role == target]

        pivot: dict[str, dict[str, int]] = {}
        all_names: set[str] = set()
        for c in consumes:
            row = pivot.setdefault(c.player_name, {})
            row[c.consumable_name] = row.get(c.consumable_name, 0) + c.count
            all_names.add(c.consumable_name)

        sorted_names = sorted(all_names)
        rows = []
        for player, usage in sorted(pivot.items()):
            row = {"Player": player}
            for name in sorted_names:
                row[name] = usage.get(name, 0)
            rows.append(row)

        cols = ["Player", *sorted_names]
        self._consumes_model.set_data(rows, cols)

    def _populate_boss_vs_trash(self, analysis: RaidAnalysis):
        if not analysis.encounters or not analysis.consumables:
            self._tabs.setTabVisible(self._bt_tab_index, False)
            return
        self._tabs.setTabVisible(self._bt_tab_index, True)
        bt = classify_consumable_usage(analysis)
        rows = []
        for name in sorted(bt.keys()):
            rows.append(
                {
                    "name": name,
                    "boss": bt[name]["boss"],
                    "trash": bt[name]["trash"],
                }
            )
        rows.sort(key=lambda r: r["boss"], reverse=True)
        self._bt_model.set_data(rows)

    def _populate_engineering(self, analysis: RaidAnalysis):
        eng = compute_engineering_stats(analysis)
        if not eng:
            self._tabs.setTabVisible(self._eng_tab_index, False)
            return
        self._tabs.setTabVisible(self._eng_tab_index, True)
        rows = []
        for name in sorted(eng.keys()):
            rows.append({"name": name, **eng[name]})
        self._eng_model.set_data(rows)

    def _populate_timeline(self, analysis: RaidAnalysis):
        if not analysis.consumables:
            self._tabs.setTabVisible(self._tl_tab_index, False)
            return
        self._tabs.setTabVisible(self._tl_tab_index, True)
        self._tl_analysis = analysis
        names = sorted({c.consumable_name for c in analysis.consumables})
        self._tl_combo.blockSignals(True)
        self._tl_combo.clear()
        for n in names:
            self._tl_combo.addItem(n)
        self._tl_combo.blockSignals(False)
        if names:
            self._tl_combo.setCurrentIndex(0)
            self._on_timeline_consumable_changed(0)

    def _on_timeline_consumable_changed(self, index: int):
        name = self._tl_combo.currentText()
        if not name or not hasattr(self, "_tl_analysis"):
            return

        from .charts import ConsumableTimelineHeatmap

        heatmap_data = build_heatmap_data(self._tl_analysis, name)
        heatmap = ConsumableTimelineHeatmap(heatmap_data)
        self._tl_heatmap_scroll.setWidget(heatmap)
        player_count = len(heatmap_data.get("players", []))
        self._tl_heatmap_scroll.setFixedHeight(min(max(28 + player_count * 21 + 10, 80), 500))

    def _render_composition(self, analysis: RaidAnalysis):
        comp = analysis.composition
        lines = ["RAID COMPOSITION", "=" * 50]

        for label, group in [
            ("Tanks", comp.tanks),
            ("Healers", comp.healers),
            ("Melee DPS", comp.melee),
            ("Ranged DPS", comp.ranged),
        ]:
            lines.append(f"\n{label} ({len(group)}):")
            for p in group:
                lines.append(f"  {p.name} ({p.player_class})")

        self._comp_text.setPlainText("\n".join(lines))

    def _populate_encounters(self, analysis: RaidAnalysis):
        self._encounters = analysis.encounters
        self._enc_combo.blockSignals(True)
        self._enc_combo.clear()
        if not self._encounters:
            self._tabs.setTabVisible(self._encounters_tab_index, False)
            self._enc_combo.blockSignals(False)
            return
        self._tabs.setTabVisible(self._encounters_tab_index, True)
        for enc in self._encounters:
            duration_s = enc.duration_ms // 1000
            label = f"{enc.name} ({duration_s // 60}:{duration_s % 60:02d})"
            self._enc_combo.addItem(label)
        self._enc_combo.blockSignals(False)
        self._enc_combo.setCurrentIndex(0)
        self._on_encounter_changed(0)

    def _on_encounter_changed(self, index: int):
        if index < 0 or index >= len(self._encounters):
            return
        enc = self._encounters[index]
        duration_s = enc.duration_ms // 1000
        total_dmg = sum(p.total_damage for p in enc.players)
        total_heal = sum(p.total_healing for p in enc.players)
        self._enc_summary.setText(
            f"Duration: {duration_s // 60}:{duration_s % 60:02d}  |  Damage: {total_dmg:,}  |  Healing: {total_heal:,}"
        )

        self._enc_table.setRowCount(len(enc.players))
        for i, p in enumerate(enc.players):
            self._enc_table.setItem(i, 0, QTableWidgetItem(p.name))
            self._enc_table.setItem(i, 1, QTableWidgetItem(p.player_class))
            self._enc_table.setItem(i, 2, QTableWidgetItem(p.role))
            for j, val in enumerate([p.total_damage, p.total_healing, p.total_damage_taken]):
                item = QTableWidgetItem(f"{val:,}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._enc_table.setItem(i, j + 3, item)
            at_item = QTableWidgetItem(f"{p.active_time_percent:.1f}%")
            at_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._enc_table.setItem(i, 6, at_item)

    def _on_debuff_fight_changed(self, index: int):
        if not hasattr(self, "_du_fights") or index < 0 or index >= len(self._du_fights):
            return
        fight_name, fight_start, fight_end = self._du_fights[index]
        fight_uptimes = [
            au for au in self._all_aura_uptimes
            if au.fight_start == fight_start and au.fight_name == fight_name
        ]
        fight_uptimes.sort(key=lambda au: au.uptime_percent)
        self._du_timeline.set_data(fight_uptimes, fight_start, fight_end)

    def _on_totem_fight_changed(self, index: int):
        if not hasattr(self, "_tu_fights") or index < 0 or index >= len(self._tu_fights):
            return
        fight_name, fight_start, fight_end = self._tu_fights[index]
        fight_uptimes = [
            tu for tu in self._all_totem_uptimes
            if tu.fight_start == fight_start and tu.fight_name == fight_name
        ]
        fight_uptimes.sort(key=lambda tu: tu.uptime_percent)
        self._tu_timeline.set_data(fight_uptimes, fight_start, fight_end)

    def _on_name_clicked(self, name: str):
        a = self._analysis
        player_consumes = [c for c in a.consumables if c.player_name == name]

        for h in a.healers:
            if h.name == name:
                self._detail_panel.show_healer(h, player_consumes)
                self._splitter.setSizes([3, 1])
                return
        for t in a.tanks:
            if t.name == name:
                self._detail_panel.show_tank(t, player_consumes)
                self._splitter.setSizes([3, 1])
                return
        for d in a.dps:
            if d.name == name:
                self._detail_panel.show_dps(d, player_consumes)
                self._splitter.setSizes([3, 1])
                return

    def _open_wcl_url(self):
        import webbrowser

        webbrowser.open(self._analysis.metadata.url)

    def _export_markdown(self):
        title = self._analysis.metadata.title
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title).strip().replace(" ", "_")

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Markdown Report",
            f"{safe_title}.md",
            "Markdown Files (*.md);;All Files (*)",
        )
        if not path:
            return

        try:
            from ..renderers.markdown import export_raid_analysis

            export_raid_analysis(self._analysis, output_path=path)
            self.status_message.emit(f"Exported to {path}")
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n\n{e}")

    def _delete_raid(self):
        report_id = self._analysis.metadata.report_id
        title = self._analysis.metadata.title
        reply = QMessageBox.question(
            self,
            "Delete Raid",
            f'Delete "{title}" from the database?\n\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from ..database import PerformanceDB

            with PerformanceDB() as db:
                db.delete_raid(report_id)
            self.status_message.emit(f"Deleted raid: {title}")
            self.raid_deleted.emit(report_id)
            self.request_back.emit()
        except (sqlite3.Error, OSError) as e:
            QMessageBox.critical(self, "Delete Error", f"Failed to delete raid:\n{e}")

    def _refresh_raid(self):
        report_id = self._analysis.metadata.report_id
        title = self._analysis.metadata.title
        reply = QMessageBox.question(
            self,
            "Refresh Raid",
            f'Re-download and re-analyze "{title}"?\n\n'
            "This will fetch fresh data from WarcraftLogs.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._refresh_btn.setEnabled(False)
        self.status_message.emit(f"Refreshing {title}...")

        try:
            from ..database import PerformanceDB

            with PerformanceDB() as db:
                db.clear_raid_cache(report_id)
        except (sqlite3.Error, OSError):
            pass

        from .worker import AnalysisWorker

        self._refresh_worker = AnalysisWorker(report_id, parent=self)
        self._refresh_worker.progress.connect(self.status_message.emit)
        self._refresh_worker.finished.connect(self._on_refresh_finished)
        self._refresh_worker.error.connect(self._on_refresh_error)
        self._refresh_worker.start()

    def _on_refresh_finished(self, analysis):
        try:
            from ..database import PerformanceDB

            with PerformanceDB() as db:
                db.import_raid(analysis)
        except (sqlite3.Error, OSError) as e:
            QMessageBox.critical(self, "Refresh Error", f"Failed to save refreshed data:\n{e}")
            self._refresh_btn.setEnabled(True)
            return

        self.status_message.emit(f"Refreshed: {analysis.metadata.title}")
        self._refresh_btn.setEnabled(True)
        self.raid_refreshed.emit(analysis.metadata.report_id)

    def _on_refresh_error(self, error_msg: str):
        self._refresh_btn.setEnabled(True)
        self.status_message.emit(f"Refresh failed: {error_msg}")
        QMessageBox.critical(self, "Refresh Error", f"Failed to refresh raid:\n\n{error_msg}")
