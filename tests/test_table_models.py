"""Tests for GUI table models — data(), rowCount(), columnCount(), edge cases.

These tests require PySide6; they are skipped automatically in CI
where PySide6 is not installed.
"""

import pytest

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from warcraftlogs_client.gui.table_models import (
    DPSTableModel,
    GearTableModel,
    HealerTableModel,
    HistoryTableModel,
    TankTableModel,
)
from warcraftlogs_client.models import (
    DispelUsage,
    DPSPerformance,
    GearItem,
    HealerPerformance,
    ResourceUsage,
    SpellUsage,
    TankPerformance,
)

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def sample_healer():
    return HealerPerformance(
        name="Priestess",
        player_class="Priest",
        source_id=1,
        total_healing=500_000,
        total_overhealing=100_000,
        spells=[SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=120, total_amount=300_000)],
        dispels=[DispelUsage(spell_name="Dispel Magic", casts=15)],
        resources=[ResourceUsage(name="Super Mana Potion", count=3), ResourceUsage(name="Dark Rune", count=2)],
        fear_ward_casts=4,
        active_time_percent=92.5,
    )


@pytest.fixture
def sample_tank():
    return TankPerformance(
        name="Tankadin",
        player_class="Paladin",
        source_id=2,
        total_damage_taken=800_000,
        total_mitigated=1_200_000,
        active_time_percent=98.0,
    )


@pytest.fixture
def sample_dps():
    return DPSPerformance(
        name="Stabber",
        player_class="Rogue",
        source_id=3,
        role="melee",
        total_damage=1_200_000,
        abilities=[SpellUsage(spell_id=1, spell_name="Sinister Strike", casts=450, total_amount=600_000)],
        active_time_percent=95.3,
    )


class TestHealerTableModel:
    def test_empty_model(self):
        model = HealerTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 10

    def test_row_count_matches_data(self, sample_healer):
        model = HealerTableModel([sample_healer])
        assert model.rowCount() == 1

    def test_column_headers(self):
        model = HealerTableModel()
        assert model.headerData(0, Qt.Orientation.Horizontal) == "Name"
        assert model.headerData(2, Qt.Orientation.Horizontal) == "Healing"
        assert model.headerData(0, Qt.Orientation.Vertical) is None

    def test_display_data(self, sample_healer):
        model = HealerTableModel([sample_healer])
        idx = model.index(0, 0)
        assert model.data(idx) == "Priestess"
        assert model.data(model.index(0, 1)) == "Priest"
        assert model.data(model.index(0, 2)) == "500,000"
        assert model.data(model.index(0, 3)) == "100,000"

    def test_overheal_percent(self, sample_healer):
        model = HealerTableModel([sample_healer])
        val = model.data(model.index(0, 4))
        assert "%" in val

    def test_active_time(self, sample_healer):
        model = HealerTableModel([sample_healer])
        assert model.data(model.index(0, 5)) == "92.5%"

    def test_top_spell_with_casts(self, sample_healer):
        model = HealerTableModel([sample_healer])
        val = model.data(model.index(0, 6))
        assert "Greater Heal" in val
        assert "120" in val

    def test_dispels_column(self, sample_healer):
        model = HealerTableModel([sample_healer])
        assert model.data(model.index(0, 7)) == 15

    def test_mana_pot_column(self, sample_healer):
        model = HealerTableModel([sample_healer])
        assert model.data(model.index(0, 8)) == 3

    def test_dark_rune_column(self, sample_healer):
        model = HealerTableModel([sample_healer])
        assert model.data(model.index(0, 9)) == 2

    def test_no_spells(self):
        h = HealerPerformance(name="Empty", player_class="Priest", source_id=1)
        model = HealerTableModel([h])
        assert model.data(model.index(0, 6)) == "-"

    def test_no_active_time(self):
        h = HealerPerformance(name="Zero", player_class="Priest", source_id=1)
        model = HealerTableModel([h])
        assert model.data(model.index(0, 5)) == "-"

    def test_invalid_index_returns_none(self, sample_healer):
        model = HealerTableModel([sample_healer])
        assert model.data(model.index(5, 0)) is None

    def test_set_data_sorts_by_healing(self):
        h1 = HealerPerformance(name="Low", player_class="Priest", source_id=1, total_healing=100)
        h2 = HealerPerformance(name="High", player_class="Priest", source_id=2, total_healing=500)
        model = HealerTableModel()
        model.set_data([h1, h2])
        assert model.data(model.index(0, 0)) == "High"
        assert model.data(model.index(1, 0)) == "Low"


class TestTankTableModel:
    def test_empty_model(self):
        model = TankTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 6

    def test_display_data(self, sample_tank):
        model = TankTableModel([sample_tank])
        assert model.data(model.index(0, 0)) == "Tankadin"
        assert model.data(model.index(0, 1)) == "Paladin"
        assert model.data(model.index(0, 2)) == "800,000"
        assert model.data(model.index(0, 3)) == "1,200,000"

    def test_mitigation_percent(self, sample_tank):
        model = TankTableModel([sample_tank])
        val = model.data(model.index(0, 4))
        assert "%" in val

    def test_active_time(self, sample_tank):
        model = TankTableModel([sample_tank])
        assert model.data(model.index(0, 5)) == "98.0%"

    def test_set_data_sorts_by_damage_taken(self):
        t1 = TankPerformance(name="Low", player_class="Warrior", source_id=1, total_damage_taken=100)
        t2 = TankPerformance(name="High", player_class="Warrior", source_id=2, total_damage_taken=500)
        model = TankTableModel()
        model.set_data([t1, t2])
        assert model.data(model.index(0, 0)) == "High"

    def test_invalid_index_returns_none(self, sample_tank):
        model = TankTableModel([sample_tank])
        assert model.data(model.index(5, 0)) is None


