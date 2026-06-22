"""Shared analysis helpers used by both the main raid view and Head-to-Head comparison."""

import dataclasses
from collections import defaultdict

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PySide6.QtGui import QColor

from .styles import COLORS

ENGINEERING_ITEMS = {
    "Super Sapper Charge", "Goblin Sapper Charge",
    "Adamantite Grenade", "Gnomish Flame Turret",
    "Fel Iron Bomb", "Bomb",
}


class NumericSortProxy(QSortFilterProxyModel):
    """Proxy that sorts columns numerically when the display text looks like a number."""

    def lessThan(self, left, right):
        l_val = self.sourceModel().data(left, Qt.ItemDataRole.DisplayRole)
        r_val = self.sourceModel().data(right, Qt.ItemDataRole.DisplayRole)
        l_num = self._parse_number(l_val)
        r_num = self._parse_number(r_val)
        if l_num is not None and r_num is not None:
            return l_num < r_num
        return super().lessThan(left, right)

    @staticmethod
    def _parse_number(text):
        if not isinstance(text, str) or text in ("", "—"):
            return None
        try:
            return float(text.replace(",", "").replace("%", "").replace("+", ""))
        except (ValueError, AttributeError):
            return None


def build_timeline_data(analysis, consumable_name):
    """Return per-player timeline rows for a specific consumable."""
    rows = []
    for cu in (analysis.consumables or []):
        if cu.consumable_name != consumable_name:
            continue
        ts_parts = []
        for ms in sorted(cu.timestamps):
            total_s = ms // 1000
            ts_parts.append(f"{total_s // 60:02d}:{total_s % 60:02d}")
        rows.append({
            "player": cu.player_name,
            "role": cu.player_role,
            "count": cu.count,
            "timestamps": ", ".join(ts_parts) if ts_parts else "—",
            "first_ts": cu.timestamps[0] if cu.timestamps else float("inf"),
        })
    rows.sort(key=lambda r: r["first_ts"])
    return rows


def compute_engineering_stats(analysis):
    """Compute min/median/max avg-damage-per-cast for engineering items."""
    from statistics import median as stat_median

    item_data = defaultdict(lambda: {"player_avgs": [], "total_casts": 0,
                                      "total_damage": 0, "users": 0})
    all_players = list(analysis.dps or [])
    for player in all_players:
        for ability in (player.abilities or []):
            if ability.spell_name not in ENGINEERING_ITEMS:
                continue
            if ability.casts <= 0:
                continue
            avg_dmg = ability.total_amount / ability.casts
            entry = item_data[ability.spell_name]
            entry["player_avgs"].append(avg_dmg)
            entry["total_casts"] += ability.casts
            entry["total_damage"] += ability.total_amount
            entry["users"] += 1

    result = {}
    for name, data in item_data.items():
        avgs = sorted(data["player_avgs"])
        result[name] = {
            "total_casts": data["total_casts"],
            "total_damage": data["total_damage"],
            "users": data["users"],
            "min_avg": avgs[0] if avgs else 0,
            "median_avg": stat_median(avgs) if avgs else 0,
            "max_avg": avgs[-1] if avgs else 0,
        }
    return result


def classify_consumable_usage(analysis):
    """Classify each consumable use as boss or trash based on encounter windows."""
    encounters = analysis.encounters or []
    intervals = [(e.start_time, e.end_time) for e in encounters]

    by_name = defaultdict(lambda: {"boss": 0, "trash": 0})
    for cu in (analysis.consumables or []):
        for ts in cu.timestamps:
            in_boss = any(s <= ts <= e for s, e in intervals)
            by_name[cu.consumable_name]["boss" if in_boss else "trash"] += 1
    return dict(by_name)


def compute_shared_encounter_window(guild_analysis, ref_analysis):
    """Detect extra guild encounters and compute the shared encounter time window.

    Returns a dict with scoping metadata, or None if either side has no encounters.
    """
    guild_encs = guild_analysis.encounters or []
    ref_encs = ref_analysis.encounters or []
    if not guild_encs or not ref_encs:
        return None

    ref_ids = {e.encounter_id for e in ref_encs}
    ref_names = {e.name for e in ref_encs}

    shared = []
    extra = []
    for e in guild_encs:
        if e.encounter_id in ref_ids or e.name in ref_names:
            shared.append(e)
        else:
            extra.append(e)

    if not extra:
        return {"has_extra_encounters": False, "guild_extra_names": [],
                "window_start": None, "window_end": None,
                "shared_count": len(shared)}

    if not shared:
        return {"has_extra_encounters": True,
                "guild_extra_names": sorted(e.name for e in extra),
                "window_start": None, "window_end": None,
                "shared_count": 0}

    return {
        "has_extra_encounters": True,
        "guild_extra_names": sorted(e.name for e in extra),
        "window_start": min(e.start_time for e in shared),
        "window_end": max(e.end_time for e in shared),
        "shared_count": len(shared),
    }


def scope_analysis_to_window(analysis, window_start, window_end):
    """Return a copy of the analysis with consumables and encounters filtered to a time window."""
    filtered_consumables = []
    for cu in (analysis.consumables or []):
        ts = [t for t in cu.timestamps if window_start <= t <= window_end]
        if ts:
            filtered_consumables.append(
                dataclasses.replace(cu, timestamps=ts, count=len(ts)))

    filtered_encounters = [
        e for e in (analysis.encounters or [])
        if e.start_time >= window_start and e.end_time <= window_end
    ]

    return dataclasses.replace(
        analysis,
        consumables=filtered_consumables,
        encounters=filtered_encounters,
    )


class TimelineTableModel(QAbstractTableModel):
    HEADERS = ["Player", "Role", "Count", "Timestamps"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("player", "")
            elif col == 1:
                return row.get("role", "")
            elif col == 2:
                return str(row.get("count", 0))
            elif col == 3:
                return row.get("timestamps", "—")
        elif role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS["text"])
        return None


class SingleBossTrashModel(QAbstractTableModel):
    HEADERS = ["Consumable", "Boss Uses", "Trash Uses"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("name", "")
            elif col == 1:
                return str(row.get("boss", 0))
            elif col == 2:
                return str(row.get("trash", 0))
        elif role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS["text"])
        return None


class SingleEngineeringModel(QAbstractTableModel):
    HEADERS = ["Item", "Players", "Casts", "Total Damage",
               "Min Avg", "Median Avg", "Max Avg"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def set_data(self, rows: list[dict]):
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return row.get("name", "")
            elif col == 1:
                return str(row.get("users", 0))
            elif col == 2:
                return str(row.get("total_casts", 0))
            elif col == 3:
                return f"{row.get('total_damage', 0):,.0f}"
            elif col == 4:
                return f"{row.get('min_avg', 0):,.0f}"
            elif col == 5:
                return f"{row.get('median_avg', 0):,.0f}"
            elif col == 6:
                return f"{row.get('max_avg', 0):,.0f}"
        elif role == Qt.ItemDataRole.ForegroundRole:
            return QColor(COLORS["text"])
        return None
