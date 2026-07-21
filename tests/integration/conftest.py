"""Shared fixtures for integration tests."""

import pytest

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.models import (
    ConsumableUsage,
    DPSPerformance,
    EncounterPerformance,
    EncounterSummary,
    HealerPerformance,
    InterruptUsage,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)


@pytest.fixture
def db(tmp_path):
    """Create a fresh test database."""
    db_path = str(tmp_path / "integration_test.db")
    with PerformanceDB(db_path) as database:
        yield database


def make_analysis(
    report_id="int_test_001",
    title="Integration Test Raid",
    owner="TestGuild",
    healer_name="HolyPriest",
    tank_name="TankWarrior",
    dps_name="StabbyRogue",
    healer_healing=500_000,
    tank_damage_taken=800_000,
    dps_damage=400_000,
    consumables=None,
    interrupts=None,
    encounters=None,
):
    """Factory for building RaidAnalysis objects."""
    metadata = RaidMetadata(
        report_id=report_id,
        title=title,
        owner=owner,
        start_time=1_700_000_000_000,
        end_time=1_700_003_600_000,
    )
    composition = RaidComposition(
        tanks=[PlayerIdentity(name=tank_name, player_class="Warrior", source_id=2, role="tank")],
        healers=[PlayerIdentity(name=healer_name, player_class="Priest", source_id=1, role="healer")],
        melee=[PlayerIdentity(name=dps_name, player_class="Rogue", source_id=3, role="melee")],
        ranged=[],
    )
    return RaidAnalysis(
        metadata=metadata,
        composition=composition,
        healers=[
            HealerPerformance(
                name=healer_name,
                player_class="Priest",
                source_id=1,
                total_healing=healer_healing,
                total_overhealing=int(healer_healing * 0.2),
                spells=[SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=50, total_amount=healer_healing)],
                dispels=[],
                resources=[],
                fear_ward_casts=3,
            )
        ],
        tanks=[
            TankPerformance(
                name=tank_name,
                player_class="Warrior",
                source_id=2,
                total_damage_taken=tank_damage_taken,
                total_mitigated=int(tank_damage_taken * 0.75),
                damage_taken_breakdown=[SpellUsage(spell_id=1, spell_name="Melee", casts=200)],
                abilities_used=[SpellUsage(spell_id=6572, spell_name="Revenge", casts=45)],
            )
        ],
        dps=[
            DPSPerformance(
                name=dps_name,
                player_class="Rogue",
                source_id=3,
                role="melee",
                total_damage=dps_damage,
                abilities=[SpellUsage(spell_id=26862, spell_name="Sinister Strike", casts=120, total_amount=dps_damage)],
            )
        ],
        consumables=consumables or [],
        interrupts=interrupts or [],
        encounters=encounters or [],
    )
