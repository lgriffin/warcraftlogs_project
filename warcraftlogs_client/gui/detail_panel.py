"""
Character detail side panel — full-height breakdown when a character is selected.
"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import (
    CancelledCastSummary,
    ConsumableUsage,
    DPSPerformance,
    EncounterSummary,
    HealerPerformance,
    TankPerformance,
)
from .charts import CancelledCastTimelineWidget
from .styles import COLORS


class _SpellTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple] = []
        self._columns: list[str] = []

    def set_data(self, rows: list[tuple], columns: list[str]):
        self.beginResetModel()
        self._rows = rows
        self._columns = columns
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        val = self._rows[index.row()][index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(val, int) and val > 999:
                return f"{val:,}"
            return str(val) if val is not None else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if isinstance(val, (int, float)):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return None


class CharacterDetailPanel(QWidget):
    view_history = Signal(str)
    closed = Signal()

    SECTIONS = [
        ("spell_breakdown", "Spells"),
        ("dispels", "Dispels"),
        ("damage_taken", "Dmg Taken"),
        ("abilities_used", "Abilities"),
        ("cancelled_casts", "Cancelled"),
        ("consumables", "Consumables"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._section_toggles: dict[str, QCheckBox] = {}
        self._section_tabs: dict[str, int] = {}
        self._build_ui()
        self.setVisible(False)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ──
        header_bar = QWidget()
        header_bar.setFixedHeight(48)
        header_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS["bg_card"]};
                border-bottom: 1px solid {COLORS["border"]};
                border-left: 1px solid {COLORS["border"]};
            }}
        """)
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(12, 4, 8, 4)

        self._name_label = QLabel("")
        self._name_label.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self._name_label.setStyleSheet(f"color: {COLORS['text_header']}; border: none;")
        header_layout.addWidget(self._name_label)

        header_layout.addStretch()

        btn_style = f"""
            QPushButton {{
                background-color: {COLORS["bg_input"]};
                color: {COLORS["text"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 4px;
                font-size: 11px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                background-color: {COLORS["border"]};
            }}
        """

        history_btn = QPushButton("History")
        history_btn.setFixedHeight(28)
        history_btn.setStyleSheet(btn_style)
        history_btn.clicked.connect(self._on_view_history)
        header_layout.addWidget(history_btn)

        close_btn = QPushButton("X")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS["text_dim"]};
                border: none;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                color: {COLORS["accent"]};
            }}
        """)
        close_btn.clicked.connect(self._on_close)
        header_layout.addWidget(close_btn)

        outer.addWidget(header_bar)

        # ── Summary line ──
        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS["text_dim"]};
                background-color: {COLORS["bg_card"]};
                border-left: 1px solid {COLORS["border"]};
                padding: 6px 12px;
                font-size: 11px;
            }}
        """)
        outer.addWidget(self._summary_label)

        # ── Section toggle bar ──
        toggle_bar = QWidget()
        toggle_bar.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS["bg_card"]};
                border-left: 1px solid {COLORS["border"]};
                border-bottom: 1px solid {COLORS["border"]};
            }}
        """)
        toggle_layout = QHBoxLayout(toggle_bar)
        toggle_layout.setContentsMargins(12, 4, 12, 4)
        toggle_layout.setSpacing(12)

        show_label = QLabel("Show:")
        show_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px; border: none;")
        toggle_layout.addWidget(show_label)

        for key, label in self.SECTIONS:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {COLORS['text']}; font-size: 11px; border: none;")
            cb.toggled.connect(lambda checked, k=key: self._toggle_section(k, checked))
            self._section_toggles[key] = cb
            toggle_layout.addWidget(cb)

        toggle_layout.addStretch()
        outer.addWidget(toggle_bar)

        # ── Tabbed content (each section = one tab, full height) ──
        self._detail_tabs = QTabWidget()
        self._detail_tabs.setStyleSheet(f"""
            QTabWidget {{
                border-left: 1px solid {COLORS["border"]};
            }}
        """)

        self._section_models: dict[str, _SpellTableModel] = {}
        self._section_table_views: dict[str, QTableView] = {}

        for key, label in self.SECTIONS:
            model = _SpellTableModel()
            table = QTableView()
            table.setModel(model)
            table.setAlternatingRowColors(True)
            table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
            table.setSortingEnabled(True)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            table.setStyleSheet(f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")

            if key == "cancelled_casts":
                wrapper = QWidget()
                wrapper_layout = QVBoxLayout(wrapper)
                wrapper_layout.setContentsMargins(0, 0, 0, 0)
                wrapper_layout.setSpacing(4)

                self._cc_boss_combo = QComboBox()
                self._cc_boss_combo.setFixedHeight(28)
                self._cc_boss_combo.setStyleSheet(f"""
                    QComboBox {{
                        background-color: {COLORS["bg_input"]};
                        color: {COLORS["text"]};
                        border: 1px solid {COLORS["border"]};
                        border-radius: 4px;
                        padding: 4px 8px;
                        font-size: 11px;
                    }}
                """)
                self._cc_boss_combo.currentIndexChanged.connect(self._on_cc_boss_changed)
                wrapper_layout.addWidget(self._cc_boss_combo)

                self._cc_timeline = CancelledCastTimelineWidget()
                cc_scroll = QScrollArea()
                cc_scroll.setWidgetResizable(True)
                cc_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                cc_scroll.setWidget(self._cc_timeline)
                cc_scroll.setFixedHeight(300)
                cc_scroll.setStyleSheet(f"""
                    QScrollArea {{
                        border: 1px solid {COLORS["border"]};
                        background-color: {COLORS["bg_card"]};
                    }}
                """)
                self._cc_timeline_scroll = cc_scroll
                cc_scroll.setVisible(False)
                wrapper_layout.addWidget(cc_scroll)

                wrapper_layout.addWidget(table, 1)

                tab_idx = self._detail_tabs.addTab(wrapper, label)
            else:
                tab_idx = self._detail_tabs.addTab(table, label)

            self._section_models[key] = model
            self._section_table_views[key] = table
            self._section_tabs[key] = tab_idx

        outer.addWidget(self._detail_tabs, 1)

        self._current_name = None
        self._cc_data: CancelledCastSummary | None = None
        self._cc_encounters: list[EncounterSummary] = []

    def _toggle_section(self, key: str, visible: bool):
        tab_idx = self._section_tabs.get(key)
        if tab_idx is None:
            return
        self._detail_tabs.setTabVisible(tab_idx, visible)

    def _on_view_history(self):
        if self._current_name:
            self.view_history.emit(self._current_name)

    def _on_close(self):
        self.setVisible(False)
        self.closed.emit()

    def show_healer(
        self,
        h: HealerPerformance,
        consumables: list[ConsumableUsage] | None = None,
        cancelled: CancelledCastSummary | None = None,
        encounters: list[EncounterSummary] | None = None,
    ):
        self._current_name = h.name
        self._name_label.setText(h.name)
        at_str = f"  |  Active: {h.active_time_percent:.1f}%" if h.active_time_percent > 0 else ""
        self._summary_label.setText(
            f"{h.player_class}  |  Healer  |  "
            f"Healing: {h.total_healing:,}  |  Overhealing: {h.total_overhealing:,}  |  "
            f"OH%: {h.overheal_percent:.1f}%{at_str}"
        )

        rows = [(s.spell_name, s.casts, s.total_amount) for s in h.spells if s.total_amount > 0]
        self._populate_section("spell_breakdown", rows, ["Spell", "Casts", "Total Healing"])

        rows = [(d.spell_name, d.casts) for d in h.dispels if d.casts > 0]
        self._populate_section("dispels", rows, ["Spell", "Casts"])

        resource_rows = [(r.name, r.count) for r in h.resources if r.count > 0]

        self._clear_section("damage_taken")
        self._clear_section("abilities_used")
        self._show_cancelled_casts(cancelled, encounters)
        self._show_consumables(consumables, resource_rows)

        self._auto_select_tab()
        self.setVisible(True)

    def show_tank(
        self,
        t: TankPerformance,
        consumables: list[ConsumableUsage] | None = None,
        cancelled: CancelledCastSummary | None = None,
        encounters: list[EncounterSummary] | None = None,
    ):
        self._current_name = t.name
        self._name_label.setText(t.name)
        at_str = f"  |  Active: {t.active_time_percent:.1f}%" if t.active_time_percent > 0 else ""
        self._summary_label.setText(
            f"{t.player_class}  |  Tank  |  "
            f"Taken: {t.total_damage_taken:,}  |  Mitigated: {t.total_mitigated:,}  |  "
            f"Mit%: {t.mitigation_percent:.1f}%{at_str}"
        )

        rows = [(s.spell_name, s.casts) for s in t.damage_taken_breakdown]
        self._populate_section("damage_taken", rows, ["Ability", "Hits"])

        rows = [(s.spell_name, s.casts) for s in t.abilities_used]
        self._populate_section("abilities_used", rows, ["Ability", "Uses"])

        self._clear_section("spell_breakdown")
        self._clear_section("dispels")
        self._show_cancelled_casts(cancelled, encounters)
        self._show_consumables(consumables)

        self._auto_select_tab()
        self.setVisible(True)

    def show_dps(
        self,
        d: DPSPerformance,
        consumables: list[ConsumableUsage] | None = None,
        cancelled: CancelledCastSummary | None = None,
        encounters: list[EncounterSummary] | None = None,
    ):
        self._current_name = d.name
        self._name_label.setText(d.name)
        at_str = f"  |  Active: {d.active_time_percent:.1f}%" if d.active_time_percent > 0 else ""
        self._summary_label.setText(
            f"{d.player_class}  |  {d.role.title()} DPS  |  Total Damage: {d.total_damage:,}{at_str}"
        )

        rows = [(a.spell_name, a.casts, a.total_amount) for a in d.abilities if a.total_amount > 0]
        self._populate_section("spell_breakdown", rows, ["Ability", "Casts", "Total Damage"])

        self._clear_section("dispels")
        self._clear_section("damage_taken")
        self._clear_section("abilities_used")
        self._show_cancelled_casts(cancelled, encounters)
        self._show_consumables(consumables)

        self._auto_select_tab()
        self.setVisible(True)

    def _show_cancelled_casts(
        self,
        cancelled: CancelledCastSummary | None = None,
        encounters: list[EncounterSummary] | None = None,
    ):
        self._cc_data = cancelled
        self._cc_encounters = encounters or []

        self._cc_boss_combo.blockSignals(True)
        self._cc_boss_combo.clear()
        self._cc_boss_combo.addItem("All (Raid)")
        for enc in self._cc_encounters:
            self._cc_boss_combo.addItem(enc.name)
        self._cc_boss_combo.setCurrentIndex(0)
        self._cc_boss_combo.blockSignals(False)
        self._cc_boss_combo.setVisible(bool(self._cc_encounters))

        self._refresh_cc_table()

    def _on_cc_boss_changed(self, _index: int):
        self._refresh_cc_table()

    def _refresh_cc_table(self):
        cancelled = self._cc_data
        if not cancelled or not cancelled.spell_details:
            self._clear_section("cancelled_casts")
            self._cc_timeline_scroll.setVisible(False)
            return

        boss_idx = self._cc_boss_combo.currentIndex()

        if boss_idx <= 0:
            rows = [
                (d.spell_name, d.total_casts, d.cancelled_casts, f"{d.cancel_rate:.1f}%")
                for d in cancelled.spell_details
                if d.cancelled_casts > 0
            ]
            self._populate_section("cancelled_casts", rows, ["Spell", "Casts", "Cancelled", "Rate"])
            self._cc_timeline_scroll.setVisible(False)
        else:
            enc = self._cc_encounters[boss_idx - 1]
            rows = []
            fight_details = []
            for d in cancelled.spell_details:
                has_fight_ts = False
                for ts_idx, t in enumerate(d.timestamps):
                    if t < enc.start_time or t > enc.end_time:
                        continue
                    has_fight_ts = True
                    cancel_time = self._format_fight_time(t, enc.start_time)
                    next_info = d.next_casts[ts_idx] if ts_idx < len(d.next_casts) else None
                    if next_info:
                        next_str = (
                            f"{next_info.spell_name} @ {self._format_fight_time(next_info.timestamp, enc.start_time)}"
                        )
                    else:
                        next_str = "—"
                    cause, cause_time = self._get_likely_cause_for_timestamp(d, t, enc)
                    rows.append((d.spell_name, cancel_time, next_str, cause, cause_time))
                if has_fight_ts:
                    fight_details.append(d)
            self._populate_section(
                "cancelled_casts",
                rows,
                ["Spell", "Cancelled At", "Next Cast", "Likely Cause", "Cause Time"],
            )
            if fight_details or enc.boss_events:
                self._cc_timeline.set_data(fight_details, enc)
                self._cc_timeline_scroll.setVisible(True)
            else:
                self._cc_timeline_scroll.setVisible(False)

    @staticmethod
    def _format_fight_time(timestamp_ms, fight_start_ms):
        rel = timestamp_ms - fight_start_ms
        minutes = rel // 60000
        seconds = (rel // 1000) % 60
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _get_likely_cause_for_timestamp(detail, cancel_ts, enc):
        corr = next((c for c in detail.correlations if c.cancel_timestamp == cancel_ts), None)
        if not corr or not corr.nearby_events:
            return "", ""
        closest = min(corr.nearby_events, key=lambda e: abs(e.offset_ms))
        cause_time = CharacterDetailPanel._format_fight_time(closest.timestamp, enc.start_time)
        if closest.event_type == "boss_death":
            return "Boss Died", cause_time
        elif closest.event_type == "boss_cast":
            return f"{closest.ability_name} (cast)", cause_time
        else:
            return f"{closest.ability_name} (dmg)", cause_time

    def _show_consumables(
        self, consumables: list[ConsumableUsage] | None = None, resource_rows: list[tuple] | None = None
    ):
        rows = []
        has_ts = False
        seen_names: set[str] = set()
        if consumables:
            has_ts = any(c.timestamps for c in consumables if c.count > 0)
            if has_ts:
                rows = [(c.consumable_name, c.count, c.timestamps_formatted) for c in consumables if c.count > 0]
            else:
                rows = [(c.consumable_name, c.count) for c in consumables if c.count > 0]
            seen_names = {c.consumable_name for c in consumables if c.count > 0}
        if resource_rows:
            for name, count in resource_rows:
                if name in seen_names:
                    continue
                if has_ts:
                    rows.append((name, count, ""))
                else:
                    rows.append((name, count))
        if rows:
            if has_ts:
                self._populate_section("consumables", rows, ["Consumable", "Count", "Timestamps"])
            else:
                self._populate_section("consumables", rows, ["Consumable", "Count"])
        else:
            self._clear_section("consumables")

    def _populate_section(self, key: str, rows: list[tuple], columns: list[str]):
        model = self._section_models[key]
        tab_idx = self._section_tabs[key]
        if rows:
            model.set_data(rows, columns)
            self._detail_tabs.setTabVisible(tab_idx, self._section_toggles[key].isChecked())
        else:
            model.set_data([], [])
            self._detail_tabs.setTabVisible(tab_idx, False)

    def _clear_section(self, key: str):
        self._section_models[key].set_data([], [])
        self._detail_tabs.setTabVisible(self._section_tabs[key], False)

    def _auto_select_tab(self):
        for key, _ in self.SECTIONS:
            tab_idx = self._section_tabs[key]
            if self._detail_tabs.isTabVisible(tab_idx):
                self._detail_tabs.setCurrentIndex(tab_idx)
                return

    def clear(self):
        self._current_name = None
        self._name_label.setText("")
        self._summary_label.setText("")
        self.setVisible(False)
        for key, _ in self.SECTIONS:
            self._clear_section(key)
