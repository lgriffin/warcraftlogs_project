"""
Raid-to-Raid comparison view for comparing two guild raids side-by-side.
"""

import sqlite3
from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..database import PerformanceDB
from .styles import COLORS, COMMON_STYLES


class _MetricCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background-color: {COLORS['bg_card']};"
            f" border: 1px solid {COLORS['border']};"
            f" border-radius: 6px; padding: 12px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Segoe UI", 9))
        title_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; border: none;")
        layout.addWidget(title_lbl)

        self._raid_a_lbl = QLabel("Raid A: —")
        self._raid_a_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._raid_a_lbl.setStyleSheet(f"color: {COLORS['accent']}; border: none;")
        layout.addWidget(self._raid_a_lbl)

        self._raid_b_lbl = QLabel("Raid B: —")
        self._raid_b_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._raid_b_lbl.setStyleSheet("color: #69CCF0; border: none;")
        layout.addWidget(self._raid_b_lbl)

        self._delta_lbl = QLabel()
        self._delta_lbl.setFont(QFont("Segoe UI", 10))
        self._delta_lbl.setStyleSheet(f"color: {COLORS['text_dim']}; border: none;")
        layout.addWidget(self._delta_lbl)

    def set_values(self, val_a, val_b, higher_is_better=True, fmt="{:,.0f}"):
        self._raid_a_lbl.setText(f"Raid A: {fmt.format(val_a)}" if val_a is not None else "Raid A: —")
        self._raid_b_lbl.setText(f"Raid B: {fmt.format(val_b)}" if val_b is not None else "Raid B: —")
        if val_a is not None and val_b is not None and val_b != 0:
            delta_pct = (val_a - val_b) / abs(val_b) * 100
            sign = "+" if delta_pct > 0 else ""
            if higher_is_better:
                is_better = delta_pct > 0
            else:
                is_better = delta_pct < 0
            color = COLORS["success"] if is_better else COLORS["error"]
            self._delta_lbl.setText(f"{sign}{delta_pct:.1f}%")
            self._delta_lbl.setStyleSheet(f"color: {color}; border: none;")


