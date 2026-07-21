"""Pytest-qt tests for GUI table models.

Uses qtbot instead of manually managing QApplication.
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from warcraftlogs_client.gui.table_models import (
    DPSTableModel,
    HealerTableModel,
    HistoryTableModel,
    TankTableModel,
)
from warcraftlogs_client.models import (
    DispelUsage,
    DPSPerformance,
    HealerPerformance,
    ResourceUsage,
    SpellUsage,
    TankPerformance,
)


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


@pytest.mark.gui
class TestHealerTableModelQt:
    def test_empty_model(self, qtbot):
        model = HealerTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 10

    def test_set_data_populates_rows(self, qtbot, sample_healer):
        model = HealerTableModel()
        model.set_data([sample_healer])
        assert model.rowCount() == 1

    def test_display_data(self, qtbot, sample_healer):
        model = HealerTableModel([sample_healer])
        assert model.data(model.index(0, 0)) == "Priestess"
        assert model.data(model.index(0, 1)) == "Priest"
        assert model.data(model.index(0, 2)) == "500,000"

    def test_set_data_sorts_by_healing(self, qtbot):
        h1 = HealerPerformance(name="Low", player_class="Priest", source_id=1, total_healing=100)
        h2 = HealerPerformance(name="High", player_class="Priest", source_id=2, total_healing=500)
        model = HealerTableModel()
        model.set_data([h1, h2])
        assert model.data(model.index(0, 0)) == "High"
        assert model.data(model.index(1, 0)) == "Low"

    def test_column_headers(self, qtbot):
        model = HealerTableModel()
        assert model.headerData(0, Qt.Orientation.Horizontal) == "Name"
        assert model.headerData(2, Qt.Orientation.Horizontal) == "Healing"

    def test_invalid_index_returns_none(self, qtbot, sample_healer):
        model = HealerTableModel([sample_healer])
        assert model.data(model.index(5, 0)) is None


@pytest.mark.gui
class TestTankTableModelQt:
    def test_empty_model(self, qtbot):
        model = TankTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 6

    def test_set_data_populates_rows(self, qtbot, sample_tank):
        model = TankTableModel()
        model.set_data([sample_tank])
        assert model.rowCount() == 1

    def test_display_data(self, qtbot, sample_tank):
        model = TankTableModel([sample_tank])
        assert model.data(model.index(0, 0)) == "Tankadin"
        assert model.data(model.index(0, 1)) == "Paladin"
        assert model.data(model.index(0, 2)) == "800,000"
        assert model.data(model.index(0, 3)) == "1,200,000"

    def test_set_data_sorts_by_damage_taken(self, qtbot):
        t1 = TankPerformance(name="Low", player_class="Warrior", source_id=1, total_damage_taken=100)
        t2 = TankPerformance(name="High", player_class="Warrior", source_id=2, total_damage_taken=500)
        model = TankTableModel()
        model.set_data([t1, t2])
        assert model.data(model.index(0, 0)) == "High"

    def test_invalid_index_returns_none(self, qtbot, sample_tank):
        model = TankTableModel([sample_tank])
        assert model.data(model.index(5, 0)) is None


@pytest.mark.gui
class TestDPSTableModelQt:
    def test_empty_model(self, qtbot):
        model = DPSTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 5

    def test_set_data_populates_rows(self, qtbot, sample_dps):
        model = DPSTableModel()
        model.set_data([sample_dps])
        assert model.rowCount() == 1

    def test_display_data(self, qtbot, sample_dps):
        model = DPSTableModel([sample_dps])
        assert model.data(model.index(0, 0)) == "Stabber"
        assert model.data(model.index(0, 1)) == "Rogue"
        assert model.data(model.index(0, 2)) == "1,200,000"

    def test_top_ability_with_casts(self, qtbot, sample_dps):
        model = DPSTableModel([sample_dps])
        val = model.data(model.index(0, 4))
        assert "Sinister Strike" in val
        assert "450" in val

    def test_set_data_sorts_by_damage(self, qtbot):
        d1 = DPSPerformance(name="Low", player_class="Rogue", source_id=1, role="melee", total_damage=100)
        d2 = DPSPerformance(name="High", player_class="Rogue", source_id=2, role="melee", total_damage=500)
        model = DPSTableModel()
        model.set_data([d1, d2])
        assert model.data(model.index(0, 0)) == "High"

    def test_no_abilities_shows_dash(self, qtbot):
        d = DPSPerformance(name="Empty", player_class="Rogue", source_id=1, role="melee")
        model = DPSTableModel([d])
        assert model.data(model.index(0, 4)) == "-"


@pytest.mark.gui
class TestHistoryTableModelQt:
    def test_empty_model(self, qtbot):
        model = HistoryTableModel(columns=["Name", "Damage"])
        assert model.rowCount() == 0
        assert model.columnCount() == 2

    def test_set_data_and_read(self, qtbot):
        model = HistoryTableModel(columns=["name", "damage"])
        model.set_data([{"name": "Player1", "damage": 50000}])
        assert model.rowCount() == 1
        assert model.data(model.index(0, 0)) == "Player1"
        assert model.data(model.index(0, 1)) == "50,000"

    def test_checkable_mode_adds_column(self, qtbot):
        model = HistoryTableModel(columns=["name"], checkable=True)
        model.set_data([{"name": "A"}])
        assert model.columnCount() == 2  # checkbox col + 1 data col

    def test_checkbox_toggle_and_checked_rows(self, qtbot):
        model = HistoryTableModel(columns=["name"], checkable=True)
        model.set_data([{"name": "A"}, {"name": "B"}])
        model.setData(model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        checked = model.checked_rows()
        assert len(checked) == 1
        assert checked[0]["name"] == "A"
