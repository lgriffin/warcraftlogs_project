"""Tests for PerformanceDB — SQLite persistence with real temp databases."""

import json

import pytest

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.models import (
    ConsumableUsage,
    DPSPerformance,
    DispelUsage,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)


class TestSchemaCreation:
    def test_tables_exist(self, db):
        conn = db._get_conn()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "schema_version", "characters", "raids",
            "healer_performance", "healer_spells",
            "tank_performance", "tank_damage_taken", "tank_abilities",
            "dps_performance", "dps_abilities", "consumable_usage",
        }
        assert expected.issubset(tables)


class TestImportRaid:
    def test_creates_records(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        assert db.is_raid_imported("abc123")

    def test_idempotent_upsert(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        db.import_raid(sample_raid_analysis)
        raids = db.get_raid_list()
        assert len(raids) == 1

    def test_healer_stored(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        history = db.get_character_history("HolyPriest")
        assert history is not None
        assert history.player_class == "Priest"
        assert history.avg_healing is not None
        assert history.avg_healing > 0

    def test_tank_stored(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        history = db.get_character_history("TankWarrior")
        assert history is not None
        assert history.avg_mitigation_percent is not None

    def test_dps_stored(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        history = db.get_character_history("StabbyRogue")
        assert history is not None
        assert history.avg_damage is not None

    def test_consumables_stored(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        history = db.get_character_history("HolyPriest")
        assert history.total_consumables_used == 3


class TestIsRaidImported:
    def test_false_when_not_imported(self, db):
        assert db.is_raid_imported("nonexistent") is False

    def test_true_after_import(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        assert db.is_raid_imported("abc123") is True


class TestCharacterHistory:
    def test_found(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        h = db.get_character_history("HolyPriest")
        assert h is not None
        assert h.total_raids == 1
        assert h.first_seen is not None
        assert h.last_seen is not None

    def test_not_found(self, db):
        assert db.get_character_history("Nobody") is None


class TestTrends:
    def test_healer_trend(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_healer_trend("HolyPriest")
        assert len(trend) == 1
        assert trend[0]["total_healing"] == 500_000

    def test_tank_trend(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_tank_trend("TankWarrior")
        assert len(trend) == 1
        assert trend[0]["total_damage_taken"] == 800_000

    def test_dps_trend(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_dps_trend("StabbyRogue")
        assert len(trend) == 1
        assert trend[0]["total_damage"] == 400_000

    def test_consumable_trend(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_consumable_trend("HolyPriest")
        assert len(trend) >= 1
        assert trend[0]["consumable_name"] == "Super Mana Potion"
        assert trend[0]["count"] == 3


class TestDeleteRaid:
    def test_removes_all_data(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        db.delete_raid("abc123")
        assert db.is_raid_imported("abc123") is False
        assert db.get_healer_trend("HolyPriest") == []

    def test_nonexistent_no_error(self, db):
        db.delete_raid("does_not_exist")


class TestGetAllCharacters:
    def test_returns_all(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        chars = db.get_all_characters()
        names = {c.name for c in chars}
        assert "HolyPriest" in names
        assert "TankWarrior" in names
        assert "StabbyRogue" in names


class TestRaidList:
    def test_returns_raids(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        raids = db.get_raid_list()
        assert len(raids) == 1
        assert raids[0]["report_id"] == "abc123"
        assert raids[0]["title"] == "Karazhan Clear"


class TestRaidRoster:
    def test_returns_players(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        roster = db.get_raid_roster("abc123")
        names = {r["name"] for r in roster}
        assert "HolyPriest" in names
        assert "TankWarrior" in names


class TestRaidAnalysisRoundtrip:
    def test_roundtrip(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        loaded = db.get_raid_analysis("abc123")
        assert loaded is not None
        assert loaded.metadata.report_id == "abc123"
        assert loaded.metadata.title == "Karazhan Clear"
        assert len(loaded.healers) == 1
        assert len(loaded.tanks) == 1
        assert len(loaded.dps) == 1
        assert loaded.healers[0].total_healing == 500_000

    def test_not_found(self, db):
        assert db.get_raid_analysis("nonexistent") is None


class TestClearAll:
    def test_clears_everything(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        db.clear_all()
        assert db.get_raid_list() == []
        assert db.get_all_characters() == []


class TestImportedReportCodes:
    def test_returns_codes(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        codes = db.get_imported_report_codes()
        assert "abc123" in codes

    def test_empty(self, db):
        assert db.get_imported_report_codes() == set()


class TestImportConsumables:
    def test_standalone_import(self, db, sample_raid_metadata):
        usage = [
            ConsumableUsage(
                player_name="Player1", player_role="dps",
                report_id="abc123", consumable_name="Dark Rune",
                count=2, timestamps=[30_000, 120_000],
            ),
        ]
        db.import_consumables(sample_raid_metadata, usage)
        history = db.get_character_history("Player1")
        assert history is not None
        assert history.total_consumables_used == 2


class TestContextManager:
    def test_context_manager_protocol(self, tmp_path):
        db_path = str(tmp_path / "ctx.db")
        with PerformanceDB(db_path) as db:
            assert db._conn is not None
        assert db._conn is None
