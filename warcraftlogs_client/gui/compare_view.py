"""
Character Comparison view — select 2-5 characters and compare stats
with an overlaid radar chart, cast breakdown, and raid-size filtering.
"""

import sqlite3
from collections import defaultdict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableView, QHeaderView, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QFont, QColor

from .styles import COMMON_STYLES, COLORS
from .charts import ComparisonSpiderChart, SERIES_COLORS
from ..database import PerformanceDB

MAX_CHARACTERS = 5

CLASS_COLORS = {
    "Warrior": "#C79C6E",
    "Paladin": "#F58CBA",
    "Priest": "#FFFFFF",
    "Shaman": "#0070DE",
    "Druid": "#FF7D0A",
    "Rogue": "#FFF569",
    "Mage": "#69CCF0",
    "Warlock": "#9482C9",
    "Hunter": "#ABD473",
    "Death Knight": "#C41E3A",
}


ROLE_METRIC_KEYS = {
    "Healer": {"avg_healing"},
    "DPS": {"avg_damage"},
    "Tank": {"avg_mitigation"},
}

ROLE_SPECIFIC_KEYS = {"avg_healing", "avg_damage", "avg_mitigation"}


class _ComparisonTableModel(QAbstractTableModel):
    ROWS = [
        "Role", "Raids Tracked", "Avg Healing", "Avg Damage",
        "Avg Mitigation%", "Avg Active Time%", "Total Consumables", "Consistency",
    ]
    ROW_KEYS = [
        "role", "total_raids", "avg_healing", "avg_damage",
        "avg_mitigation", "avg_active_time", "total_consumables", "consistency",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._names: list[str] = []
        self._data: dict[str, dict] = {}

    def set_data(self, names: list[str], data: dict[str, dict]):
        self.beginResetModel()
        self._names = list(names)
        self._data = data
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.ROWS)

    def columnCount(self, parent=QModelIndex()):
        return 1 + len(self._names)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if section == 0:
                return "Metric"
            return self._names[section - 1]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        key = self.ROW_KEYS[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return self.ROWS[row]
            name = self._names[col - 1]
            char_data = self._data.get(name, {})

            if key in ROLE_SPECIFIC_KEYS:
                char_role = char_data.get("role", "")
                allowed = ROLE_METRIC_KEYS.get(char_role, set())
                if key not in allowed:
                    return "-"

            val = char_data.get(key)
            if val is None:
                return "-"
            if isinstance(val, float):
                return f"{val:,.1f}"
            if isinstance(val, int) and val > 9999:
                return f"{val:,}"
            return str(val)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 0:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if col > 0:
                idx = col - 1
                return SERIES_COLORS[idx % len(SERIES_COLORS)]

        if role == Qt.ItemDataRole.FontRole:
            if col > 0:
                font = QFont()
                font.setBold(True)
                return font

        return None


class _CastTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._names: list[str] = []
        self._spells: list[str] = []
        self._data: dict[str, dict[str, dict]] = {}

    def set_data(self, names: list[str],
                 data: dict[str, dict[str, dict]],
                 spells: list[str]):
        self.beginResetModel()
        self._names = list(names)
        self._spells = list(spells)
        self._data = data
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._spells)

    def columnCount(self, parent=QModelIndex()):
        return 1 + len(self._names)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if section == 0:
                return "Spell / Ability"
            return self._names[section - 1]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return self._spells[row]
            name = self._names[col - 1]
            spell = self._spells[row]
            entry = self._data.get(name, {}).get(spell)
            if not entry:
                return "-"
            avg_casts = entry["avg_casts"]
            avg_val = entry["avg_value"]
            label = entry.get("label", "dmg")
            if avg_val >= 1_000_000:
                val_str = f"{avg_val / 1_000_000:.1f}M"
            elif avg_val >= 1_000:
                val_str = f"{avg_val / 1_000:.0f}K"
            else:
                val_str = f"{avg_val:.0f}"
            return f"{avg_casts:.0f} casts / {val_str} {label}"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 0:
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if col > 0:
                idx = col - 1
                return SERIES_COLORS[idx % len(SERIES_COLORS)]

        if role == Qt.ItemDataRole.FontRole:
            if col == 0:
                font = QFont()
                font.setBold(True)
                return font

        return None