class TestDPSTableModel:
    def test_empty_model(self):
        model = DPSTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 5

    def test_display_data(self, sample_dps):
        model = DPSTableModel([sample_dps])
        assert model.data(model.index(0, 0)) == "Stabber"
        assert model.data(model.index(0, 1)) == "Rogue"
        assert model.data(model.index(0, 2)) == "1,200,000"

    def test_active_time(self, sample_dps):
        model = DPSTableModel([sample_dps])
        assert model.data(model.index(0, 3)) == "95.3%"

    def test_top_ability_with_casts(self, sample_dps):
        model = DPSTableModel([sample_dps])
        val = model.data(model.index(0, 4))
        assert "Sinister Strike" in val
        assert "450" in val

    def test_no_abilities(self):
        d = DPSPerformance(name="Empty", player_class="Rogue", source_id=1, role="melee")
        model = DPSTableModel([d])
        assert model.data(model.index(0, 4)) == "-"

    def test_set_data_sorts_by_damage(self):
        d1 = DPSPerformance(name="Low", player_class="Rogue", source_id=1, role="melee", total_damage=100)
        d2 = DPSPerformance(name="High", player_class="Rogue", source_id=2, role="melee", total_damage=500)
        model = DPSTableModel()
        model.set_data([d1, d2])
        assert model.data(model.index(0, 0)) == "High"


class TestHistoryTableModel:
    def test_empty_model(self):
        model = HistoryTableModel(columns=["Name", "Damage"])
        assert model.rowCount() == 0
        assert model.columnCount() == 2

    def test_display_data(self):
        model = HistoryTableModel(columns=["name", "damage"])
        model.set_data([{"name": "Player1", "damage": 50000}])
        assert model.data(model.index(0, 0)) == "Player1"
        assert model.data(model.index(0, 1)) == "50,000"

    def test_float_formatting(self):
        model = HistoryTableModel(columns=["pct"])
        model.set_data([{"pct": 85.6789}])
        assert model.data(model.index(0, 0)) == "85.7"

    def test_checkable_mode(self):
        model = HistoryTableModel(columns=["name"], checkable=True)
        model.set_data([{"name": "A"}, {"name": "B"}])
        assert model.columnCount() == 2  # checkbox col + 1 data col
        assert model.data(model.index(0, 1)) == "A"

    def test_checkbox_toggle(self):
        model = HistoryTableModel(columns=["name"], checkable=True)
        model.set_data([{"name": "A"}, {"name": "B"}])
        model.setData(model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        assert len(model.checked_rows()) == 1
        assert model.checked_rows()[0]["name"] == "A"

    def test_set_data_clears_checks(self):
        model = HistoryTableModel(columns=["name"], checkable=True)
        model.set_data([{"name": "A"}])
        model.setData(model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        model.set_data([{"name": "B"}])
        assert len(model.checked_rows()) == 0

    def test_alignment_numeric(self):
        model = HistoryTableModel(columns=["val"])
        model.set_data([{"val": 42}])
        alignment = model.data(model.index(0, 0), Qt.ItemDataRole.TextAlignmentRole)
        assert alignment & Qt.AlignmentFlag.AlignRight

    def test_alignment_text(self):
        model = HistoryTableModel(columns=["name"])
        model.set_data([{"name": "text"}])
        alignment = model.data(model.index(0, 0), Qt.ItemDataRole.TextAlignmentRole)
        assert alignment & Qt.AlignmentFlag.AlignLeft

    def test_none_value(self):
        model = HistoryTableModel(columns=["missing"])
        model.set_data([{"other": "val"}])
        assert model.data(model.index(0, 0)) == ""


class TestGearTableModel:
    def test_empty_model(self):
        model = GearTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 5

    def test_display_data(self):
        item = GearItem(slot="Head", item_id=12345, item_level=115, quality=4)
        model = GearTableModel()
        model.set_data([item])
        assert model.data(model.index(0, 0)) == "Head"
        assert model.data(model.index(0, 1)) == "#12345"
        assert model.data(model.index(0, 2)) == 115
        assert model.data(model.index(0, 3)) == "Epic"

    def test_resolved_names(self):
        item = GearItem(slot="Head", item_id=12345, item_level=115, quality=4)
        model = GearTableModel()
        model.set_data([item])
        model.set_resolved({12345: "Helm of the Fallen Hero"}, {})
        assert model.data(model.index(0, 1)) == "Helm of the Fallen Hero"

    def test_gems_display(self):
        item = GearItem(slot="Head", item_id=12345, item_level=115, quality=4, gems=[100, 200])
        model = GearTableModel()
        model.set_data([item])
        model.set_resolved({100: "Red Gem", 200: "Blue Gem"}, {})
        val = model.data(model.index(0, 4))
        assert "Red Gem" in val
        assert "Blue Gem" in val

    def test_no_gems(self):
        item = GearItem(slot="Head", item_id=12345, item_level=115, quality=4)
        model = GearTableModel()
        model.set_data([item])
        assert model.data(model.index(0, 4)) == ""

    def test_column_headers(self):
        model = GearTableModel()
        assert model.headerData(0, Qt.Orientation.Horizontal) == "Slot"
        assert model.headerData(1, Qt.Orientation.Horizontal) == "Item"
