"""Shared fixtures for the Warcraft Logs test suite."""

import json
import os
from unittest.mock import MagicMock

import pytest

from warcraftlogs_client.models import (
    ConsumableUsage,
    DPSPerformance,
    DispelUsage,
    EncounterPerformance,
    EncounterSummary,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    ResourceUsage,
    SpellUsage,
    TankPerformance,
)


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset singletons between tests."""
    import warcraftlogs_client.spell_manager as sm
    import warcraftlogs_client.config as cfg

    sm._spell_manager = None
    cfg._config_manager = None
    yield
    sm._spell_manager = None
    cfg._config_manager = None


@pytest.fixture
def sample_raid_metadata():
    return RaidMetadata(
        report_id="abc123",
        title="Karazhan Clear",
        owner="TestGuild",
        start_time=1_700_000_000_000,
        end_time=1_700_003_600_000,
    )


@pytest.fixture
def sample_healer_performance():
    return HealerPerformance(
        name="HolyPriest",
        player_class="Priest",
        source_id=1,
        total_healing=500_000,
        total_overhealing=100_000,
        spells=[
            SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=50, total_amount=300_000),
            SpellUsage(spell_id=139, spell_name="Renew", casts=80, total_amount=200_000),
        ],
        dispels=[DispelUsage(spell_name="Dispel Magic", casts=12)],
        resources=[ResourceUsage(name="Super Mana Potion", count=3)],
        fear_ward_casts=5,
    )


@pytest.fixture
def sample_tank_performance():
    return TankPerformance(
        name="TankWarrior",
        player_class="Warrior",
        source_id=2,
        total_damage_taken=800_000,
        total_mitigated=600_000,
        damage_taken_breakdown=[
            SpellUsage(spell_id=1, spell_name="Melee", casts=200),
        ],
        abilities_used=[
            SpellUsage(spell_id=6572, spell_name="Revenge", casts=45),
        ],
    )


@pytest.fixture
def sample_dps_performance():
    return DPSPerformance(
        name="StabbyRogue",
        player_class="Rogue",
        source_id=3,
        role="melee",
        total_damage=400_000,
        abilities=[
            SpellUsage(spell_id=1, spell_name="Melee", casts=300, total_amount=200_000),
            SpellUsage(spell_id=26862, spell_name="Sinister Strike", casts=120, total_amount=150_000),
        ],
    )


@pytest.fixture
def sample_composition():
    return RaidComposition(
        tanks=[PlayerIdentity(name="TankWarrior", player_class="Warrior", source_id=2, role="tank")],
        healers=[PlayerIdentity(name="HolyPriest", player_class="Priest", source_id=1, role="healer")],
        melee=[PlayerIdentity(name="StabbyRogue", player_class="Rogue", source_id=3, role="melee")],
        ranged=[PlayerIdentity(name="FrostMage", player_class="Mage", source_id=4, role="ranged")],
    )


@pytest.fixture
def sample_raid_analysis(sample_raid_metadata, sample_composition,
                         sample_healer_performance, sample_tank_performance,
                         sample_dps_performance):
    return RaidAnalysis(
        metadata=sample_raid_metadata,
        composition=sample_composition,
        healers=[sample_healer_performance],
        tanks=[sample_tank_performance],
        dps=[sample_dps_performance],
        consumables=[
            ConsumableUsage(
                player_name="HolyPriest", player_role="healer",
                report_id="abc123", consumable_name="Super Mana Potion",
                count=3, timestamps=[60_000, 180_000, 300_000],
            ),
        ],
    )


@pytest.fixture
def sample_encounter_summary():
    return EncounterSummary(
        encounter_id=658,
        name="Attumen the Huntsman",
        start_time=12000,
        end_time=180000,
        duration_ms=168000,
        players=[
            EncounterPerformance(
                name="StabbyRogue", player_class="Rogue", source_id=3,
                role="melee", total_damage=150_000, total_healing=0, total_damage_taken=20_000,
            ),
            EncounterPerformance(
                name="HolyPriest", player_class="Priest", source_id=1,
                role="healer", total_damage=5_000, total_healing=120_000, total_damage_taken=15_000,
            ),
            EncounterPerformance(
                name="TankWarrior", player_class="Warrior", source_id=2,
                role="tank", total_damage=30_000, total_healing=0, total_damage_taken=200_000,
            ),
        ],
    )


@pytest.fixture
def sample_master_actors():
    return [
        {"name": "TankWarrior", "id": 2, "type": "Player", "subType": "Warrior"},
        {"name": "HolyPriest", "id": 1, "type": "Player", "subType": "Priest"},
        {"name": "StabbyRogue", "id": 3, "type": "Player", "subType": "Rogue"},
        {"name": "FrostMage", "id": 4, "type": "Player", "subType": "Mage"},
        {"name": "ShadowLock", "id": 5, "type": "Player", "subType": "Warlock"},
        {"name": "BoomDruid", "id": 6, "type": "Player", "subType": "Druid"},
        {"name": "Onyxia", "id": 100, "type": "NPC", "subType": "Boss"},
    ]


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.run_query.return_value = {"data": {"reportData": {"report": {}}}}
    client.get_healing_data.return_value = []
    client.get_damage_taken_data.return_value = []
    client.get_damage_done_data.return_value = []
    client.get_cast_events_paginated.return_value = []
    client.get_buffs_table.return_value = {"data": {"auras": []}}
    client.get_cast_table.return_value = []
    client.get_damage_taken_table.return_value = []
    client.get_damage_done_table.return_value = []
    client.get_master_data.return_value = []
    client.get_fights.return_value = []
    client.get_encounter_table.return_value = []
    return client


@pytest.fixture
def db(tmp_path):
    from warcraftlogs_client.database import PerformanceDB
    db_path = str(tmp_path / "test.db")
    with PerformanceDB(db_path) as database:
        yield database


@pytest.fixture
def config_file(tmp_path):
    cfg = {
        "client_id": "test_id",
        "client_secret": "test_secret",
        "report_id": "test_report",
        "guild_id": 12345,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    return str(path)
