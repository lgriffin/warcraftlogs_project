"""
Reusable raid analysis display widget.

Shows full raid breakdown with role tabs, consumables, composition,
and a slide-out detail panel when a player name is clicked.
"""

import json
import sqlite3

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableView, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QTextEdit, QComboBox, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QCursor

from .styles import COMMON_STYLES, COLORS
from .table_models import HealerTableModel, TankTableModel, DPSTableModel, HistoryTableModel
from .detail_panel import CharacterDetailPanel
from ..models import RaidAnalysis, EncounterSummary


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
    cross_analyze = Signal(str)

    def __init__(self, analysis: RaidAnalysis, show_back: bool = True,
                 show_delete: bool = True, parent=None):
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

        if self._show_delete:
            delete_btn = QPushButton("Delete")
            delete_btn.setFixedHeight(32)
            delete_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['error']};
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
        self._enc_table.setColumnCount(6)
        self._enc_table.setHorizontalHeaderLabels(
            ["Name", "Class", "Role", "Damage Done", "Healing Done", "Damage Taken"])
        self._enc_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            self._enc_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
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
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
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

        cols = ["Player"] + sorted_names
        self._consumes_model.set_data(rows, cols)

    def _render_composition(self, analysis: RaidAnalysis):
        comp = analysis.composition
        lines = ["RAID COMPOSITION", "=" * 50]

        for label, group in [("Tanks", comp.tanks), ("Healers", comp.healers),
                             ("Melee DPS", comp.melee), ("Ranged DPS", comp.ranged)]:
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
            f"Duration: {duration_s // 60}:{duration_s % 60:02d}  |  "
            f"Damage: {total_dmg:,}  |  Healing: {total_heal:,}")

        self._enc_table.setRowCount(len(enc.players))
        for i, p in enumerate(enc.players):
            self._enc_table.setItem(i, 0, QTableWidgetItem(p.name))
            self._enc_table.setItem(i, 1, QTableWidgetItem(p.player_class))
            self._enc_table.setItem(i, 2, QTableWidgetItem(p.role))
            for j, val in enumerate([p.total_damage, p.total_healing, p.total_damage_taken]):
                item = QTableWidgetItem(f"{val:,}")
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._enc_table.setItem(i, j + 3, item)

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
            export_raid_analysis(self._analysis, output_path=path)
            self.status_message.emit(f"Exported to {path}")
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n\n{e}")

    def _delete_raid(self):
        report_id = self._analysis.metadata.report_id
        title = self._analysis.metadata.title
        reply = QMessageBox.question(
            self, "Delete Raid",
            f"Delete \"{title}\" from the database?\n\nThis cannot be undone.",
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
