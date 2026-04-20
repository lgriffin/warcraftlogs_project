"""
Analyze view — browse guild reports, run raid analysis, and display results.
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QComboBox, QTabWidget, QTableView,
    QProgressBar, QHeaderView, QGroupBox, QMessageBox,
    QSplitter, QTextEdit,
)
from PySide6.QtCore import Qt, Signal, QModelIndex
from PySide6.QtGui import QFont, QCursor

from .styles import COMMON_STYLES, COLORS
from .table_models import HealerTableModel, TankTableModel, DPSTableModel, HistoryTableModel
from .detail_panel import CharacterDetailPanel
from .worker import AnalysisWorker, GuildReportsWorker
from ..models import RaidAnalysis


class AnalyzeView(QWidget):
    status_message = Signal(str)
    navigate_to_character = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMMON_STYLES)
        self._worker = None
        self._guild_worker = None
        self._current_analysis = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ── Header ──
        header = QLabel("Analyze Raid")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(header)

        # ── Input row ──
        input_group = QGroupBox("Report")
        input_layout = QHBoxLayout(input_group)

        input_layout.addWidget(QLabel("Report ID:"))
        self.report_id_input = QLineEdit()
        self.report_id_input.setPlaceholderText("e.g. QNmWzDhyFZxKY6t4")
        self.report_id_input.setMinimumWidth(250)
        input_layout.addWidget(self.report_id_input)

        self.save_checkbox = QCheckBox("Save to database")
        self.save_checkbox.setChecked(True)
        input_layout.addWidget(self.save_checkbox)

        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.setFixedWidth(120)
        self.analyze_btn.clicked.connect(self._start_analysis)
        input_layout.addWidget(self.analyze_btn)

        input_layout.addStretch()
        layout.addWidget(input_group)

        # ── Progress bar ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        self.progress_label.setVisible(False)

        progress_layout = QHBoxLayout()
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_label)
        layout.addLayout(progress_layout)

        # ── Raid info banner ──
        self.raid_info = QLabel("")
        self.raid_info.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                padding: 10px 16px;
                border-radius: 6px;
                font-size: 13px;
            }}
        """)
        self.raid_info.setVisible(False)
        layout.addWidget(self.raid_info)

        # ── Main content: guild reports | results + detail ──
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel: guild reports
        guild_panel = QWidget()
        guild_layout = QVBoxLayout(guild_panel)
        guild_layout.setContentsMargins(0, 0, 8, 0)

        guild_header_layout = QHBoxLayout()
        guild_label = QLabel("Guild Reports")
        guild_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        guild_label.setStyleSheet(f"color: {COLORS['text_header']};")
        guild_header_layout.addWidget(guild_label)

        self.refresh_guild_btn = QPushButton("Fetch")
        self.refresh_guild_btn.setProperty("secondary", True)
        self.refresh_guild_btn.setFixedWidth(70)
        self.refresh_guild_btn.clicked.connect(self._fetch_guild_reports)
        guild_header_layout.addWidget(self.refresh_guild_btn)
        guild_layout.addLayout(guild_header_layout)

        # Day-of-week filter
        day_filter_layout = QHBoxLayout()
        day_filter_layout.setSpacing(4)
        filter_label = QLabel("Days:")
        filter_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        day_filter_layout.addWidget(filter_label)

        self._day_checkboxes = {}
        days = [("Mon", 0), ("Tue", 1), ("Wed", 2), ("Thu", 3),
                ("Fri", 4), ("Sat", 5), ("Sun", 6)]
        defaults_on = {2, 3, 6}  # Wed, Thu, Sun
        for label, idx in days:
            day_label = QLabel(label)
            day_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 11px;")
            day_filter_layout.addWidget(day_label)
            cb = QCheckBox()
            cb.setChecked(idx in defaults_on)
            cb.setStyleSheet("font-size: 11px;")
            cb.toggled.connect(self._apply_day_filter)
            self._day_checkboxes[idx] = cb
            day_filter_layout.addWidget(cb)

        day_filter_layout.addStretch()
        guild_layout.addLayout(day_filter_layout)

        self.guild_reports_model = HistoryTableModel(link_columns={"code"})
        self.guild_reports_table = QTableView()
        self.guild_reports_table.setModel(self.guild_reports_model)
        self.guild_reports_table.setAlternatingRowColors(True)
        self.guild_reports_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.guild_reports_table.verticalHeader().setVisible(False)
        self.guild_reports_table.horizontalHeader().setStretchLastSection(True)
        self.guild_reports_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.guild_reports_table.setStyleSheet(f"""
            QTableView {{
                alternate-background-color: {COLORS['bg_dark']};
            }}
        """)
        self.guild_reports_table.doubleClicked.connect(self._on_guild_report_double_clicked)
        self.guild_reports_table.clicked.connect(self._on_guild_report_clicked)
        guild_layout.addWidget(self.guild_reports_table, 1)

        self.content_splitter.addWidget(guild_panel)

        # Right panel: results + detail side panel
        right_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Results tabs
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setContentsMargins(8, 0, 0, 0)

        self.tabs = QTabWidget()

        self.healer_model = HealerTableModel()
        self.tank_model = TankTableModel()
        self.melee_model = DPSTableModel()
        self.ranged_model = DPSTableModel()

        self.tabs.addTab(self._make_table(self.healer_model), "Healers")
        self.tabs.addTab(self._make_table(self.tank_model), "Tanks")
        self.tabs.addTab(self._make_table(self.melee_model), "Melee DPS")
        self.tabs.addTab(self._make_table(self.ranged_model), "Ranged DPS")

        # Consumables tab with filter dropdown
        consumes_widget = QWidget()
        consumes_layout = QVBoxLayout(consumes_widget)
        consumes_layout.setContentsMargins(0, 4, 0, 0)

        consumes_bar = QHBoxLayout()
        consumes_bar.addWidget(QLabel("Filter:"))
        self._consumes_filter_combo = QComboBox()
        self._consumes_filter_combo.setMinimumWidth(180)
        self._consumes_filter_combo.setStyleSheet(f"""
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
        self._consumes_filter_combo.currentIndexChanged.connect(self._apply_consumes_filter)
        consumes_bar.addWidget(self._consumes_filter_combo)
        consumes_bar.addStretch()
        consumes_layout.addLayout(consumes_bar)

        self._consumes_model = HistoryTableModel()
        consumes_table = QTableView()
        consumes_table.setModel(self._consumes_model)
        consumes_table.setAlternatingRowColors(True)
        consumes_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        consumes_table.setSortingEnabled(True)
        consumes_table.verticalHeader().setVisible(False)
        consumes_table.horizontalHeader().setStretchLastSection(True)
        consumes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        consumes_table.setStyleSheet(f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        consumes_layout.addWidget(consumes_table, 1)
        self.tabs.addTab(consumes_widget, "Consumables")

        self.comp_text = QTextEdit()
        self.comp_text.setReadOnly(True)
        self.comp_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: none;
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 13px;
                padding: 12px;
            }}
        """)
        self.tabs.addTab(self.comp_text, "Composition")

        results_layout.addWidget(self.tabs, 1)
        right_splitter.addWidget(results_widget)

        # Character detail side panel
        self.detail_panel = CharacterDetailPanel()
        self.detail_panel.setMinimumWidth(350)
        self.detail_panel.view_history.connect(self.navigate_to_character.emit)
        self._right_splitter = right_splitter
        self.detail_panel.closed.connect(lambda: self._right_splitter.setSizes([1, 0]))
        right_splitter.addWidget(self.detail_panel)

        right_splitter.setSizes([1, 0])

        self.content_splitter.addWidget(right_splitter)
        self.content_splitter.setSizes([300, 800])

        layout.addWidget(self.content_splitter, 1)

        # ── Load defaults ──
        self._load_default_report_id()
        self.report_id_input.returnPressed.connect(self._start_analysis)

    def _make_table(self, model) -> QTableView:
        table = _ClickableNameTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setStyleSheet(table.styleSheet() + f"""
            QTableView {{
                alternate-background-color: {COLORS['bg_dark']};
            }}
        """)
        table.name_clicked.connect(self._on_character_clicked)
        return table

    def _get_player_consumables(self, name: str):
        if not self._current_analysis:
            return []
        return [c for c in self._current_analysis.consumables if c.player_name == name]

    def _on_character_clicked(self, name: str):
        if not self._current_analysis:
            return

        player_consumes = self._get_player_consumables(name)
        tab_idx = self.tabs.currentIndex()

        found = False

        # Prioritise the currently active tab so clicking a tank on the Tanks
        # tab doesn't accidentally match the same name in the healers list.
        if tab_idx == 1:  # Tanks
            for t in self._current_analysis.tanks:
                if t.name == name:
                    self.detail_panel.show_tank(t, player_consumes)
                    found = True
                    break
        elif tab_idx in (2, 3):  # Melee / Ranged DPS
            for d in self._current_analysis.dps:
                if d.name == name:
                    self.detail_panel.show_dps(d, player_consumes)
                    found = True
                    break

        if not found:
            for h in self._current_analysis.healers:
                if h.name == name:
                    self.detail_panel.show_healer(h, player_consumes)
                    found = True
                    break

        if not found:
            for t in self._current_analysis.tanks:
                if t.name == name:
                    self.detail_panel.show_tank(t, player_consumes)
                    found = True
                    break

        if not found:
            for d in self._current_analysis.dps:
                if d.name == name:
                    self.detail_panel.show_dps(d, player_consumes)
                    found = True
                    break

        if found:
            total = self._right_splitter.width()
            self._right_splitter.setSizes([total - 400, 400])

    def _load_default_report_id(self):
        try:
            from ..config import load_config
            config = load_config()
            self.report_id_input.setText(config.get("report_id", ""))
        except Exception:
            pass

    # ── Guild reports ──

    def _fetch_guild_reports(self):
        try:
            from ..config import load_config
            config = load_config()
            guild_id = config.get("guild_id", 774065)
        except Exception:
            guild_id = 774065

        self.refresh_guild_btn.setEnabled(False)
        self.status_message.emit("Fetching guild reports...")

        self._guild_worker = GuildReportsWorker(guild_id)
        self._guild_worker.finished.connect(self._on_guild_reports_loaded)
        self._guild_worker.error.connect(self._on_guild_reports_error)
        self._guild_worker.start()

    def _on_guild_reports_loaded(self, reports: list):
        self.refresh_guild_btn.setEnabled(True)
        self._guild_reports_raw = reports
        self._refresh_cached_codes()
        self._apply_day_filter()
        if reports:
            latest = max(reports, key=lambda r: r.get("start_time", 0))
            code = latest.get("code", "")
            if code:
                self.report_id_input.setText(code)
        self.status_message.emit(f"Loaded {len(reports)} guild reports")

    def _refresh_cached_codes(self):
        try:
            from ..database import PerformanceDB
            db = PerformanceDB()
            self._cached_codes = db.get_imported_report_codes()
        except Exception:
            self._cached_codes = set()

    def _apply_day_filter(self):
        if not hasattr(self, '_guild_reports_raw'):
            return

        allowed_days = {idx for idx, cb in self._day_checkboxes.items() if cb.isChecked()}
        cached = getattr(self, '_cached_codes', set())

        display_rows = []
        for r in self._guild_reports_raw:
            start = r.get("start_time", 0)
            if not start:
                continue
            dt = datetime.fromtimestamp(start / 1000)
            if dt.weekday() not in allowed_days:
                continue
            code = r.get("code", "")
            display_rows.append({
                "date": dt.strftime("%Y-%m-%d %H:%M"),
                "day": dt.strftime("%a"),
                "title": r.get("title", ""),
                "owner": r.get("owner", ""),
                "zone": r.get("zone", ""),
                "code": code,
                "saved": "Yes" if code in cached else "",
            })

        self.guild_reports_model.set_data(
            display_rows,
            ["date", "day", "title", "owner", "zone", "code", "saved"],
        )

    def _on_guild_reports_error(self, error_msg: str):
        self.refresh_guild_btn.setEnabled(True)
        self.status_message.emit(f"Failed to fetch guild reports: {error_msg}")

    def _on_guild_report_clicked(self, index: QModelIndex):
        row = index.row()
        rows = self.guild_reports_model._rows
        if row < len(rows):
            code = rows[row].get("code", "")
            if not code:
                return
            col_name = self.guild_reports_model._columns[index.column()] if index.column() < len(self.guild_reports_model._columns) else ""
            if col_name == "code":
                import webbrowser
                try:
                    from ..config import load_config
                    api_url = load_config().get("wcl_api_url", "")
                except Exception:
                    api_url = ""
                base = "https://fresh.warcraftlogs.com" if "fresh." in api_url else "https://www.warcraftlogs.com"
                webbrowser.open(f"{base}/reports/{code}")
            else:
                self.report_id_input.setText(code)

    def _on_guild_report_double_clicked(self, index: QModelIndex):
        row = index.row()
        rows = self.guild_reports_model._rows
        if row < len(rows):
            code = rows[row].get("code", "")
            if code:
                self.report_id_input.setText(code)
                self._start_analysis()

    def set_report_id(self, report_code: str):
        self.report_id_input.setText(report_code)
        self._start_analysis()

    # ── Analysis ──

    def _start_analysis(self):
        report_id = self.report_id_input.text().strip()
        if not report_id:
            QMessageBox.warning(self, "Missing Report ID",
                                "Please enter a WarcraftLogs report ID.")
            return

        self.analyze_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_label.setVisible(True)
        self.raid_info.setVisible(False)
        self.detail_panel.clear()

        self._worker = AnalysisWorker(report_id)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, message: str):
        self.progress_label.setText(message)
        self.status_message.emit(message)

    def _on_finished(self, analysis: RaidAnalysis):
        self._current_analysis = analysis
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.analyze_btn.setEnabled(True)

        m = analysis.metadata
        comp = analysis.composition
        self.raid_info.setText(
            f"{m.title}  |  {m.date_formatted}  |  "
            f"Owner: {m.owner}  |  "
            f"{len(comp.tanks)}T / {len(comp.healers)}H / "
            f"{len(comp.melee)}M / {len(comp.ranged)}R"
        )
        self.raid_info.setVisible(True)

        self.healer_model.set_data(analysis.healers)
        self.tank_model.set_data(analysis.tanks)
        self.melee_model.set_data([d for d in analysis.dps if d.role == "melee"])
        self.ranged_model.set_data([d for d in analysis.dps if d.role == "ranged"])

        self._populate_raid_consumables(analysis)
        self._render_composition(analysis)

        if self.save_checkbox.isChecked():
            try:
                from ..database import PerformanceDB
                with PerformanceDB() as db:
                    db.import_raid(analysis)
                self.status_message.emit(f"Analysis complete. Saved to database.")
                self._refresh_cached_codes()
                self._apply_day_filter()
            except Exception as e:
                self.status_message.emit(f"Analysis complete. DB save failed: {e}")
        else:
            self.status_message.emit("Analysis complete.")

        if analysis.healers:
            self.tabs.setCurrentIndex(0)
        elif analysis.tanks:
            self.tabs.setCurrentIndex(1)

    def _on_error(self, error_msg: str):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.status_message.emit(f"Error: {error_msg}")
        QMessageBox.critical(self, "Analysis Error", f"Failed to analyze raid:\n\n{error_msg}")

    def _populate_raid_consumables(self, analysis: RaidAnalysis):
        self._raid_consumables_raw = analysis.consumables
        consumes = analysis.consumables

        consumable_names = sorted({c.consumable_name for c in consumes})
        self._consumes_filter_combo.blockSignals(True)
        self._consumes_filter_combo.clear()
        self._consumes_filter_combo.addItem("All")
        for name in consumable_names:
            self._consumes_filter_combo.addItem(name)
        self._consumes_filter_combo.blockSignals(False)

        self._apply_consumes_filter()

    def _apply_consumes_filter(self):
        if not hasattr(self, '_raid_consumables_raw'):
            return

        consumes = self._raid_consumables_raw
        selected = self._consumes_filter_combo.currentText()

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

        self._consumes_model.set_data(rows, cols)

    def _render_composition(self, analysis: RaidAnalysis):
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

        self.comp_text.setPlainText("\n".join(lines))

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_guild_loaded') or not self._guild_loaded:
            self._guild_loaded = True
            self._fetch_guild_reports()


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
