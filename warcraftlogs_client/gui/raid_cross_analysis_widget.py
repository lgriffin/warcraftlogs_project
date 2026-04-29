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
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS
from .charts import build_raid_trend_chart


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


class RaidCrossAnalysisWidget(QWidget):
    status_message = Signal(str)
    request_back = Signal()

    def __init__(self, report_id: str, parent=None):
        super().__init__(parent)
        self._report_id = report_id
        self._export_data = {}
        self._build_ui()
        self._load_data()

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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ background-color: {COLORS['bg_dark']}; border: none; }}")

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(24, 16, 24, 24)
        self._content_layout.setSpacing(16)
        scroll.setWidget(self._content)
        layout.addWidget(scroll, 1)

    def _load_data(self):
        from ..database import PerformanceDB

        try:
            with PerformanceDB() as db:
                raid_stats = db.get_raid_aggregate_stats(self._report_id)
                if not raid_stats:
                    self._show_error("Raid not found in database.")
                    return

                raid_size = raid_stats.get("raid_size") or 0
                size_mode = 1 if raid_size <= 15 else 2
                size_label = f"{raid_size}-man" if raid_size else "Unknown size"

                historical = db.get_historical_raid_aggregates(size_mode, self._report_id)
                players = db.get_player_performance_for_raid(self._report_id)

                player_deltas = self._compute_player_deltas(db, players, size_mode)
        except Exception as e:
            self._show_error(f"Error loading data: {e}")
            return

        self._title_label.setText(f"Cross-Analysis: {raid_stats['title']}")

        self._export_data = {
            "raid_stats": raid_stats,
            "historical": historical,
            "player_deltas": player_deltas,
            "size_label": size_label,
        }

        self._build_summary_section(raid_stats, historical, size_label)
        self._build_trend_charts(raid_stats, historical)
        self._build_player_sections(player_deltas)
        self._content_layout.addStretch()

    def _compute_player_deltas(self, db, players, size_mode):
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
                            and self._matches_size(r, size_mode)]
                if filtered:
                    avg_healing = sum(r["total_healing"] for r in filtered) / len(filtered)
                    avg_oh = sum(r["overheal_percent"] for r in filtered) / len(filtered)
                    delta["metrics"]["avg_healing"] = avg_healing
                    delta["metrics"]["avg_overheal"] = avg_oh
                    delta["metrics"]["healing_pct"] = _pct_change(p["total_healing"], avg_healing)
                spell_trend = db.get_healer_spell_trend(name, limit=50)
                delta["spell_deltas"] = self._compute_spell_deltas(
                    spell_trend, size_mode, "total_healing")
            elif role == "tank":
                delta["metrics"]["total_damage_taken"] = p.get("total_damage_taken", 0)
                delta["metrics"]["mitigation_percent"] = p.get("mitigation_percent", 0)
                trend = db.get_tank_trend(name, limit=50)
                filtered = [r for r in trend if r.get("report_id") != self._report_id
                            and self._matches_size(r, size_mode)]
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
                            and self._matches_size(r, size_mode)]
                if filtered:
                    avg_damage = sum(r["total_damage"] for r in filtered) / len(filtered)
                    delta["metrics"]["avg_damage"] = avg_damage
                    delta["metrics"]["damage_pct"] = _pct_change(p["total_damage"], avg_damage)
                spell_trend = db.get_dps_ability_trend(name, limit=50)
                delta["spell_deltas"] = self._compute_spell_deltas(
                    spell_trend, size_mode, "total_damage")

            con_trend = db.get_consumable_trend(name, limit=50)
            delta["consumable_deltas"] = self._compute_consumable_deltas(con_trend, size_mode)

            deltas.append(delta)
        return deltas

    def _matches_size(self, row, size_mode):
        rs = row.get("raid_size")
        if rs is None:
            return True
        if size_mode == 1:
            return rs <= 15
        return rs > 15

    def _compute_spell_deltas(self, spell_trend, size_mode, value_key):
        by_raid: dict[str, dict[str, dict]] = defaultdict(dict)
        for row in spell_trend:
            if not self._matches_size(row, size_mode):
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

    def _compute_consumable_deltas(self, con_trend, size_mode):
        by_raid: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in con_trend:
            if not self._matches_size(row, size_mode):
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

    def _build_summary_section(self, raid_stats, historical, size_label):
        section = QWidget()
        section.setStyleSheet(f"background-color: {COLORS['bg_card']}; border-radius: 8px;")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(20, 16, 20, 16)

        info_label = QLabel(
            f"<b>{raid_stats['title']}</b> &nbsp;|&nbsp; {raid_stats.get('raid_date', '')[:10]}"
            f" &nbsp;|&nbsp; {size_label} &nbsp;|&nbsp; Duration: {_fmt_duration(raid_stats['duration_ms'])}"
        )
        info_label.setFont(QFont("Segoe UI", 11))
        info_label.setStyleSheet(f"color: {COLORS['text']};")
        section_layout.addWidget(info_label)

        num_comparison = len(historical)
        compare_label = QLabel(f"Compared against {num_comparison} other {size_label} raids")
        compare_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        section_layout.addWidget(compare_label)

        if not historical:
            no_data = QLabel("No historical raids of this size to compare against.")
            no_data.setStyleSheet(f"color: {COLORS['warning']}; font-size: 12px; padding: 8px;")
            section_layout.addWidget(no_data)
            self._content_layout.addWidget(section)
            return

        avg_duration = sum(h["duration_ms"] for h in historical) / len(historical)
        avg_damage = sum(h["total_damage"] for h in historical) / len(historical)
        avg_healing = sum(h["total_healing"] for h in historical) / len(historical)
        avg_taken = sum(h["total_damage_taken"] for h in historical) / len(historical)

        cards_layout = QGridLayout()
        cards_layout.setSpacing(12)

        duration_down = raid_stats["duration_ms"] < avg_duration

        cards = [
            ("Duration", _fmt_duration(raid_stats["duration_ms"]),
             _fmt_duration(avg_duration),
             _pct_change(raid_stats["duration_ms"], avg_duration), True),
            ("Total Damage", _fmt_number(raid_stats["total_damage"]),
             _fmt_number(avg_damage),
             _pct_change(raid_stats["total_damage"], avg_damage), duration_down),
            ("Total Healing", _fmt_number(raid_stats["total_healing"]),
             _fmt_number(avg_healing),
             _pct_change(raid_stats["total_healing"], avg_healing), duration_down),
            ("Damage Taken", _fmt_number(raid_stats["total_damage_taken"]),
             _fmt_number(avg_taken),
             _pct_change(raid_stats["total_damage_taken"], avg_taken), True),
        ]

        for i, (label, this_val, avg_val, pct, invert) in enumerate(cards):
            card = self._make_summary_card(label, this_val, avg_val, pct, invert)
            cards_layout.addWidget(card, 0, i)

        section_layout.addLayout(cards_layout)
        self._content_layout.addWidget(section)

    def _make_summary_card(self, title, this_val, avg_val, pct_change, invert):
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

        delta_text, delta_color = _delta_label(pct_change, invert)
        delta_lbl = QLabel(f"{delta_text}  vs avg {avg_val}")
        delta_lbl.setFont(QFont("Segoe UI", 10))
        delta_lbl.setStyleSheet(f"color: {delta_color}; border: none;")
        card_layout.addWidget(delta_lbl)

        return card

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
            chart_grid.addWidget(chart_view, i // 2, i % 2)

        chart_wrapper = QWidget()
        chart_wrapper.setLayout(chart_grid)
        self._content_layout.addWidget(chart_wrapper)

    def _build_player_sections(self, player_deltas):
        roles = [
            ("Healers", "healer"),
            ("Tanks", "tank"),
            ("Melee DPS", "melee"),
            ("Ranged DPS", "ranged"),
        ]

        for role_label, role_key in roles:
            players = [p for p in player_deltas if p["role"] == role_key]
            if not players:
                continue

            section_label = QLabel(role_label)
            section_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
            section_label.setStyleSheet(f"color: {COLORS['text_header']}; margin-top: 8px;")
            self._content_layout.addWidget(section_label)

            for p in sorted(players, key=lambda x: x["name"]):
                self._build_player_card(p)

    def _build_player_card(self, delta):
        card = QWidget()
        card.setObjectName("playerCard")
        card.setStyleSheet(f"""
            QWidget#playerCard {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
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
        name_label = QLabel(f"{delta['name']}  ({delta['player_class']})")
        name_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        name_label.setStyleSheet(f"color: {COLORS['accent']};")
        header_layout.addWidget(name_label)

        primary_pct = self._get_primary_pct(delta)
        if primary_pct is not None:
            invert = delta["role"] == "tank"
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
        detail_widget.setStyleSheet(f"background-color: transparent;")
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 8, 0, 0)
        detail_layout.setSpacing(8)
        detail_widget.setVisible(False)

        def toggle():
            visible = not detail_widget.isVisible()
            detail_widget.setVisible(visible)
            toggle_btn.setText("Hide Details" if visible else "Show Details")

        toggle_btn.clicked.connect(toggle)

        self._add_metrics_table(detail_layout, delta)

        if delta.get("spell_deltas"):
            self._add_spell_table(detail_layout, delta["spell_deltas"])

        if delta.get("consumable_deltas"):
            self._add_consumable_table(detail_layout, delta["consumable_deltas"])

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

    def _add_metrics_table(self, parent_layout, delta):
        metrics = delta["metrics"]
        role = delta["role"]

        label = QLabel("Performance Metrics")
        label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
        parent_layout.addWidget(label)

        grid = QGridLayout()
        grid.setSpacing(4)

        headers = ["Metric", "This Raid", "Personal Avg", "Change"]
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
            grid.addWidget(lbl, 0, col)

        row = 1
        if role == "healer":
            row = self._metric_row(grid, row, "Total Healing",
                                   _fmt_number(metrics.get("total_healing")),
                                   _fmt_number(metrics.get("avg_healing")),
                                   metrics.get("healing_pct"), False)
            row = self._metric_row(grid, row, "Overheal %",
                                   f"{metrics.get('overheal_percent', 0):.1f}%",
                                   f"{metrics.get('avg_overheal', 0):.1f}%"
                                   if metrics.get("avg_overheal") is not None else "N/A",
                                   None, True)
        elif role == "tank":
            row = self._metric_row(grid, row, "Damage Taken",
                                   _fmt_number(metrics.get("total_damage_taken")),
                                   _fmt_number(metrics.get("avg_damage_taken")),
                                   metrics.get("taken_pct"), True)
            row = self._metric_row(grid, row, "Mitigation %",
                                   f"{metrics.get('mitigation_percent', 0):.1f}%",
                                   f"{metrics.get('avg_mitigation', 0):.1f}%"
                                   if metrics.get("avg_mitigation") is not None else "N/A",
                                   metrics.get("mitigation_pct"), False)
        else:
            row = self._metric_row(grid, row, "Total Damage",
                                   _fmt_number(metrics.get("total_damage")),
                                   _fmt_number(metrics.get("avg_damage")),
                                   metrics.get("damage_pct"), False)

        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        wrapper.setLayout(grid)
        parent_layout.addWidget(wrapper)

    def _metric_row(self, grid, row, name, this_val, avg_val, pct, invert):
        grid.addWidget(QLabel(name), row, 0)
        grid.addWidget(QLabel(str(this_val)), row, 1)
        grid.addWidget(QLabel(str(avg_val)), row, 2)
        if pct is not None:
            delta_text, delta_color = _delta_label(pct, invert)
            lbl = QLabel(delta_text)
            lbl.setStyleSheet(f"color: {delta_color}; background: transparent;")
            grid.addWidget(lbl, row, 3)
        else:
            grid.addWidget(QLabel("—"), row, 3)
        return row + 1

    def _add_spell_table(self, parent_layout, spell_deltas):
        label = QLabel("Spell / Ability Changes")
        label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        label.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
        parent_layout.addWidget(label)

        grid = QGridLayout()
        grid.setSpacing(4)

        headers = ["Spell", "Casts (This)", "Avg Casts", "Cast Delta"]
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
            grid.addWidget(lbl, 0, col)

        for i, s in enumerate(spell_deltas[:10]):
            row = i + 1
            grid.addWidget(QLabel(s["spell_name"]), row, 0)
            grid.addWidget(QLabel(str(s["this_casts"])), row, 1)
            grid.addWidget(QLabel(f"{s['avg_casts']:.1f}"), row, 2)
            d = s["cast_delta"]
            if d > 0:
                delta_lbl = QLabel(f"+{d:.0f}")
                delta_lbl.setStyleSheet(f"color: {COLORS['success']}; background: transparent;")
            elif d < 0:
                delta_lbl = QLabel(f"{d:.0f}")
                delta_lbl.setStyleSheet(f"color: {COLORS['error']}; background: transparent;")
            else:
                delta_lbl = QLabel("—")
                delta_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
            grid.addWidget(delta_lbl, row, 3)

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
        grid.setSpacing(4)

        headers = ["Consumable", "Count (This)", "Avg Count", "Delta"]
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
            grid.addWidget(lbl, 0, col)

        for i, c in enumerate(consumable_deltas[:10]):
            row = i + 1
            grid.addWidget(QLabel(c["consumable_name"]), row, 0)
            grid.addWidget(QLabel(str(c["this_count"])), row, 1)
            grid.addWidget(QLabel(f"{c['avg_count']:.1f}"), row, 2)
            d = c["delta"]
            if d > 0.5:
                delta_lbl = QLabel(f"+{d:.0f}")
                delta_lbl.setStyleSheet(f"color: {COLORS['success']}; background: transparent;")
            elif d < -0.5:
                delta_lbl = QLabel(f"{d:.0f}")
                delta_lbl.setStyleSheet(f"color: {COLORS['error']}; background: transparent;")
            else:
                delta_lbl = QLabel("—")
                delta_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
            grid.addWidget(delta_lbl, row, 3)

        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        wrapper.setLayout(grid)
        parent_layout.addWidget(wrapper)

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
