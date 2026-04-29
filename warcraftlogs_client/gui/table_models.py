"""
Qt table models for displaying analysis results.
"""

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor, QFont

from ..models import HealerPerformance, TankPerformance, DPSPerformance, GearItem


class HealerTableModel(QAbstractTableModel):
    def __init__(self, healers: list[HealerPerformance] = None, parent=None):
        super().__init__(parent)
        self._healers = healers or []
        self._columns = ["Name", "Class", "Healing", "Overhealing", "OH%",
                         "Dispels", "Mana Pot", "Dark Rune"]

    def set_data(self, healers: list[HealerPerformance]):
        self.beginResetModel()
        self._healers = sorted(healers, key=lambda h: h.total_healing, reverse=True)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._healers)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._healers):
            return None

        h = self._healers[index.row()]
        col = index.column()
        resource_lookup = {r.name: r.count for r in h.resources}

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return h.name
            if col == 1: return h.player_class
            if col == 2: return f"{h.total_healing:,}"
            if col == 3: return f"{h.total_overhealing:,}"
            if col == 4: return f"{h.overheal_percent:.1f}%"
            if col == 5: return sum(d.casts for d in h.dispels)
            if col == 6: return resource_lookup.get("Super Mana Potion", 0)
            if col == 7: return resource_lookup.get("Dark Rune", 0)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col >= 2:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return _link_color()
            if col == 1:
                return _class_color(h.player_class)

        if role == Qt.ItemDataRole.FontRole:
            if col == 0:
                return _link_font()

        return None


class TankTableModel(QAbstractTableModel):
    def __init__(self, tanks: list[TankPerformance] = None, parent=None):
        super().__init__(parent)
        self._tanks = tanks or []
        self._columns = ["Name", "Class", "Damage Taken", "Mitigated", "Mitigation%"]

    def set_data(self, tanks: list[TankPerformance]):
        self.beginResetModel()
        self._tanks = sorted(tanks, key=lambda t: t.total_damage_taken, reverse=True)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._tanks)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._tanks):
            return None

        t = self._tanks[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return t.name
            if col == 1: return t.player_class
            if col == 2: return f"{t.total_damage_taken:,}"
            if col == 3: return f"{t.total_mitigated:,}"
            if col == 4: return f"{t.mitigation_percent:.1f}%"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col >= 2:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return _link_color()
            if col == 1:
                return _class_color(t.player_class)

        if role == Qt.ItemDataRole.FontRole:
            if col == 0:
                return _link_font()

        return None


class DPSTableModel(QAbstractTableModel):
    def __init__(self, dps_list: list[DPSPerformance] = None, parent=None):
        super().__init__(parent)
        self._dps = dps_list or []
        self._columns = ["Name", "Class", "Total Damage", "Top Ability", "Top Ability Casts"]

    def set_data(self, dps_list: list[DPSPerformance]):
        self.beginResetModel()
        self._dps = sorted(dps_list, key=lambda d: d.total_damage, reverse=True)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._dps)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._columns[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._dps):
            return None

        d = self._dps[index.row()]
        col = index.column()

        top = d.abilities[0] if d.abilities else None

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return d.name
            if col == 1: return d.player_class
            if col == 2: return f"{d.total_damage:,}"
            if col == 3: return top.spell_name if top else "-"
            if col == 4: return top.casts if top else 0

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col >= 2:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return _link_color()
            if col == 1:
                return _class_color(d.player_class)

        if role == Qt.ItemDataRole.FontRole:
            if col == 0:
                return _link_font()

        return None


