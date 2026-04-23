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


class TestCaseInsensitiveNameMatching:
    """Character name lookups must be case-insensitive.

    The WCL API may return "Hadur" while the locally imported raid data
    stores the name as "hadur" or "HADUR".  All query methods should
    find the character regardless of casing.
    """

    def test_get_character_history_case_insensitive(self, db, sample_raid_analysis):
        """Querying with different casing should still find the character."""
        db.import_raid(sample_raid_analysis)
        # Data was imported with name "HolyPriest"
        for variant in ("holypriest", "HOLYPRIEST", "holyPRIEST", "HolyPriest"):
            history = db.get_character_history(variant)
            assert history is not None, f"Failed to find character with name '{variant}'"
            assert history.total_raids == 1

    def test_healer_trend_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_healer_trend("holypriest")
        assert len(trend) == 1
        assert trend[0]["total_healing"] == 500_000

    def test_tank_trend_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_tank_trend("TANKWARRIOR")
        assert len(trend) == 1
        assert trend[0]["total_damage_taken"] == 800_000

    def test_dps_trend_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_dps_trend("stabbyrogue")
        assert len(trend) == 1
        assert trend[0]["total_damage"] == 400_000

    def test_consumable_trend_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_consumable_trend("HOLYPRIEST")
        assert len(trend) >= 1

    def test_consumable_summary_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        summary = db.get_consumable_summary("holypriest")
        assert len(summary) >= 1

    def test_character_consistency_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        result = db.get_character_consistency("holypriest")
        assert result != {}
        assert result["name"] == "holypriest"

    def test_character_personal_bests_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        bests = db.get_character_personal_bests("HOLYPRIEST")
        assert len(bests) > 0

    def test_character_consumable_compliance_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        compliance = db.get_character_consumable_compliance("holypriest")
        assert compliance != {}
        assert compliance["total_raids"] > 0

    def test_character_spider_data_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        spider = db.get_character_spider_data("holypriest")
        assert spider != {}

    def test_character_raid_calendar_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        calendar = db.get_character_raid_calendar("holypriest")
        assert len(calendar) >= 1

    def test_healer_spell_trend_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_healer_spell_trend("holypriest")
        assert len(trend) >= 1

    def test_dps_ability_trend_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        trend = db.get_dps_ability_trend("stabbyrogue")
        assert len(trend) >= 1

    def test_compare_characters_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        result = db.compare_characters(["holypriest"], "healer")
        assert len(result) == 1

    def test_upsert_character_case_insensitive_dedup(self, db, sample_raid_analysis):
        """Importing with different casing should NOT create a duplicate character."""
        db.import_raid(sample_raid_analysis)
        # Import again with a modified analysis that has different casing
        modified = RaidAnalysis(
            metadata=RaidMetadata(
                report_id="def456",
                title="Second Raid",
                owner="TestGuild",
                start_time=1_700_010_000_000,
                end_time=1_700_013_600_000,
            ),
            composition=RaidComposition(
                tanks=[], healers=[
                    PlayerIdentity(name="HOLYPRIEST", player_class="Priest",
                                   source_id=1, role="healer"),
                ], melee=[], ranged=[],
            ),
            healers=[
                HealerPerformance(
                    name="HOLYPRIEST", player_class="Priest", source_id=1,
                    total_healing=600_000, total_overhealing=120_000,
                    spells=[], fear_ward_casts=0,
                ),
            ],
            tanks=[],
            dps=[],
            consumables=[],
        )
        db.import_raid(modified)

        # Should only have one character entry, not two
        conn = db._get_conn()
        rows = conn.execute(
            "SELECT * FROM characters WHERE name = ? COLLATE NOCASE",
            ("HolyPriest",),
        ).fetchall()
        assert len(rows) == 1

        # Both raids should be associated with that one character
        history = db.get_character_history("holypriest")
        assert history is not None
        assert history.total_raids == 2

    def test_add_raid_group_member_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        group = db.create_raid_group("TestGroup")
        result = db.add_raid_group_member(group.id, "holypriest")
        assert result is True
        groups = db.get_groups_for_character("HOLYPRIEST")
        assert "TestGroup" in groups

    def test_remove_raid_group_member_case_insensitive(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        group = db.create_raid_group("TestGroup")
        db.add_raid_group_member(group.id, "HolyPriest")
        db.remove_raid_group_member(group.id, "HOLYPRIEST")
        groups = db.get_groups_for_character("HolyPriest")
        assert "TestGroup" not in groups


class TestContextManager:
    def test_context_manager_protocol(self, tmp_path):
        db_path = str(tmp_path / "ctx.db")
        with PerformanceDB(db_path) as db:
            assert db._conn is not None
        assert db._conn is None