class CompareView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected: list[str] = []
        self._char_stats: dict[str, dict] = {}
        self._spider_data: dict[str, dict] = {}
        self._all_characters: list = []
        self._chip_widgets: dict[str, QWidget] = {}
        self._raw_healer_trends: dict[str, list[dict]] = {}
        self._raw_dps_trends: dict[str, list[dict]] = {}
        self._raw_tank_trends: dict[str, list[dict]] = {}
        self._raw_healer_spells: dict[str, list[dict]] = {}
        self._raw_dps_abilities: dict[str, list[dict]] = {}
        self._raw_consumable_trends: dict[str, list[dict]] = {}
        self._cached_consistency: dict[str, dict | None] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.setStyleSheet(COMMON_STYLES)

        title = QLabel("Character Comparison")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(title)

        picker_row = QHBoxLayout()
        picker_row.setSpacing(8)

        self._toggle_btn = QPushButton("<< Characters")
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_dark']};
                border-color: {COLORS['accent']};
            }}
        """)
        self._toggle_btn.clicked.connect(self._toggle_selector)
        picker_row.addWidget(self._toggle_btn)

        filter_label = QLabel("Class:")
        filter_label.setStyleSheet(f"color: {COLORS['text']};")
        picker_row.addWidget(filter_label)

        self._class_filter = QComboBox()
        self._class_filter.setMinimumWidth(140)
        self._class_filter.addItem("All Classes")
        self._class_filter.currentTextChanged.connect(self._apply_filter)
        combo_style = f"""
            QComboBox {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 10px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                selection-background-color: {COLORS['bg_dark']};
                border: 1px solid {COLORS['border']};
            }}
        """
        self._class_filter.setStyleSheet(combo_style)
        picker_row.addWidget(self._class_filter)

        size_label = QLabel("Raid Size:")
        size_label.setStyleSheet(f"color: {COLORS['text']};")
        picker_row.addWidget(size_label)

        self._raid_size_filter = QComboBox()
        self._raid_size_filter.setMinimumWidth(130)
        self._raid_size_filter.addItems(["All Raids", "10-man", "25-man"])
        self._raid_size_filter.currentIndexChanged.connect(self._on_raid_size_changed)
        self._raid_size_filter.setStyleSheet(combo_style)
        picker_row.addWidget(self._raid_size_filter)

        picker_row.addStretch()
        layout.addLayout(picker_row)

        self._chips_layout = QHBoxLayout()
        self._chips_layout.setSpacing(6)
        self._chips_layout.addStretch()
        layout.addLayout(self._chips_layout)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        self._selector_panel = QWidget()
        self._selector_panel.setFixedWidth(260)
        selector_layout = QVBoxLayout(self._selector_panel)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(6)

        list_label = QLabel("Select characters (max 5):")
        list_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        selector_layout.addWidget(list_label)

        self._char_list = QListWidget()
        self._char_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 6px 10px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_dark']};
            }}
        """)
        self._char_list.itemChanged.connect(self._on_item_toggled)
        selector_layout.addWidget(self._char_list)

        content_row.addWidget(self._selector_panel)

        right_panel = QVBoxLayout()
        right_panel.setSpacing(12)

        table_style = f"""
            QTableView {{
                alternate-background-color: {COLORS['bg_dark']};
                gridline-color: {COLORS['border']};
                font-size: 13px;
            }}
            QHeaderView::section {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_header']};
                border: 1px solid {COLORS['border']};
                padding: 6px 8px;
                font-weight: bold;
                font-size: 13px;
            }}
        """

        self._table_model = _ComparisonTableModel()
        self._table = QTableView()
        self._table.setModel(self._table_model)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(160)
        self._table.setStyleSheet(table_style)
        right_panel.addWidget(self._table)

        cast_label = QLabel("Cast / Ability Comparison")
        cast_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        cast_label.setStyleSheet(f"color: {COLORS['text_header']};")
        right_panel.addWidget(cast_label)

        self._cast_model = _CastTableModel()
        self._cast_table = QTableView()
        self._cast_table.setModel(self._cast_model)
        self._cast_table.setAlternatingRowColors(True)
        self._cast_table.verticalHeader().setVisible(False)
        self._cast_table.verticalHeader().setDefaultSectionSize(30)
        self._cast_table.horizontalHeader().setStretchLastSection(False)
        self._cast_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._cast_table.setMinimumHeight(160)
        self._cast_table.setStyleSheet(table_style)
        right_panel.addWidget(self._cast_table)

        self._spider = ComparisonSpiderChart()
        self._spider.character_removed.connect(self._remove_character)
        right_panel.addWidget(self._spider, 1)

        content_row.addLayout(right_panel, 1)
        layout.addLayout(content_row, 1)

    def _toggle_selector(self):
        visible = self._selector_panel.isVisible()
        self._selector_panel.setVisible(not visible)
        if visible:
            self._toggle_btn.setText("Characters >>")
        else:
            self._toggle_btn.setText("<< Characters")

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_character_list()

    def _refresh_character_list(self):
        try:
            with PerformanceDB() as db:
                self._all_characters = db.get_all_characters()
        except (sqlite3.Error, OSError):
            self._all_characters = []

        classes = sorted({ch.player_class for ch in self._all_characters})
        current_filter = self._class_filter.currentText()
        self._class_filter.blockSignals(True)
        self._class_filter.clear()
        self._class_filter.addItem("All Classes")
        for cls in classes:
            self._class_filter.addItem(cls)
        idx = self._class_filter.findText(current_filter)
        self._class_filter.setCurrentIndex(max(0, idx))
        self._class_filter.blockSignals(False)

        self._apply_filter()

    def _apply_filter(self):
        cls_filter = self._class_filter.currentText()
        self._char_list.blockSignals(True)
        self._char_list.clear()

        for ch in self._all_characters:
            if cls_filter != "All Classes" and ch.player_class != cls_filter:
                continue
            item = QListWidgetItem(f"{ch.name}  ({ch.player_class})")
            item.setData(Qt.ItemDataRole.UserRole, ch.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if ch.name in self._selected
                else Qt.CheckState.Unchecked)
            class_color = CLASS_COLORS.get(ch.player_class, "#eeeeee")
            item.setForeground(QColor(class_color))
            self._char_list.addItem(item)

        self._char_list.blockSignals(False)

    def _on_item_toggled(self, item: QListWidgetItem):
        name = item.data(Qt.ItemDataRole.UserRole)
        checked = item.checkState() == Qt.CheckState.Checked

        if checked:
            if name in self._selected:
                return
            if len(self._selected) >= MAX_CHARACTERS:
                self._char_list.blockSignals(True)
                item.setCheckState(Qt.CheckState.Unchecked)
                self._char_list.blockSignals(False)
                self.status_message.emit(f"Maximum {MAX_CHARACTERS} characters")
                return
            self._load_and_add(name)
        else:
            if name in self._selected:
                self._remove_character(name)

    def _load_and_add(self, name: str):
        try:
            with PerformanceDB() as db:
                history = db.get_character_history(name)
                consistency = db.get_character_consistency(name)
                spider = db.get_character_spider_data(name)
                healer_trends = db.get_healer_trend(name)
                dps_trends = db.get_dps_trend(name)
                tank_trends = db.get_tank_trend(name)
                healer_spells = db.get_healer_spell_trend(name)
                dps_abilities = db.get_dps_ability_trend(name)
                consumable_trends = db.get_consumable_trend(name)
        except (sqlite3.Error, OSError) as e:
            self.status_message.emit(f"Failed to load {name}: {e}")
            return

        if not history:
            self.status_message.emit(f"No data found for {name}")
            return

        self._raw_healer_trends[name] = healer_trends
        self._raw_dps_trends[name] = dps_trends
        self._raw_tank_trends[name] = tank_trends
        self._raw_healer_spells[name] = healer_spells
        self._raw_dps_abilities[name] = dps_abilities
        self._raw_consumable_trends[name] = consumable_trends
        self._cached_consistency[name] = consistency

        mode = self._raid_size_filter.currentIndex()
        stats = self._compute_stats_from_trends(
            name,
            self._filter_by_raid_size(healer_trends, mode),
            self._filter_by_raid_size(dps_trends, mode),
            self._filter_by_raid_size(tank_trends, mode),
            self._filter_by_raid_size(consumable_trends, mode),
        )

        self._selected.append(name)
        self._char_stats[name] = stats
        self._spider_data[name] = spider or {}

        self._add_chip(name)
        self._refresh_display()
        self.status_message.emit(f"Added {name} to comparison")

    @staticmethod
    def _filter_by_raid_size(rows: list[dict], mode: int) -> list[dict]:
        if mode == 0:
            return rows
        if mode == 1:
            return [r for r in rows if r.get("raid_size") is not None and r["raid_size"] <= 15]
        return [r for r in rows if r.get("raid_size") is not None and r["raid_size"] > 15]

    def _infer_role(self, healer_trends, dps_trends, tank_trends) -> str:
        counts = [
            (len(healer_trends), "Healer"),
            (len(dps_trends), "DPS"),
            (len(tank_trends), "Tank"),
        ]
        counts.sort(key=lambda x: x[0], reverse=True)
        return counts[0][1] if counts[0][0] > 0 else "DPS"

    def _compute_stats_from_trends(self, name,
                                   healer_trends, dps_trends, tank_trends,
                                   consumable_trends=None):
        raid_dates = set()
        avg_healing = None
        avg_damage = None
        avg_mitigation = None

        if healer_trends:
            raid_dates.update(r["raid_date"] for r in healer_trends)
            vals = [r["total_healing"] for r in healer_trends if r.get("total_healing")]
            avg_healing = sum(vals) / len(vals) if vals else None

        if dps_trends:
            raid_dates.update(r["raid_date"] for r in dps_trends)
            vals = [r["total_damage"] for r in dps_trends if r.get("total_damage")]
            avg_damage = sum(vals) / len(vals) if vals else None

        if tank_trends:
            raid_dates.update(r["raid_date"] for r in tank_trends)
            vals = [r["mitigation_percent"] for r in tank_trends if r.get("mitigation_percent")]
            avg_mitigation = sum(vals) / len(vals) if vals else None

        if consumable_trends is None:
            consumable_trends = []
        total_consumables = sum(r.get("count", 0) for r in consumable_trends)

        role = self._infer_role(healer_trends, dps_trends, tank_trends)

        consistency = self._cached_consistency.get(name)
        consistency_val = None
        if consistency:
            scores = []
            for key in ("healing_consistency", "damage_consistency",
                        "mitigation_consistency"):
                if key in consistency:
                    scores.append(consistency[key])
            consistency_val = round(sum(scores) / len(scores), 1) if scores else None

        all_at = []
        for trends in (healer_trends, dps_trends, tank_trends):
            for r in trends:
                at = r.get("active_time_percent")
                if at and at > 0:
                    all_at.append(at)
        avg_active_time = round(sum(all_at) / len(all_at), 1) if all_at else None

        return {
            "role": role,
            "total_raids": len(raid_dates),
            "avg_healing": round(avg_healing, 1) if avg_healing else None,
            "avg_damage": round(avg_damage, 1) if avg_damage else None,
            "avg_mitigation": round(avg_mitigation, 1) if avg_mitigation else None,
            "avg_active_time": avg_active_time,
            "total_consumables": total_consumables,
            "consistency": consistency_val,
        }

    def _aggregate_casts(self):
        mode = self._raid_size_filter.currentIndex()
        all_data: dict[str, dict[str, dict]] = {}
        total_casts_per_spell: dict[str, int] = defaultdict(int)

        for name in self._selected:
            char_spells: dict[str, dict] = {}

            healer_spells = self._filter_by_raid_size(
                self._raw_healer_spells.get(name, []), mode)
            spell_groups: dict[str, list] = defaultdict(list)
            for row in healer_spells:
                spell_groups[row["spell_name"]].append(row)
            for spell, rows in spell_groups.items():
                raid_dates = set(r["raid_date"] for r in rows)
                n_raids = len(raid_dates)
                total_c = sum(r.get("casts", 0) for r in rows)
                total_v = sum(r.get("total_healing", 0) for r in rows)
                char_spells[spell] = {
                    "avg_casts": total_c / n_raids if n_raids else 0,
                    "avg_value": total_v / n_raids if n_raids else 0,
                    "label": "heal",
                }
                total_casts_per_spell[spell] += total_c

            dps_abilities = self._filter_by_raid_size(
                self._raw_dps_abilities.get(name, []), mode)
            ability_groups: dict[str, list] = defaultdict(list)
            for row in dps_abilities:
                ability_groups[row["spell_name"]].append(row)
            for spell, rows in ability_groups.items():
                raid_dates = set(r["raid_date"] for r in rows)
                n_raids = len(raid_dates)
                total_c = sum(r.get("casts", 0) for r in rows)
                total_v = sum(r.get("total_damage", 0) for r in rows)
                char_spells[spell] = {
                    "avg_casts": total_c / n_raids if n_raids else 0,
                    "avg_value": total_v / n_raids if n_raids else 0,
                    "label": "dmg",
                }
                total_casts_per_spell[spell] += total_c

            all_data[name] = char_spells

        sorted_spells = sorted(total_casts_per_spell.keys(),
                               key=lambda s: total_casts_per_spell[s],
                               reverse=True)
        return all_data, sorted_spells

    def _on_raid_size_changed(self):
        mode = self._raid_size_filter.currentIndex()
        for name in self._selected:
            healer = self._filter_by_raid_size(
                self._raw_healer_trends.get(name, []), mode)
            dps = self._filter_by_raid_size(
                self._raw_dps_trends.get(name, []), mode)
            tank = self._filter_by_raid_size(
                self._raw_tank_trends.get(name, []), mode)
            consumes = self._filter_by_raid_size(
                self._raw_consumable_trends.get(name, []), mode)
            self._char_stats[name] = self._compute_stats_from_trends(
                name, healer, dps, tank, consumes)
        self._refresh_display()

    def _add_chip(self, name: str):
        idx = self._selected.index(name)
        color = SERIES_COLORS[idx % len(SERIES_COLORS)]

        chip = QWidget()
        chip_layout = QHBoxLayout(chip)
        chip_layout.setContentsMargins(8, 4, 4, 4)
        chip_layout.setSpacing(4)

        label = QLabel(name)
        label.setStyleSheet(
            f"color: {color.name()}; font-weight: bold; background: transparent;")
        chip_layout.addWidget(label)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                color: {COLORS['text_dim']};
                background: transparent;
                border: none;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{ color: {COLORS['error']}; }}
        """)
        close_btn.clicked.connect(lambda _, n=name: self._remove_character(n))
        chip_layout.addWidget(close_btn)

        chip.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_dark']};
                border: 1px solid {color.name()};
                border-radius: 12px;
            }}
        """)

        self._chips_layout.takeAt(self._chips_layout.count() - 1)
        self._chips_layout.addWidget(chip)
        self._chips_layout.addStretch()
        self._chip_widgets[name] = chip

    def _remove_character(self, name: str):
        if name not in self._selected:
            return
        self._selected.remove(name)
        self._char_stats.pop(name, None)
        self._spider_data.pop(name, None)
        self._raw_healer_trends.pop(name, None)
        self._raw_dps_trends.pop(name, None)
        self._raw_tank_trends.pop(name, None)
        self._raw_healer_spells.pop(name, None)
        self._raw_dps_abilities.pop(name, None)
        self._raw_consumable_trends.pop(name, None)
        self._cached_consistency.pop(name, None)

        chip = self._chip_widgets.pop(name, None)
        if chip:
            self._chips_layout.removeWidget(chip)
            chip.deleteLater()

        self._rebuild_chips()
        self._sync_checkboxes()
        self._refresh_display()
        self.status_message.emit(f"Removed {name} from comparison")

    def _sync_checkboxes(self):
        self._char_list.blockSignals(True)
        for i in range(self._char_list.count()):
            item = self._char_list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(
                Qt.CheckState.Checked if name in self._selected
                else Qt.CheckState.Unchecked)
        self._char_list.blockSignals(False)

    def _rebuild_chips(self):
        for name, chip in list(self._chip_widgets.items()):
            self._chips_layout.removeWidget(chip)
            chip.deleteLater()
        self._chip_widgets.clear()

        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._chips_layout.addStretch()
        for name in self._selected:
            self._add_chip(name)

    def _refresh_display(self):
        self._table_model.set_data(self._selected, self._char_stats)

        cast_data, sorted_spells = self._aggregate_casts()
        self._cast_model.set_data(self._selected, cast_data, sorted_spells)

        self._spider.set_datasets(
            {n: self._spider_data.get(n, {}) for n in self._selected})
