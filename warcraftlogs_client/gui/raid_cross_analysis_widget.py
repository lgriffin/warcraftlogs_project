"""
Cross-analysis report widget.

Compares a selected raid against historical raids of the same size,
showing raid-level metrics (duration, DPS, HPS, damage taken) and
per-player deltas with spell and consumable breakdowns.
"""

from collections import defaultdict
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGridLayout, QFrame, QFileDialog, QMessageBox,
    QCheckBox, QComboBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS
from .charts import build_raid_trend_chart

_ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def _fmt_number(val, suffix=""):
    if val is None:
        return "N/A"
    if abs(val) >= 1_000_000:
        return f"{val / 1_000_000:.1f}M{suffix}"
    if abs(val) >= 1_000:
        return f"{val / 1_000:.1f}K{suffix}"
    return f"{val:,.0f}{suffix}"


def _fmt_duration(ms):
    if not ms or ms <= 0:
        return "N/A"
    total_s = ms / 1000
    hours = int(total_s // 3600)
    minutes = int((total_s % 3600) // 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _pct_change(current, average):
    if not average or average == 0:
        return 0.0
    return (current - average) / average * 100


def _delta_label(pct, invert=False):
    if pct == 0:
        return "—", COLORS["text_dim"]
    good = pct < 0 if invert else pct > 0
    color = COLORS["success"] if good else COLORS["error"]
    arrow = "▲" if pct > 0 else "▼"
    return f"{arrow} {abs(pct):.1f}%", color


def _rlabel(text, color=None, bold=False):
    lbl = QLabel(str(text))
    lbl.setAlignment(_ALIGN_RIGHT)
    style = "background: transparent; border: none;"
    if color:
        style += f" color: {color};"
    lbl.setStyleSheet(style)
    if bold:
        lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
    return lbl


class RaidCrossAnalysisWidget(QWidget):
    status_message = Signal(str)
    request_back = Signal()
    open_raid = Signal(str)

    def __init__(self, report_id: str, parent=None):
        super().__init__(parent)
        self._report_id = report_id
        self._export_data = {}
        self._raid_stats = None
        self._historical = []
        self._players = []
        self._size_mode = 1
        self._size_label = ""
        self._zone = None
        self._build_ui()
        self._load_data()

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

        self._title_label = QLabel("Cross-Analysis Report")
        self._title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {COLORS['text_header']};")
        header_layout.addWidget(self._title_label)

        header_layout.addStretch()

        export_btn = QPushButton("Export")
        export_btn.setProperty("secondary", True)
        export_btn.setFixedHeight(32)
        export_btn.clicked.connect(self._export_markdown)
        header_layout.addWidget(export_btn)

        layout.addWidget(header)

        # ── Filter toolbar ──
        toolbar = QWidget()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; "
            f"border-bottom: 1px solid {COLORS['border']};")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(16, 0, 16, 0)
        tb_layout.setSpacing(16)

        compare_lbl = QLabel("Compare:")
        compare_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        tb_layout.addWidget(compare_lbl)

        cb_style = f"QCheckBox {{ color: {COLORS['text']}; font-size: 12px; spacing: 4px; }}"

        self._hist_cb = QCheckBox("Historical Avg")
        self._hist_cb.setChecked(True)
        self._hist_cb.setStyleSheet(cb_style)
        self._hist_cb.toggled.connect(self._on_mode_changed)
        tb_layout.addWidget(self._hist_cb)

        self._last3_cb = QCheckBox("Last 3 Raids")
        self._last3_cb.setChecked(False)
        self._last3_cb.setStyleSheet(cb_style)
        self._last3_cb.toggled.connect(self._on_mode_changed)
        tb_layout.addWidget(self._last3_cb)

        tb_layout.addSpacing(16)

        day_label = QLabel("Day:")
        day_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        tb_layout.addWidget(day_label)

        self._day_combo = QComboBox()
        self._day_combo.addItems([
            "Any Day", "Monday", "Tuesday", "Wednesday",
            "Thursday", "Friday", "Saturday", "Sunday",
        ])
        self._day_combo.setFixedHeight(26)
        self._day_combo.setMinimumWidth(120)
        self._day_combo.setStyleSheet(f"""
            QComboBox {{
                color: {COLORS['text']};
                background-color: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                color: {COLORS['text']};
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                selection-background-color: {COLORS['accent']};
            }}
        """)
        self._day_combo.currentIndexChanged.connect(self._on_mode_changed)
        tb_layout.addWidget(self._day_combo)

        tb_layout.addStretch()
        layout.addWidget(toolbar)

        # ── Scroll content ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f"QScrollArea {{ background-color: {COLORS['bg_dark']}; border: none; }}")

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(24, 16, 24, 24)
        self._content_layout.setSpacing(16)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)

    def _on_mode_changed(self):
        if not self._hist_cb.isChecked() and not self._last3_cb.isChecked():
            sender = self.sender()
            sender.setChecked(True)
            return
        if self._raid_stats:
            self._refresh_content()

    def _load_data(self):
        from ..database import PerformanceDB

        try:
            with PerformanceDB() as db:
                raid_stats = db.get_raid_aggregate_stats(self._report_id)
                if not raid_stats:
                    self._show_error("Raid not found in database.")
                    return

                raid_size = raid_stats.get("raid_size") or 0
                self._size_mode = 1 if raid_size <= 15 else 2
                self._size_label = f"{raid_size}-man" if raid_size else "Unknown size"
                self._zone = raid_stats.get("zone")

                self._raid_stats = raid_stats
                self._historical = db.get_historical_raid_aggregates(
                    self._size_mode, self._report_id, zone=self._zone)
                self._players = db.get_player_performance_for_raid(self._report_id)
        except Exception as e:
            self._show_error(f"Error loading data: {e}")
            return

        self._title_label.setText(f"Cross-Analysis: {raid_stats['title']}")

        raid_date_str = raid_stats.get("raid_date", "")[:10]
        if raid_date_str:
            try:
                raid_day = datetime.strptime(raid_date_str, "%Y-%m-%d").strftime("%A")
                idx = self._day_combo.findText(raid_day)
                if idx >= 0:
                    self._day_combo.setCurrentIndex(idx)
            except ValueError:
                pass

        self._refresh_content()

    def _refresh_content(self):
        old = self._scroll.takeWidget()
        if old:
            old.deleteLater()

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        self._content.setMaximumWidth(1200)
        outer = QWidget()
        outer.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        outer_layout = QHBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addStretch()
        outer_layout.addWidget(self._content)
        outer_layout.addStretch()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(24, 16, 24, 24)
        self._content_layout.setSpacing(16)
        self._scroll.setWidget(outer)

        selected_day = self._day_combo.currentText()
        if selected_day == "Any Day":
            filtered_historical = self._historical
        else:
            filtered_historical = [
                h for h in self._historical
                if self._raid_day_name(h.get("raid_date", "")) == selected_day
            ]

        active_modes = []
        if self._hist_cb.isChecked():
            active_modes.append(("Historical Avg", None))
        if self._last3_cb.isChecked():
            active_modes.append(("Last 3 Avg", 3))
        if not active_modes:
            active_modes = [("Historical Avg", None)]

        mode_data = []
        from ..database import PerformanceDB
        try:
            with PerformanceDB() as db:
                for label, last_n in active_modes:
                    hist_subset = filtered_historical[-last_n:] if last_n else filtered_historical
                    player_deltas = self._compute_player_deltas(
                        db, self._players, self._size_mode, last_n)
                    mode_data.append((label, hist_subset, player_deltas))
        except Exception as e:
            self._show_error(f"Error computing: {e}")
            return

        self._build_summary_section(self._raid_stats, mode_data, self._size_label)
        self._build_trend_charts(self._raid_stats, self._historical)
        self._build_player_sections(mode_data)
        self._content_layout.addStretch()

        self._export_data = {
            "raid_stats": self._raid_stats,
            "historical": mode_data[0][1],
            "player_deltas": mode_data[0][2],
            "size_label": self._size_label,
        }

    def _compute_player_deltas(self, db, players, size_mode, last_n=None):
        deltas = []
        for p in players:
            name = p["name"]
            role = p["role"]
            delta = {
                "name": name,
                "player_class": p["player_class"],
                "role": role,
                "metrics": {},
                "spell_deltas": [],
                "consumable_deltas": [],
            }

            if role == "healer":
                delta["metrics"]["total_healing"] = p.get("total_healing", 0)
                delta["metrics"]["overheal_percent"] = p.get("overheal_percent", 0)
                trend = db.get_healer_trend(name, limit=50)
                filtered = [r for r in trend if r.get("report_id") != self._report_id
                            and self._matches_filter(r, size_mode)]
                if last_n is not None:
                    filtered = filtered[-last_n:]
                if filtered:
                    avg_healing = sum(r["total_healing"] for r in filtered) / len(filtered)
                    avg_oh = sum(r["overheal_percent"] for r in filtered) / len(filtered)
                    delta["metrics"]["avg_healing"] = avg_healing
                    delta["metrics"]["avg_overheal"] = avg_oh
                    delta["metrics"]["healing_pct"] = _pct_change(p["total_healing"], avg_healing)
                spell_trend = db.get_healer_spell_trend(name, limit=50)
                delta["spell_deltas"] = self._compute_spell_deltas(
                    spell_trend, size_mode, "total_healing", last_n)
            elif role == "tank":
                delta["metrics"]["total_damage_taken"] = p.get("total_damage_taken", 0)
                delta["metrics"]["mitigation_percent"] = p.get("mitigation_percent", 0)
                trend = db.get_tank_trend(name, limit=50)
                filtered = [r for r in trend if r.get("report_id") != self._report_id
                            and self._matches_filter(r, size_mode)]
                if last_n is not None:
                    filtered = filtered[-last_n:]
                if filtered:
                    avg_taken = sum(r["total_damage_taken"] for r in filtered) / len(filtered)
                    avg_mit = sum(r["mitigation_percent"] for r in filtered) / len(filtered)
                    delta["metrics"]["avg_damage_taken"] = avg_taken
                    delta["metrics"]["avg_mitigation"] = avg_mit
                    delta["metrics"]["taken_pct"] = _pct_change(p["total_damage_taken"], avg_taken)
                    delta["metrics"]["mitigation_pct"] = _pct_change(p["mitigation_percent"], avg_mit)
            else:
                delta["metrics"]["total_damage"] = p.get("total_damage", 0)
                trend = db.get_dps_trend(name, limit=50)
                filtered = [r for r in trend if r.get("report_id") != self._report_id
                            and self._matches_filter(r, size_mode)]
                if last_n is not None:
                    filtered = filtered[-last_n:]
                if filtered:
                    avg_damage = sum(r["total_damage"] for r in filtered) / len(filtered)
                    delta["metrics"]["avg_damage"] = avg_damage
                    delta["metrics"]["damage_pct"] = _pct_change(p["total_damage"], avg_damage)
                spell_trend = db.get_dps_ability_trend(name, limit=50)
                delta["spell_deltas"] = self._compute_spell_deltas(
                    spell_trend, size_mode, "total_damage", last_n)

            con_trend = db.get_consumable_trend(name, limit=50)
            delta["consumable_deltas"] = self._compute_consumable_deltas(
                con_trend, size_mode, last_n)

            deltas.append(delta)
        return deltas

    @staticmethod
    def _raid_day_name(raid_date_str: str) -> str:
        try:
            return datetime.strptime(raid_date_str[:10], "%Y-%m-%d").strftime("%A")
        except (ValueError, TypeError):
            return ""

    def _matches_filter(self, row, size_mode):
        rs = row.get("raid_size")
        if rs is None:
            return False
        if size_mode == 1 and rs > 15:
            return False
        if size_mode == 2 and rs <= 15:
            return False
        if self._zone:
            if row.get("zone") != self._zone:
                return False
        selected_day = self._day_combo.currentText()
        if selected_day != "Any Day":
            if self._raid_day_name(row.get("raid_date", "")) != selected_day:
                return False
        return True

    def _compute_spell_deltas(self, spell_trend, size_mode, value_key, last_n=None):
        by_raid: dict[str, dict[str, dict]] = defaultdict(dict)
        for row in spell_trend:
            if not self._matches_filter(row, size_mode):
                continue
            raid_key = row.get("raid_date", "")
            spell = row.get("spell_name", "")
            by_raid[raid_key][spell] = {
                "casts": row.get("casts", 0),
                "value": row.get(value_key, 0) or 0,
            }

        raid_dates = sorted(by_raid.keys())
        if len(raid_dates) < 2:
            return []

        this_raid_date = raid_dates[-1]
        this_spells = by_raid[this_raid_date]
        hist_dates = raid_dates[:-1]
        if last_n is not None:
            hist_dates = hist_dates[-last_n:]

        spell_avgs: dict[str, dict] = defaultdict(lambda: {"casts": 0, "value": 0, "count": 0})
        for d in hist_dates:
            for spell, data in by_raid[d].items():
                spell_avgs[spell]["casts"] += data["casts"]
                spell_avgs[spell]["value"] += data["value"]
                spell_avgs[spell]["count"] += 1

        all_spells = set(this_spells.keys()) | set(spell_avgs.keys())
        results = []
        for spell in sorted(all_spells):
            this_data = this_spells.get(spell, {"casts": 0, "value": 0})
            avg_data = spell_avgs.get(spell)
            if avg_data and avg_data["count"] > 0:
                avg_casts = avg_data["casts"] / avg_data["count"]
                avg_value = avg_data["value"] / avg_data["count"]
            else:
                avg_casts = 0
                avg_value = 0
            results.append({
                "spell_name": spell,
                "this_casts": this_data["casts"],
                "avg_casts": avg_casts,
                "cast_delta": this_data["casts"] - avg_casts,
                "this_value": this_data["value"],
                "avg_value": avg_value,
            })
        results.sort(key=lambda x: x["this_casts"], reverse=True)
        return results[:15]

    def _compute_consumable_deltas(self, con_trend, size_mode, last_n=None):
        by_raid: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in con_trend:
            if not self._matches_filter(row, size_mode):
                continue
            raid_key = row.get("report_id") or row.get("raid_date", "")
            con = row.get("consumable_name", "")
            by_raid[raid_key][con] += row.get("count", 0)

        if len(by_raid) < 2:
            return []

        raid_keys = sorted(by_raid.keys())
        this_key = raid_keys[-1]
        this_cons = by_raid[this_key]
        hist_keys = raid_keys[:-1]
        if last_n is not None:
            hist_keys = hist_keys[-last_n:]

        con_totals: dict[str, dict] = defaultdict(lambda: {"total": 0, "count": 0})
        for k in hist_keys:
            for con, count in by_raid[k].items():
                con_totals[con]["total"] += count
                con_totals[con]["count"] += 1

        all_cons = set(this_cons.keys()) | set(con_totals.keys())
        results = []
        for con in sorted(all_cons):
            this_count = this_cons.get(con, 0)
            avg_data = con_totals.get(con)
            avg_count = avg_data["total"] / avg_data["count"] if avg_data and avg_data["count"] > 0 else 0
            results.append({
                "consumable_name": con,
                "this_count": this_count,
                "avg_count": avg_count,
                "delta": this_count - avg_count,
            })
        results.sort(key=lambda x: x["this_count"], reverse=True)
        return results

    # ── Summary section ──

    def _build_summary_section(self, raid_stats, mode_data, size_label):
        section = QWidget()
        section.setStyleSheet(f"background-color: {COLORS['bg_card']}; border-radius: 8px;")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(20, 16, 20, 16)
        section_layout.setSpacing(6)

        zone_str = f" &nbsp;|&nbsp; {raid_stats['zone']}" if raid_stats.get("zone") else ""
        info_label = QLabel(
            f"<b>{raid_stats['title']}</b> &nbsp;|&nbsp; {raid_stats.get('raid_date', '')[:10]}"
            f" &nbsp;|&nbsp; {size_label}{zone_str}"
            f" &nbsp;|&nbsp; Duration: {_fmt_duration(raid_stats['duration_ms'])}"
        )
        info_label.setFont(QFont("Segoe UI", 11))
        info_label.setStyleSheet(f"color: {COLORS['text']};")
        section_layout.addWidget(info_label)

        for label, hist_subset, _ in mode_data:
            compare_label = QLabel(f"{label}: compared against {len(hist_subset)} {size_label} raids")
            compare_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
            section_layout.addWidget(compare_label)

            show_links = hist_subset and len(hist_subset) <= 5
            if show_links:
                raids_row = QHBoxLayout()
                raids_row.setContentsMargins(0, 0, 0, 0)
                raids_row.setSpacing(12)
                for raid in hist_subset:
                    raid_date = raid.get("raid_date", "")[:10]
                    btn = QPushButton(f"{raid['title']}  ({raid_date})")
                    btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            color: {COLORS['accent']};
                            background: transparent;
                            border: none;
                            font-size: 11px;
                            text-decoration: underline;
                            padding: 0 4px;
                        }}
                        QPushButton:hover {{
                            color: {COLORS['text_header']};
                        }}
                    """)
                    rid = raid["report_id"]
                    btn.clicked.connect(lambda checked, r=rid: self.open_raid.emit(r))
                    raids_row.addWidget(btn)
                raids_row.addStretch()
                section_layout.addLayout(raids_row)

        any_historical = any(len(h) > 0 for _, h, _ in mode_data)
        if not any_historical:
            no_data = QLabel("No historical raids of this size to compare against.")
            no_data.setStyleSheet(f"color: {COLORS['warning']}; font-size: 12px; padding: 8px;")
            section_layout.addWidget(no_data)
            self._content_layout.addWidget(section)
            return

        mode_avgs = []
        for label, hist_subset, _ in mode_data:
            if not hist_subset:
                continue
            n = len(hist_subset)
            mode_avgs.append((
                label,
                sum(h["duration_ms"] for h in hist_subset) / n,
                sum(h["total_damage"] for h in hist_subset) / n,
                sum(h["total_healing"] for h in hist_subset) / n,
                sum(h["total_damage_taken"] for h in hist_subset) / n,
            ))

        if not mode_avgs:
            self._content_layout.addWidget(section)
            return

        duration_down = raid_stats["duration_ms"] < mode_avgs[0][1]

        metrics = [
            ("Duration", raid_stats["duration_ms"], True, True),
            ("Total Damage", raid_stats["total_damage"], False, duration_down),
            ("Total Healing", raid_stats["total_healing"], False, duration_down),
            ("Damage Taken", raid_stats["total_damage_taken"], False, True),
        ]

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        for i, (metric_label, current_val, is_duration, invert) in enumerate(metrics):
            card_deltas = []
            for mode_label, avg_dur, avg_dmg, avg_heal, avg_taken in mode_avgs:
                if metric_label == "Duration":
                    avg = avg_dur
                elif metric_label == "Total Damage":
                    avg = avg_dmg
                elif metric_label == "Total Healing":
                    avg = avg_heal
                else:
                    avg = avg_taken
                pct = _pct_change(current_val, avg)
                formatted_avg = _fmt_duration(avg) if is_duration else _fmt_number(avg)
                card_deltas.append((mode_label, formatted_avg, pct, invert))

            formatted_current = _fmt_duration(current_val) if is_duration else _fmt_number(current_val)
            card = self._make_summary_card(metric_label, formatted_current, card_deltas)
            cards_layout.addWidget(card)

        section_layout.addLayout(cards_layout)
        self._content_layout.addWidget(section)

    def _make_summary_card(self, title, this_val, deltas):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 12px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Segoe UI", 10))
        title_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; border: none;")
        card_layout.addWidget(title_lbl)

        val_lbl = QLabel(str(this_val))
        val_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        val_lbl.setStyleSheet(f"color: {COLORS['text_header']}; border: none;")
        card_layout.addWidget(val_lbl)

        for mode_label, avg_val, pct, invert in deltas:
            delta_text, delta_color = _delta_label(pct, invert)
            delta_lbl = QLabel(f"{delta_text}  vs {mode_label.lower()} {avg_val}")
            delta_lbl.setFont(QFont("Segoe UI", 10))
            delta_lbl.setStyleSheet(f"color: {delta_color}; border: none;")
            card_layout.addWidget(delta_lbl)

        return card

    # ── Trend charts ──

    def _build_trend_charts(self, raid_stats, historical):
        if not historical:
            return

        section_label = QLabel("Raid Trends")
        section_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        section_label.setStyleSheet(f"color: {COLORS['text_header']};")
        self._content_layout.addWidget(section_label)

        chart_grid = QGridLayout()
        chart_grid.setSpacing(8)

        charts = [
            ("duration_ms", "Duration Over Time", "Duration (ms)"),
            ("total_damage", "Total Damage Over Time", "Damage"),
            ("total_healing", "Total Healing Over Time", "Healing"),
            ("total_damage_taken", "Damage Taken Over Time", "Damage Taken"),
        ]

        for i, (key, title, y_label) in enumerate(charts):
            chart_view = build_raid_trend_chart(historical, raid_stats, key, title, y_label)
            chart_view.setMaximumHeight(200)
            chart_view.setMinimumHeight(160)
            chart_grid.addWidget(chart_view, i // 2, i % 2)

        chart_wrapper = QWidget()
        chart_wrapper.setLayout(chart_grid)
        self._content_layout.addWidget(chart_wrapper)

    # ── Player sections ──

    def _build_player_sections(self, mode_data):
        roles = [
            ("Healers", "healer"),
            ("Tanks", "tank"),
            ("Melee DPS", "melee"),
            ("Ranged DPS", "ranged"),
        ]

        first_deltas = mode_data[0][2]

        for role_label, role_key in roles:
            players = [p for p in first_deltas if p["role"] == role_key]
            if not players:
                continue

            section_label = QLabel(role_label)
            section_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
            section_label.setStyleSheet(f"color: {COLORS['text_header']}; margin-top: 8px;")
            self._content_layout.addWidget(section_label)

            for p in sorted(players, key=lambda x: x["name"]):
                player_modes = []
                for label, _, deltas in mode_data:
                    matching = [d for d in deltas if d["name"] == p["name"]]
                    if matching:
                        player_modes.append((label, matching[0]))
                if player_modes:
                    self._build_player_card(player_modes)

    def _build_player_card(self, player_modes):
        first_label, first_delta = player_modes[0]

        card = QWidget()
        card.setObjectName("playerCard")
        card.setStyleSheet(f"""
            QWidget#playerCard {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
            }}
            QWidget#playerCard QWidget {{
                background-color: transparent;
                color: {COLORS['text']};
            }}
            QWidget#playerCard QLabel {{
                color: {COLORS['text']};
                background-color: transparent;
                border: none;
            }}
            QWidget#playerCard QPushButton {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                color: {COLORS['text']};
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 12px;
            }}
            QWidget#playerCard QPushButton:hover {{
                background-color: {COLORS['border']};
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(8)

        header_layout = QHBoxLayout()
        name_label = QLabel(f"{first_delta['name']}  ({first_delta['player_class']})")
        name_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        name_label.setStyleSheet(f"color: {COLORS['accent']};")
        header_layout.addWidget(name_label)

        primary_pct = self._get_primary_pct(first_delta)
        if primary_pct is not None:
            invert = first_delta["role"] == "tank"
            delta_text, delta_color = _delta_label(primary_pct, invert)
            pct_label = QLabel(delta_text)
            pct_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            pct_label.setStyleSheet(f"color: {delta_color};")
            header_layout.addWidget(pct_label)

        header_layout.addStretch()

        toggle_btn = QPushButton("Show Details")
        toggle_btn.setFixedHeight(28)
        header_layout.addWidget(toggle_btn)

        card_layout.addLayout(header_layout)

        detail_widget = QWidget()
        detail_widget.setStyleSheet("background-color: transparent;")
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 8, 0, 0)
        detail_layout.setSpacing(12)
        detail_widget.setVisible(False)

        def toggle():
            visible = not detail_widget.isVisible()
            detail_widget.setVisible(visible)
            toggle_btn.setText("Hide Details" if visible else "Show Details")

        toggle_btn.clicked.connect(toggle)

        self._add_metrics_table(detail_layout, player_modes)

        if first_delta.get("spell_deltas"):
            self._add_spell_table(detail_layout, first_delta["spell_deltas"])

        if first_delta.get("consumable_deltas"):
            self._add_consumable_table(detail_layout, first_delta["consumable_deltas"])

        card_layout.addWidget(detail_widget)
        self._content_layout.addWidget(card)

    def _get_primary_pct(self, delta):
        m = delta["metrics"]
        if delta["role"] == "healer":
            return m.get("healing_pct")
        elif delta["role"] == "tank":
            return m.get("taken_pct")
        else:
            return m.get("damage_pct")

    # ── Data tables ──

    def _add_metrics_table(self, parent_layout, player_modes):
        first_delta = player_modes[0][1]
        role = first_delta["role"]

        label = QLabel("Performance Metrics")
        label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
        parent_layout.addWidget(label)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnMinimumWidth(0, 120)
        grid.setColumnMinimumWidth(1, 90)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        col_idx = 2
        for _ in player_modes:
            grid.setColumnMinimumWidth(col_idx, 90)
            grid.setColumnMinimumWidth(col_idx + 1, 80)
            grid.setColumnStretch(col_idx, 1)
            grid.setColumnStretch(col_idx + 1, 1)
            col_idx += 2

        headers = ["Metric", "This Raid"]
        for mode_label, _ in player_modes:
            headers.extend([mode_label, "Change"])

        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
            align = _ALIGN_LEFT if col == 0 else _ALIGN_RIGHT
            lbl.setAlignment(align)
            grid.addWidget(lbl, 0, col)

        row = 1
        if role == "healer":
            mode_avgs = []
            for _, delta in player_modes:
                m = delta["metrics"]
                mode_avgs.append((
                    _fmt_number(m.get("avg_healing")),
                    m.get("healing_pct"),
                    False,
                ))
            row = self._metrics_row(grid, row, "Total Healing",
                                    _fmt_number(first_delta["metrics"].get("total_healing")),
                                    mode_avgs)

            oh_avgs = []
            for _, delta in player_modes:
                m = delta["metrics"]
                avg_oh = m.get("avg_overheal")
                oh_avgs.append((
                    f"{avg_oh:.1f}%" if avg_oh is not None else "N/A",
                    None,
                    True,
                ))
            row = self._metrics_row(grid, row, "Overheal %",
                                    f"{first_delta['metrics'].get('overheal_percent', 0):.1f}%",
                                    oh_avgs)
        elif role == "tank":
            taken_avgs = []
            for _, delta in player_modes:
                m = delta["metrics"]
                taken_avgs.append((
                    _fmt_number(m.get("avg_damage_taken")),
                    m.get("taken_pct"),
                    True,
                ))
            row = self._metrics_row(grid, row, "Damage Taken",
                                    _fmt_number(first_delta["metrics"].get("total_damage_taken")),
                                    taken_avgs)

            mit_avgs = []
            for _, delta in player_modes:
                m = delta["metrics"]
                avg_mit = m.get("avg_mitigation")
                mit_avgs.append((
                    f"{avg_mit:.1f}%" if avg_mit is not None else "N/A",
                    m.get("mitigation_pct"),
                    False,
                ))
            row = self._metrics_row(grid, row, "Mitigation %",
                                    f"{first_delta['metrics'].get('mitigation_percent', 0):.1f}%",
                                    mit_avgs)
        else:
            dmg_avgs = []
            for _, delta in player_modes:
                m = delta["metrics"]
                dmg_avgs.append((
                    _fmt_number(m.get("avg_damage")),
                    m.get("damage_pct"),
                    False,
                ))
            row = self._metrics_row(grid, row, "Total Damage",
                                    _fmt_number(first_delta["metrics"].get("total_damage")),
                                    dmg_avgs)

        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        wrapper.setLayout(grid)
        parent_layout.addWidget(wrapper)

    def _metrics_row(self, grid, row, name, this_val, mode_avgs):
        name_lbl = QLabel(name)
        name_lbl.setAlignment(_ALIGN_LEFT)
        name_lbl.setStyleSheet("background: transparent;")
        grid.addWidget(name_lbl, row, 0)

        grid.addWidget(_rlabel(this_val), row, 1)

        col = 2
        for avg_str, pct, invert in mode_avgs:
            grid.addWidget(_rlabel(avg_str), row, col)
            if pct is not None:
                delta_text, delta_color = _delta_label(pct, invert)
                grid.addWidget(_rlabel(delta_text, color=delta_color), row, col + 1)
            else:
                grid.addWidget(_rlabel("—"), row, col + 1)
            col += 2
        return row + 1

    def _add_spell_table(self, parent_layout, spell_deltas):
        label = QLabel("Spell / Ability Changes")
        label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
        parent_layout.addWidget(label)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        grid.setColumnMinimumWidth(0, 160)
        grid.setColumnMinimumWidth(1, 80)
        grid.setColumnMinimumWidth(2, 80)
        grid.setColumnMinimumWidth(3, 80)

        headers = ["Spell", "Casts (This)", "Avg Casts", "Cast Delta"]
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
            lbl.setAlignment(_ALIGN_LEFT if col == 0 else _ALIGN_RIGHT)
            grid.addWidget(lbl, 0, col)

        for i, s in enumerate(spell_deltas[:10]):
            row = i + 1
            spell_lbl = QLabel(s["spell_name"])
            spell_lbl.setStyleSheet("background: transparent;")
            grid.addWidget(spell_lbl, row, 0)
            grid.addWidget(_rlabel(str(s["this_casts"])), row, 1)
            grid.addWidget(_rlabel(f"{s['avg_casts']:.1f}"), row, 2)
            d = s["cast_delta"]
            if d > 0:
                grid.addWidget(_rlabel(f"+{d:.0f}", COLORS['success']), row, 3)
            elif d < 0:
                grid.addWidget(_rlabel(f"{d:.0f}", COLORS['error']), row, 3)
            else:
                grid.addWidget(_rlabel("—", COLORS['text_dim']), row, 3)

        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        wrapper.setLayout(grid)
        parent_layout.addWidget(wrapper)

    def _add_consumable_table(self, parent_layout, consumable_deltas):
        label = QLabel("Consumable Changes")
        label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
        parent_layout.addWidget(label)

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        grid.setColumnMinimumWidth(0, 160)
        grid.setColumnMinimumWidth(1, 80)
        grid.setColumnMinimumWidth(2, 80)
        grid.setColumnMinimumWidth(3, 80)

        headers = ["Consumable", "Count (This)", "Avg Count", "Delta"]
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
            lbl.setAlignment(_ALIGN_LEFT if col == 0 else _ALIGN_RIGHT)
            grid.addWidget(lbl, 0, col)

        for i, c in enumerate(consumable_deltas[:10]):
            row = i + 1
            con_lbl = QLabel(c["consumable_name"])
            con_lbl.setStyleSheet("background: transparent;")
            grid.addWidget(con_lbl, row, 0)
            grid.addWidget(_rlabel(str(c["this_count"])), row, 1)
            grid.addWidget(_rlabel(f"{c['avg_count']:.1f}"), row, 2)
            d = c["delta"]
            if d > 0.5:
                grid.addWidget(_rlabel(f"+{d:.0f}", COLORS['success']), row, 3)
            elif d < -0.5:
                grid.addWidget(_rlabel(f"{d:.0f}", COLORS['error']), row, 3)
            else:
                grid.addWidget(_rlabel("—", COLORS['text_dim']), row, 3)

        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        wrapper.setLayout(grid)
        parent_layout.addWidget(wrapper)

    # ── Misc ──

    def _show_error(self, message):
        lbl = QLabel(message)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet(f"color: {COLORS['error']}; padding: 20px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(lbl)

    def _export_markdown(self):
        if not self._export_data:
            QMessageBox.warning(self, "Export", "No data to export.")
            return

        raid_stats = self._export_data["raid_stats"]
        safe_title = "".join(
            c if c.isalnum() or c in " _-" else "_"
            for c in raid_stats["title"]
        ).strip().replace(" ", "_")

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Cross-Analysis Report",
            f"{safe_title}_cross_analysis.md",
            "Markdown Files (*.md);;All Files (*)",
        )
        if not path:
            return

        try:
            from ..renderers.markdown import export_cross_analysis
            export_cross_analysis(
                self._export_data["raid_stats"],
                self._export_data["historical"],
                self._export_data["player_deltas"],
                self._export_data["size_label"],
                output_path=path,
            )
            self.status_message.emit(f"Exported to {path}")
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n\n{e}")