class RaidDiffView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shown = False
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(COMMON_STYLES)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Raid-to-Raid Comparison")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(title)

        desc = QLabel("Compare two guild raids side-by-side to track progression between raid nights.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        layout.addWidget(desc)

        selector_row = QHBoxLayout()
        selector_row.setSpacing(10)

        selector_row.addWidget(QLabel("Raid A:"))
        self._combo_a = QComboBox()
        self._combo_a.setMinimumWidth(300)
        selector_row.addWidget(self._combo_a, 1)

        vs_label = QLabel("vs")
        vs_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        vs_label.setStyleSheet(f"color: {COLORS['accent']};")
        selector_row.addWidget(vs_label)

        selector_row.addWidget(QLabel("Raid B:"))
        self._combo_b = QComboBox()
        self._combo_b.setMinimumWidth(300)
        selector_row.addWidget(self._combo_b, 1)

        self._compare_btn = QPushButton("Compare")
        self._compare_btn.setFixedHeight(36)
        self._compare_btn.clicked.connect(self._run_comparison)
        selector_row.addWidget(self._compare_btn)

        layout.addLayout(selector_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {COLORS['bg_dark']}; }}"
        )
        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(16)

        placeholder = QLabel("Select two raids and click Compare.")
        placeholder.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 13px;")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(placeholder)
        self._content_layout.addStretch()

        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            self._populate_combos()
        else:
            self._populate_combos()

    def _populate_combos(self):
        try:
            with PerformanceDB() as db:
                raids = db.get_guild_raids_for_comparison()
        except (sqlite3.Error, OSError):
            raids = []

        for combo in (self._combo_a, self._combo_b):
            combo.blockSignals(True)
            current = combo.currentData(Qt.ItemDataRole.UserRole)
            combo.clear()
            for r in raids:
                parts = [r.get("raid_date", "")[:10], r.get("title", "")]
                if r.get("zone"):
                    parts.append(r["zone"])
                if r.get("raid_size"):
                    parts.append(f"{r['raid_size']}-man")
                display = " — ".join(parts[:2])
                if len(parts) > 2:
                    display += f" ({', '.join(parts[2:])})"
                combo.addItem(display, r["report_id"])
            if current:
                idx = combo.findData(current, Qt.ItemDataRole.UserRole)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        if len(raids) >= 2 and self._combo_b.count() >= 2:
            self._combo_b.setCurrentIndex(1)

        self._compare_btn.setEnabled(self._combo_a.count() >= 2)

    def _run_comparison(self):
        id_a = self._combo_a.currentData(Qt.ItemDataRole.UserRole)
        id_b = self._combo_b.currentData(Qt.ItemDataRole.UserRole)
        if not id_a or not id_b:
            return
        if id_a == id_b:
            QMessageBox.warning(self, "Same Raid", "Please select two different raids to compare.")
            return

        try:
            with PerformanceDB() as db:
                analysis_a = db.get_raid_analysis(id_a)
                analysis_b = db.get_raid_analysis(id_b)
                stats_a = db.get_raid_aggregate_stats(id_a)
                stats_b = db.get_raid_aggregate_stats(id_b)
        except (sqlite3.Error, OSError) as e:
            QMessageBox.warning(self, "Error", f"Failed to load raid data:\n{e}")
            return

        if not analysis_a or not analysis_b:
            QMessageBox.warning(self, "Error", "Could not load one or both raids.")
            return

        self._display_comparison(analysis_a, analysis_b, stats_a or {}, stats_b or {})
        self.status_message.emit(
            f"Comparing '{analysis_a.metadata.title}' vs '{analysis_b.metadata.title}'"
        )

    def _clear_content(self):
        old = self._scroll.takeWidget()
        if old:
            old.deleteLater()
        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(16)

    def _add_section_header(self, layout, text):
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {COLORS['text_header']};"
            f" border-bottom: 2px solid {COLORS['accent']};"
            f" padding-bottom: 6px;"
        )
        if isinstance(layout, QVBoxLayout):
            layout.addWidget(lbl)
        else:
            layout.addWidget(lbl)

    def _display_comparison(self, raid_a, raid_b, stats_a, stats_b):
        self._clear_content()
        layout = self._content_layout

        # ── Raid Overview ──
        self._add_section_header(layout, "Raid Overview")
        cards = QGridLayout()
        cards.setSpacing(12)

        dur_card = _MetricCard("Duration")
        g_dur = stats_a.get("duration_ms")
        r_dur = stats_b.get("duration_ms")
        if g_dur is not None:
            dur_card._raid_a_lbl.setText(f"Raid A: {int(g_dur / 1000) // 60}:{int(g_dur / 1000) % 60:02d}")
        if r_dur is not None:
            dur_card._raid_b_lbl.setText(f"Raid B: {int(r_dur / 1000) // 60}:{int(r_dur / 1000) % 60:02d}")
        if g_dur and r_dur and r_dur != 0:
            delta_pct = (g_dur - r_dur) / abs(r_dur) * 100
            sign = "+" if delta_pct > 0 else ""
            color = COLORS["success"] if delta_pct < 0 else COLORS["error"]
            dur_card._delta_lbl.setText(f"{sign}{delta_pct:.1f}%")
            dur_card._delta_lbl.setStyleSheet(f"color: {color}; border: none;")

        dmg_card = _MetricCard("Total Damage")
        dmg_card.set_values(stats_a.get("total_damage"), stats_b.get("total_damage"))

        heal_card = _MetricCard("Total Healing")
        heal_card.set_values(stats_a.get("total_healing"), stats_b.get("total_healing"))

        size_card = _MetricCard("Raid Size")
        size_card.set_values(stats_a.get("raid_size"), stats_b.get("raid_size"), fmt="{:.0f}")

        taken_card = _MetricCard("Damage Taken")
        taken_card.set_values(
            stats_a.get("total_damage_taken"),
            stats_b.get("total_damage_taken"),
            higher_is_better=False,
        )

        dps_a = len(raid_a.dps) or 1
        dps_b = len(raid_b.dps) or 1
        avg_a = stats_a.get("total_damage", 0) / dps_a if stats_a.get("total_damage") else None
        avg_b = stats_b.get("total_damage", 0) / dps_b if stats_b.get("total_damage") else None
        avg_card = _MetricCard("Avg DPS per Player")
        avg_card.set_values(avg_a, avg_b)

        cards.addWidget(dur_card, 0, 0)
        cards.addWidget(dmg_card, 0, 1)
        cards.addWidget(heal_card, 0, 2)
        cards.addWidget(size_card, 1, 0)
        cards.addWidget(taken_card, 1, 1)
        cards.addWidget(avg_card, 1, 2)
        layout.addLayout(cards)

        # ── Composition ──
        self._add_section_header(layout, "Raid Composition")
        comp_grid = QGridLayout()
        comp_grid.setSpacing(6)

        a_classes = defaultdict(int)
        for p in raid_a.composition.all_players:
            a_classes[p.player_class] += 1
        b_classes = defaultdict(int)
        for p in raid_b.composition.all_players:
            b_classes[p.player_class] += 1
        all_classes = sorted(set(a_classes.keys()) | set(b_classes.keys()))

        for col, header in enumerate(["Class", "Raid A", "Raid B", "Delta"]):
            lbl = QLabel(header)
            lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLORS['text_dim']};")
            comp_grid.addWidget(lbl, 0, col)

        for i, cls in enumerate(all_classes, start=1):
            ac = a_classes.get(cls, 0)
            bc = b_classes.get(cls, 0)
            delta = ac - bc

            comp_grid.addWidget(self._styled_label(cls, COLORS["text"]), i, 0)
            comp_grid.addWidget(self._styled_label(str(ac), COLORS["accent"]), i, 1)
            comp_grid.addWidget(self._styled_label(str(bc), "#69CCF0"), i, 2)

            sign = "+" if delta > 0 else ""
            d_color = COLORS["success"] if delta > 0 else (COLORS["error"] if delta < 0 else COLORS["text_dim"])
            comp_grid.addWidget(
                self._styled_label(f"{sign}{delta}" if delta != 0 else "=", d_color), i, 3
            )

        layout.addLayout(comp_grid)

        # ── Consumable comparison ──
        self._add_section_header(layout, "Consumable Usage")
        a_cons = self._compute_consumable_summary(raid_a)
        b_cons = self._compute_consumable_summary(raid_b)
        all_consumables = sorted(set(a_cons.keys()) | set(b_cons.keys()))

        if all_consumables:
            cons_grid = QGridLayout()
            cons_grid.setSpacing(6)
            for col, header in enumerate(["Consumable", "A Uses", "A Users", "B Uses", "B Users", "Delta"]):
                lbl = QLabel(header)
                lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                lbl.setStyleSheet(f"color: {COLORS['text_dim']};")
                cons_grid.addWidget(lbl, 0, col)

            for i, name in enumerate(all_consumables, start=1):
                ac = a_cons.get(name, {})
                bc = b_cons.get(name, {})
                a_uses = ac.get("total_uses", 0)
                b_uses = bc.get("total_uses", 0)
                delta = a_uses - b_uses

                cons_grid.addWidget(self._styled_label(name, COLORS["text"]), i, 0)
                cons_grid.addWidget(self._styled_label(str(a_uses), COLORS["accent"]), i, 1)
                cons_grid.addWidget(self._styled_label(str(ac.get("unique_users", 0)), COLORS["text_dim"]), i, 2)
                cons_grid.addWidget(self._styled_label(str(b_uses), "#69CCF0"), i, 3)
                cons_grid.addWidget(self._styled_label(str(bc.get("unique_users", 0)), COLORS["text_dim"]), i, 4)

                sign = "+" if delta > 0 else ""
                d_color = COLORS["success"] if delta > 0 else (COLORS["error"] if delta < 0 else COLORS["text_dim"])
                cons_grid.addWidget(
                    self._styled_label(f"{sign}{delta}" if delta != 0 else "=", d_color), i, 5
                )
            layout.addLayout(cons_grid)
        else:
            layout.addWidget(self._styled_label("No consumable data available.", COLORS["text_dim"]))

        # ── Interrupt comparison ──
        a_ints = self._compute_interrupt_summary(raid_a)
        b_ints = self._compute_interrupt_summary(raid_b)
        if a_ints or b_ints:
            self._add_section_header(layout, "Interrupt Usage")
            int_grid = QGridLayout()
            int_grid.setSpacing(6)
            all_spells = sorted(set(a_ints.keys()) | set(b_ints.keys()))

            for col, header in enumerate(["Interrupt", "Raid A", "Raid B", "Delta"]):
                lbl = QLabel(header)
                lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                lbl.setStyleSheet(f"color: {COLORS['text_dim']};")
                int_grid.addWidget(lbl, 0, col)

            for i, spell in enumerate(all_spells, start=1):
                a_count = a_ints.get(spell, 0)
                b_count = b_ints.get(spell, 0)
                delta = a_count - b_count

                int_grid.addWidget(self._styled_label(spell, COLORS["text"]), i, 0)
                int_grid.addWidget(self._styled_label(str(a_count), COLORS["accent"]), i, 1)
                int_grid.addWidget(self._styled_label(str(b_count), "#69CCF0"), i, 2)

                sign = "+" if delta > 0 else ""
                d_color = COLORS["success"] if delta > 0 else (COLORS["error"] if delta < 0 else COLORS["text_dim"])
                int_grid.addWidget(
                    self._styled_label(f"{sign}{delta}" if delta != 0 else "=", d_color), i, 3
                )
            layout.addLayout(int_grid)

        # ── Encounter comparison ──
        a_encs = {e.name: e for e in raid_a.encounters}
        b_encs = {e.name: e for e in raid_b.encounters}
        shared_bosses = sorted(set(a_encs.keys()) & set(b_encs.keys()))

        if shared_bosses:
            self._add_section_header(layout, "Shared Boss Encounters")
            enc_grid = QGridLayout()
            enc_grid.setSpacing(6)
            for col, header in enumerate(["Boss", "A Duration", "B Duration", "A Damage", "B Damage", "Delta"]):
                lbl = QLabel(header)
                lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
                lbl.setStyleSheet(f"color: {COLORS['text_dim']};")
                enc_grid.addWidget(lbl, 0, col)

            for i, boss in enumerate(shared_bosses, start=1):
                ea = a_encs[boss]
                eb = b_encs[boss]
                dur_a_s = ea.duration_ms // 1000
                dur_b_s = eb.duration_ms // 1000
                dmg_a = sum(p.total_damage for p in ea.players)
                dmg_b = sum(p.total_damage for p in eb.players)

                enc_grid.addWidget(self._styled_label(boss, COLORS["text"]), i, 0)
                enc_grid.addWidget(
                    self._styled_label(f"{dur_a_s // 60}:{dur_a_s % 60:02d}", COLORS["accent"]), i, 1
                )
                enc_grid.addWidget(
                    self._styled_label(f"{dur_b_s // 60}:{dur_b_s % 60:02d}", "#69CCF0"), i, 2
                )
                enc_grid.addWidget(self._styled_label(f"{dmg_a:,}", COLORS["accent"]), i, 3)
                enc_grid.addWidget(self._styled_label(f"{dmg_b:,}", "#69CCF0"), i, 4)

                if dmg_b > 0:
                    delta_pct = (dmg_a - dmg_b) / dmg_b * 100
                    sign = "+" if delta_pct > 0 else ""
                    color = COLORS["success"] if delta_pct > 0 else COLORS["error"]
                    enc_grid.addWidget(self._styled_label(f"{sign}{delta_pct:.1f}%", color), i, 5)
                else:
                    enc_grid.addWidget(self._styled_label("—", COLORS["text_dim"]), i, 5)

            layout.addLayout(enc_grid)

        layout.addStretch()
        self._scroll.setWidget(self._content)

    def _styled_label(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color};")
        return lbl

    @staticmethod
    def _compute_consumable_summary(analysis):
        summary = {}
        for c in analysis.consumables:
            if c.consumable_name not in summary:
                summary[c.consumable_name] = {"total_uses": 0, "unique_users": 0, "users": set()}
            summary[c.consumable_name]["total_uses"] += c.count
            summary[c.consumable_name]["users"].add(c.player_name)
        for v in summary.values():
            v["unique_users"] = len(v["users"])
            del v["users"]
        return summary

    @staticmethod
    def _compute_interrupt_summary(analysis):
        summary = defaultdict(int)
        for iu in analysis.interrupts:
            summary[iu.spell_name] += iu.count
        return dict(summary)
