"""Shared fixtures for GUI widget tests using pytest-qt."""

import json
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.models import (
    ConsumableUsage,
    DPSPerformance,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)


@pytest.fixture
def mock_config(tmp_path):
    """Create a valid config file and patch load_config to use it."""
    cfg = {
        "client_id": "test_id",
        "client_secret": "test_secret",
        "report_id": "test_report",
        "guild_id": 12345,
        "wcl_api_url": "https://www.warcraftlogs.com/api/v2/client",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    with patch("warcraftlogs_client.config.load_config", return_value=cfg):
        yield cfg


@pytest.fixture
def mock_db(tmp_path):
    """Create a test database in tmp_path."""
    db_path = str(tmp_path / "test.db")
    with PerformanceDB(db_path) as db:
        yield db


@pytest.fixture
def sample_analysis():
    """Build a complete RaidAnalysis for GUI testing."""
    metadata = RaidMetadata(
        report_id="gui_test_001",
        title="Karazhan Full Clear",
        owner="TestGuild",
        start_time=1_700_000_000_000,
        end_time=1_700_003_600_000,
    )
    composition = RaidComposition(
        tanks=[PlayerIdentity(name="TankWarrior", player_class="Warrior", source_id=2, role="tank")],
        healers=[PlayerIdentity(name="HolyPriest", player_class="Priest", source_id=1, role="healer")],
        melee=[PlayerIdentity(name="StabbyRogue", player_class="Rogue", source_id=3, role="melee")],
        ranged=[PlayerIdentity(name="FrostMage", player_class="Mage", source_id=4, role="ranged")],
    )
    return RaidAnalysis(
        metadata=metadata,
        composition=composition,
        healers=[
            HealerPerformance(
                name="HolyPriest",
                player_class="Priest",
                source_id=1,
                total_healing=500_000,
                total_overhealing=100_000,
                spells=[SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=50, total_amount=300_000)],
                dispels=[],
                resources=[],
                fear_ward_casts=5,
            )
        ],
        tanks=[
            TankPerformance(
                name="TankWarrior",
                player_class="Warrior",
                source_id=2,
                total_damage_taken=800_000,
                total_mitigated=600_000,
                damage_taken_breakdown=[],
                abilities_used=[],
            )
        ],
        dps=[
            DPSPerformance(
                name="StabbyRogue",
                player_class="Rogue",
                source_id=3,
                role="melee",
                total_damage=400_000,
                abilities=[],
            )
        ],
        consumables=[
            ConsumableUsage(
                player_name="HolyPriest",
                player_role="healer",
                report_id="gui_test_001",
                consumable_name="Super Mana Potion",
                count=3,
                timestamps=[60_000, 180_000, 300_000],
            ),
        ],
    )


@pytest.fixture
def populated_db(mock_db, sample_analysis):
    """A database with one imported raid."""
    mock_db.import_raid(sample_analysis)
    return mock_db
