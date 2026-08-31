"""
Encounter Deep Dive view — pushed onto NavigationStack for per-encounter analysis.

Three tabs: Class Cast Timeline, Wasted Resources, Cooldown Synergy.
Data is fetched on-demand via background workers.
"""

from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..client import WarcraftLogsClient
from ..models import (
    ConsumableUsage,
    CooldownSynergyAnalysis,
    EncounterSummary,
    PlayerCastTimeline,
    PlayerIdentity,
    PlayerResourceAnalysis,
    RaidComposition,
)
from .charts import ClassCastTimelineWidget, CooldownSynergyWidget
from .encounter_worker import EncounterCastWorker, EncounterCooldownWorker, EncounterResourceWorker
from .styles import COLORS, COMMON_STYLES


class EncounterDeepDiveView(QWidget):
    status_message = Signal(str)
    request_back = Signal()

    def __init__(
        self,
        client: WarcraftLogsClient,
        report_id: str,
        encounters: list[EncounterSummary],
        composition: RaidComposition,
        consumable_usage: list[ConsumableUsage],
        initial_index: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self._client = client
        self._report_id = report_id
        self._encounters = encounters
        self._composition = composition
        self._consumable_usage = consumable_usage
        self._workers: list = []

        self._cast_cache: dict[tuple, list[PlayerCastTimeline]] = {}
        self._resource_cache: dict[int, list[PlayerResourceAnalysis]] = {}
        self._cooldown_cache: dict[int, CooldownSynergyAnalysis] = {}

        self._source_ids_resolved = self._resolve_source_ids()
        self._build_ui()

        if self._encounters:
            if initial_index == 0:
                self._on_encounter_changed(0)
            else:
                self._enc_combo.setCurrentIndex(initial_index)

    def _resolve_source_ids(self) -> bool:
        """Fetch master data from the API to get source IDs for all players."""
        try:
            actors = self._client.get_master_data(self._report_id)
        except Exception as e:
            import logging

            logging.getLogger(__name__).error("Failed to resolve source IDs: %s", e)
            return False

        actor_map = {a["name"]: a["id"] for a in actors}

        def _patch_list(players: list[PlayerIdentity]):
            for i, p in enumerate(players):
                if p.source_id == 0 and p.name in actor_map:
                    players[i] = PlayerIdentity(
                        name=p.name,
                        player_class=p.player_class,
                        source_id=actor_map[p.name],
                        role=p.role,
                    )

        _patch_list(self._composition.tanks)
        _patch_list(self._composition.healers)
        _patch_list(self._composition.melee)
        _patch_list(self._composition.ranged)
        patched = sum(1 for p in self._composition.all_players if p.source_id != 0)
        total = len(self._composition.all_players)
        import logging

        logging.getLogger(__name__).info("Resolved %d/%d source IDs", patched, total)
        return patched > 0

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setStyleSheet(COMMON_STYLES)

        # ── Header bar ──
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(f"background-color: {COLORS['bg_card']}; border-bottom: 1px solid {COLORS['border']};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)

        back_btn = QPushButton("< Back")
        back_btn.setProperty("secondary", True)
        back_btn.setFixedHeight(32)
        back_btn.clicked.connect(self.request_back.emit)
        header_layout.addWidget(back_btn)

        title = QLabel("Encounter Deep Dive")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        header_layout.addWidget(title)

        header_layout.addStretch()

        header_layout.addWidget(QLabel("Boss:"))
        self._enc_combo = QComboBox()
        self._enc_combo.setMinimumWidth(200)
        for enc in self._encounters:
            dur_s = enc.duration_ms // 1000
            self._enc_combo.addItem(f"{enc.name} ({dur_s // 60}:{dur_s % 60:02d})")
        self._enc_combo.currentIndexChanged.connect(self._on_encounter_changed)
        header_layout.addWidget(self._enc_combo)

        layout.addWidget(header)

        # ── Progress bar ──
        self._progress = QProgressBar()
        self._progress.setFixedHeight(3)
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar {{ border: none; background: {COLORS['bg_dark']}; }}"
            f"QProgressBar::chunk {{ background: {COLORS['accent']}; }}"
        )
        layout.addWidget(self._progress)

        # ── Status label ──
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; padding: 4px 16px; background: {COLORS['bg_dark']};"
        )
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        # ── Tabs ──
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {COLORS['border']}; }}QTabBar::tab {{ padding: 8px 16px; }}"
        )
        layout.addWidget(self._tabs)

        self._build_cast_tab()
        self._build_resource_tab()
        self._build_cooldown_tab()

        self._tabs.currentChanged.connect(self._on_tab_changed)

    # ── Tab 1: Class Cast Timeline ──

    def _build_cast_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(16, 12, 16, 12)

        self._cast_loading_banner = self._make_loading_banner(
            "Fetching cast data from WarcraftLogs API... This may take a moment."
        )
        tab_layout.addWidget(self._cast_loading_banner)

        # Class filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Class:"))
        self._class_combo = QComboBox()
        self._class_combo.setMinimumWidth(150)
        self._class_combo.currentTextChanged.connect(self._on_class_changed)
        filter_row.addWidget(self._class_combo)
        filter_row.addStretch()
        tab_layout.addLayout(filter_row)

        # Timeline widget in scroll area
        self._cast_timeline = ClassCastTimelineWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._cast_timeline)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {COLORS['bg_dark']}; }}")
        tab_layout.addWidget(scroll, 1)

        self._tabs.addTab(tab, "Class Cast Timeline")

    # ── Tab 2: Wasted Resources ──

    def _build_resource_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(16, 12, 16, 12)

        self._resource_loading_banner = self._make_loading_banner(
            "Fetching resource data from WarcraftLogs API... This may take a moment."
        )
        tab_layout.addWidget(self._resource_loading_banner)

        # Player filter — "All Raid" plus individual players
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Player:"))
        self._resource_player_combo = QComboBox()
        self._resource_player_combo.setMinimumWidth(150)
        self._resource_player_combo.currentIndexChanged.connect(self._on_resource_player_changed)
        filter_row.addWidget(self._resource_player_combo)
        filter_row.addStretch()
        tab_layout.addLayout(filter_row)

        # Raid summary table (shown for "All Raid")
        self._raid_waste_summary = QTableWidget()
        self._raid_waste_summary.setColumnCount(4)
        self._raid_waste_summary.setHorizontalHeaderLabels(["Player", "Class", "Total Wasted", "Top Sources"])
        self._raid_waste_summary.horizontalHeader().setStretchLastSection(True)
        self._raid_waste_summary.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._raid_waste_summary.setAlternatingRowColors(True)
        self._raid_waste_summary.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._raid_waste_summary.cellDoubleClicked.connect(self._on_waste_summary_double_click)
        tab_layout.addWidget(self._raid_waste_summary, 1)

        # Per-player waste events table (shown for individual player)
        self._waste_table = QTableWidget()
        self._waste_table.setColumnCount(3)
        self._waste_table.setHorizontalHeaderLabels(["Time", "Type", "Description"])
        self._waste_table.horizontalHeader().setStretchLastSection(True)
        self._waste_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._waste_table.setAlternatingRowColors(True)
        self._waste_table.setVisible(False)
        tab_layout.addWidget(self._waste_table, 1)

        self._tabs.addTab(tab, "Wasted Resources")

    # ── Tab 3: Cooldown Synergy ──

    def _build_cooldown_tab(self):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(16, 12, 16, 12)

        self._cooldown_loading_banner = self._make_loading_banner(
            "Fetching cooldown data from WarcraftLogs API... This may take a moment."
        )
        tab_layout.addWidget(self._cooldown_loading_banner)

        # Synergy timeline in scroll area
        self._cooldown_widget = CooldownSynergyWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._cooldown_widget)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {COLORS['bg_dark']}; }}")
        tab_layout.addWidget(scroll, 2)

        # Summary table
        summary_label = QLabel("Cooldown Synergy Scores")
        summary_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        summary_label.setStyleSheet(f"color: {COLORS['text_header']}; margin-top: 8px;")
        tab_layout.addWidget(summary_label)

        self._synergy_table = QTableWidget()
        self._synergy_table.setColumnCount(5)
        self._synergy_table.setHorizontalHeaderLabels(["Player", "Class", "CDs Used", "During Heroism", "Synergy"])
        self._synergy_table.horizontalHeader().setStretchLastSection(True)
        self._synergy_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._synergy_table.setAlternatingRowColors(True)
        tab_layout.addWidget(self._synergy_table, 1)

        self._tabs.addTab(tab, "Cooldown Synergy")

    # ── Encounter / tab change handlers ──

    def _on_encounter_changed(self, index: int):
        if index < 0 or index >= len(self._encounters):
            return
        enc = self._encounters[index]
        self._populate_class_combo(enc)
        self._on_tab_changed(self._tabs.currentIndex())

    def _on_tab_changed(self, index: int):
        if not self._encounters:
            return

        if index == 0:
            self._load_cast_data()
        elif index == 1:
            self._load_resource_data()
        elif index == 2:
            self._load_cooldown_data()

    def _populate_class_combo(self, encounter: EncounterSummary):
        self._class_combo.blockSignals(True)
        self._class_combo.clear()
        classes = sorted({p.player_class for p in self._composition.all_players if p.player_class})
        self._class_combo.addItems(classes)
        self._class_combo.blockSignals(False)
        if classes:
            self._class_combo.setCurrentIndex(0)

    def _on_class_changed(self, class_name: str):
        if class_name:
            self._load_cast_data()

    def _on_resource_player_changed(self, index: int):
        if not hasattr(self, "_current_resource_data") or not self._current_resource_data:
            return
        if index < 0:
            return
        enc = self._encounters[self._enc_combo.currentIndex()]
        if index == 0:
            self._raid_waste_summary.setVisible(True)
            self._waste_table.setVisible(False)
        else:
            player_idx = index - 1
            if player_idx >= len(self._current_resource_data):
                return
            self._raid_waste_summary.setVisible(False)
            self._waste_table.setVisible(True)
            analysis = self._current_resource_data[player_idx]
            self._populate_player_waste_table(analysis, enc)

    def _on_waste_summary_double_click(self, row: int, _col: int):
        combo_index = row + 1
        if combo_index < self._resource_player_combo.count():
            self._resource_player_combo.setCurrentIndex(combo_index)

    def _populate_player_waste_table(self, analysis: PlayerResourceAnalysis, encounter: EncounterSummary):
        sorted_waste = sorted(analysis.waste_events, key=lambda w: w.timestamp)
        events = []
        for w in sorted_waste:
            rel_ms = w.timestamp - encounter.start_time
            total_s = max(0, rel_ms // 1000)
            time_str = f"{total_s // 60}:{total_s % 60:02d}"
            events.append((time_str, w.waste_type, w.description))

        self._waste_table.setRowCount(len(events))
        for i, (time_str, wtype, desc) in enumerate(events):
            self._waste_table.setItem(i, 0, QTableWidgetItem(time_str))
            self._waste_table.setItem(i, 1, QTableWidgetItem(wtype.replace("_", " ").title()))
            self._waste_table.setItem(i, 2, QTableWidgetItem(desc))

    # ── Loading banner ──

    def _make_loading_banner(self, text: str) -> QLabel:
        banner = QLabel(text)
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner.setFixedHeight(40)
        banner.setStyleSheet(
            f"background-color: {COLORS['warning']}; color: {COLORS['bg_dark']};"
            " font-weight: bold; font-size: 13px; border-radius: 4px;"
            " padding: 8px 16px;"
        )
        banner.setVisible(False)
        return banner

    # ── Data loading ──

    def _show_loading(self, message: str):
        self._progress.setVisible(True)
        self._status_label.setText(message)
        self._status_label.setVisible(True)

    def _hide_loading(self):
        self._progress.setVisible(False)
        self._status_label.setVisible(False)

    def _load_cast_data(self):
        enc_idx = self._enc_combo.currentIndex()
        if enc_idx < 0:
            return
        enc = self._encounters[enc_idx]
        player_class = self._class_combo.currentText()
        if not player_class:
            return

        cache_key = (enc.encounter_id, enc.start_time, player_class)
        if cache_key in self._cast_cache:
            self._display_cast_data(self._cast_cache[cache_key], enc)
            return

        self._cast_loading_banner.setVisible(True)
        self._show_loading(f"Loading cast data for {player_class} players...")
        worker = EncounterCastWorker(self._client, self._report_id, enc, self._composition, player_class, parent=self)
        worker.progress.connect(lambda msg: self._status_label.setText(msg))
        worker.finished.connect(lambda data, k=cache_key, e=enc: self._on_cast_data_ready(data, k, e))
        worker.error.connect(self._on_worker_error)
        self._workers.append(worker)
        worker.start()

    def _on_cast_data_ready(self, data: list, cache_key: tuple, encounter: EncounterSummary):
        self._cast_cache[cache_key] = data
        self._cast_loading_banner.setVisible(False)
        self._hide_loading()
        self._display_cast_data(data, encounter)

    def _display_cast_data(self, timelines: list[PlayerCastTimeline], encounter: EncounterSummary):
        self._cast_timeline.set_data(timelines, encounter.start_time, encounter.end_time)

    def _load_resource_data(self):
        enc_idx = self._enc_combo.currentIndex()
        if enc_idx < 0:
            return
        enc = self._encounters[enc_idx]

        cache_key = enc.encounter_id
        if cache_key in self._resource_cache:
            self._display_resource_data(self._resource_cache[cache_key], enc)
            return

        self._resource_loading_banner.setVisible(True)
        self._show_loading("Loading resource data...")
        worker = EncounterResourceWorker(
            self._client, self._report_id, enc, self._composition, self._consumable_usage, parent=self
        )
        worker.progress.connect(lambda msg: self._status_label.setText(msg))
        worker.finished.connect(lambda data, k=cache_key, e=enc: self._on_resource_data_ready(data, k, e))
        worker.error.connect(self._on_worker_error)
        self._workers.append(worker)
        worker.start()

    def _on_resource_data_ready(self, data: list, cache_key: int, encounter: EncounterSummary):
        self._resource_cache[cache_key] = data
        self._resource_loading_banner.setVisible(False)
        self._hide_loading()
        self._display_resource_data(data, encounter)

    def _display_resource_data(self, analyses: list[PlayerResourceAnalysis], encounter: EncounterSummary):
        self._current_resource_data = analyses

        # Populate combo: "All Raid" + individual players
        self._resource_player_combo.blockSignals(True)
        self._resource_player_combo.clear()
        self._resource_player_combo.addItem("All Raid")
        for a in analyses:
            waste_count = len(a.waste_events)
            suffix = f" — {waste_count} event{'s' if waste_count != 1 else ''}" if waste_count else ""
            self._resource_player_combo.addItem(f"{a.player_name} ({a.player_class}){suffix}")
        self._resource_player_combo.blockSignals(False)

        # Build raid summary table
        players_with_waste = [a for a in analyses if a.waste_events]
        players_with_waste.sort(key=lambda a: sum(self._parse_waste_amount(w) for w in a.waste_events), reverse=True)

        self._raid_waste_summary.setRowCount(len(players_with_waste))
        for i, a in enumerate(players_with_waste):
            total_wasted = sum(self._parse_waste_amount(w) for w in a.waste_events)
            source_counts: Counter[str] = Counter()
            for w in a.waste_events:
                source_counts[w.ability_name or "Unknown"] += self._parse_waste_amount(w)
            top_sources = ", ".join(f"{name} ({amt})" for name, amt in source_counts.most_common(3))

            resource_name = {0: "mana", 1: "rage", 3: "energy"}.get(a.waste_events[0].resource_type, "resource")

            self._raid_waste_summary.setItem(i, 0, QTableWidgetItem(a.player_name))
            self._raid_waste_summary.setItem(i, 1, QTableWidgetItem(a.player_class))

            total_item = QTableWidgetItem(f"{total_wasted:,} {resource_name}")
            total_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._raid_waste_summary.setItem(i, 2, total_item)

            self._raid_waste_summary.setItem(i, 3, QTableWidgetItem(top_sources))

        self._raid_waste_summary.setVisible(True)
        self._waste_table.setVisible(False)
        self._resource_player_combo.setCurrentIndex(0)

    @staticmethod
    def _parse_waste_amount(waste_event) -> int:
        desc = waste_event.description
        try:
            return int(desc.split()[0])
        except (ValueError, IndexError):
            return 0

    def _load_cooldown_data(self):
        enc_idx = self._enc_combo.currentIndex()
        if enc_idx < 0:
            return
        enc = self._encounters[enc_idx]

        cache_key = enc.encounter_id
        if cache_key in self._cooldown_cache:
            self._display_cooldown_data(self._cooldown_cache[cache_key], enc)
            return

        self._cooldown_loading_banner.setVisible(True)
        self._show_loading("Analyzing cooldown management...")
        worker = EncounterCooldownWorker(self._client, self._report_id, enc, self._composition, parent=self)
        worker.progress.connect(lambda msg: self._status_label.setText(msg))
        worker.finished.connect(lambda data, k=cache_key, e=enc: self._on_cooldown_data_ready(data, k, e))
        worker.error.connect(self._on_worker_error)
        self._workers.append(worker)
        worker.start()

    def _on_cooldown_data_ready(self, data: CooldownSynergyAnalysis, cache_key: int, encounter: EncounterSummary):
        self._cooldown_cache[cache_key] = data
        self._cooldown_loading_banner.setVisible(False)
        self._hide_loading()
        self._display_cooldown_data(data, encounter)

    def _display_cooldown_data(self, analysis: CooldownSynergyAnalysis, encounter: EncounterSummary):
        self._cooldown_widget.set_data(analysis, encounter.start_time, encounter.end_time)

        # Populate summary table
        synergies = sorted(analysis.player_synergies, key=lambda s: s.synergy_score, reverse=True)
        self._synergy_table.setRowCount(len(synergies))
        for i, ps in enumerate(synergies):
            self._synergy_table.setItem(i, 0, QTableWidgetItem(ps.player_name))
            self._synergy_table.setItem(i, 1, QTableWidgetItem(ps.player_class))

            cd_item = QTableWidgetItem(str(ps.total_cd_count))
            cd_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._synergy_table.setItem(i, 2, cd_item)

            overlap_item = QTableWidgetItem(str(ps.heroism_overlap_count))
            overlap_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._synergy_table.setItem(i, 3, overlap_item)

            score_item = QTableWidgetItem(f"{ps.synergy_score:.0f}%")
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if ps.synergy_score >= 75:
                score_item.setForeground(Qt.GlobalColor.green)
            elif ps.synergy_score >= 50:
                score_item.setForeground(Qt.GlobalColor.yellow)
            elif ps.total_cd_count > 0:
                score_item.setForeground(Qt.GlobalColor.red)
            self._synergy_table.setItem(i, 4, score_item)

    def _on_worker_error(self, message: str):
        self._cast_loading_banner.setVisible(False)
        self._resource_loading_banner.setVisible(False)
        self._cooldown_loading_banner.setVisible(False)
        self._hide_loading()
        self._status_label.setText(f"Error: {message}")
        self._status_label.setStyleSheet(
            f"color: {COLORS['error']}; padding: 4px 16px; background: {COLORS['bg_dark']};"
        )
        self._status_label.setVisible(True)