class HistoryTableModel(QAbstractTableModel):
    """Generic table model for history trend data (list of dicts)."""

    def __init__(self, columns: list[str] = None, link_columns: set[str] = None,
                 checkable: bool = False, parent=None):
        super().__init__(parent)
        self._columns = columns or []
        self._rows: list[dict] = []
        self._link_columns = link_columns or set()
        self._checkable = checkable
        self._checked: set[int] = set()

    def set_data(self, rows: list[dict], columns: list[str] = None):
        self.beginResetModel()
        self._rows = rows
        if columns:
            self._columns = columns
        self._checked.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        extra = 1 if self._checkable else 0
        return len(self._columns) + extra

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if self._checkable:
                if section == 0:
                    return ""
                return self._columns[section - 1]
            return self._columns[section]
        return None

    def flags(self, index):
        base = super().flags(index)
        if self._checkable and index.column() == 0:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def checked_rows(self) -> list[dict]:
        return [self._rows[i] for i in sorted(self._checked) if i < len(self._rows)]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None

        if self._checkable and index.column() == 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if index.row() in self._checked else Qt.CheckState.Unchecked
            return None

        row = self._rows[index.row()]
        col_idx = index.column() - 1 if self._checkable else index.column()
        if col_idx < 0 or col_idx >= len(self._columns):
            return None
        col_key = self._columns[col_idx]

        if role == Qt.ItemDataRole.DisplayRole:
            val = row.get(col_key, row.get(col_key.lower().replace(" ", "_"), ""))
            if isinstance(val, float):
                return f"{val:,.1f}"
            if isinstance(val, int) and val > 9999:
                return f"{val:,}"
            return str(val) if val is not None else ""

        if role == Qt.ItemDataRole.TextAlignmentRole:
            val = row.get(col_key, row.get(col_key.lower().replace(" ", "_"), ""))
            if isinstance(val, (int, float)):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if col_key in self._link_columns:
                return _link_color()

        if role == Qt.ItemDataRole.FontRole:
            if col_key in self._link_columns:
                return _link_font()

        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if self._checkable and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            if value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked:
                self._checked.add(index.row())
            else:
                self._checked.discard(index.row())
            self.dataChanged.emit(index, index, [role])
            return True
        return False


QUALITY_COLORS = {
    0: QColor("#9d9d9d"),  # Poor
    1: QColor("#ffffff"),  # Common
    2: QColor("#1eff00"),  # Uncommon
    3: QColor("#0070dd"),  # Rare
    4: QColor("#a335ee"),  # Epic
    5: QColor("#ff8000"),  # Legendary
}


class GearTableModel(QAbstractTableModel):
    COLUMNS = ["Slot", "Item", "iLvl", "Quality", "Gems"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[GearItem] = []
        self._names: dict[int, str] = {}
        self._tooltips: dict[int, str] = {}

    def set_data(self, items: list[GearItem]):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def set_resolved(self, item_names: dict, tooltips: dict):
        self.beginResetModel()
        self._names = item_names
        self._tooltips = tooltips
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None

        item = self._items[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return item.slot
            if col == 1: return self._names.get(item.item_id, f"#{item.item_id}")
            if col == 2: return item.item_level if item.item_level else ""
            if col == 3: return item.quality_name
            if col == 4:
                if not item.gems:
                    return ""
                return ", ".join(
                    self._names.get(gid, f"#{gid}") for gid in item.gems
                )

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 1 and item.item_id in self._tooltips:
                return self._tooltips[item.item_id]

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 2:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 1:
                return QUALITY_COLORS.get(item.quality, _link_color())
            if col == 3:
                return QUALITY_COLORS.get(item.quality, QColor("#eeeeee"))
            if col == 4:
                return _link_color()

        if role == Qt.ItemDataRole.FontRole:
            if col in (1, 4):
                return _link_font()

        return None


def _link_color() -> QColor:
    return QColor("#e94560")


def _link_font() -> QFont:
    font = QFont()
    font.setUnderline(True)
    return font


def _class_color(class_name: str) -> QColor:
    colors = {
        "Warrior": QColor("#C79C6E"),
        "Paladin": QColor("#F58CBA"),
        "Priest": QColor("#FFFFFF"),
        "Shaman": QColor("#0070DE"),
        "Druid": QColor("#FF7D0A"),
        "Rogue": QColor("#FFF569"),
        "Mage": QColor("#69CCF0"),
        "Warlock": QColor("#9482C9"),
        "Hunter": QColor("#ABD473"),
    }
    return colors.get(class_name, QColor("#EEEEEE"))
