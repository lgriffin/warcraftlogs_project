"""Tests for reference reports: isolation, comparison, and label management."""

import pytest

from warcraftlogs_client.models import (
    ConsumableUsage,
    DPSPerformance,
    EncounterPerformance,
    EncounterSummary,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)


def _make_analysis(report_id, title="Test Raid", healer_name="Healer1",
                   tank_name="Tank1", dps_name="DPS1",
                   encounter_id=None, encounter_name="Attumen"):
    metadata = RaidMetadata(
        report_id=report_id, title=title, owner="Owner",
        start_time=1_700_000_000_000, end_time=1_700_003_600_000,
    )
    comp = RaidComposition(
        tanks=[PlayerIdentity(name=tank_name, player_class="Warrior",
                              source_id=1, role="tank")],
        healers=[PlayerIdentity(name=healer_name, player_class="Priest",
                                source_id=2, role="healer")],
        melee=[PlayerIdentity(name=dps_name, player_class="Rogue",
                              source_id=3, role="melee")],
        ranged=[],
    )
    healers = [HealerPerformance(
        name=healer_name, player_class="Priest", source_id=2,
        total_healing=500_000, total_overhealing=100_000,
        spells=[], dispels=[], resources=[], fear_ward_casts=0,
    )]
    tanks = [TankPerformance(
        name=tank_name, player_class="Warrior", source_id=1,
        total_damage_taken=800_000, total_mitigated=600_000,
        damage_taken_breakdown=[], abilities_used=[],
    )]
    dps = [DPSPerformance(
        name=dps_name, player_class="Rogue", source_id=3,
        role="melee", total_damage=400_000, abilities=[],
    )]
    encounters = []
    if encounter_id is not None:
        encounters = [EncounterSummary(
            encounter_id=encounter_id, name=encounter_name,
            start_time=12000, end_time=180000, duration_ms=168000,
            players=[
                EncounterPerformance(
                    name=dps_name, player_class="Rogue", source_id=3,
                    role="melee", total_damage=150_000,
                    total_healing=0, total_damage_taken=20_000),
                EncounterPerformance(
                    name=healer_name, player_class="Priest", source_id=2,
                    role="healer", total_damage=5_000,
                    total_healing=120_000, total_damage_taken=15_000),
                EncounterPerformance(
                    name=tank_name, player_class="Warrior", source_id=1,
                    role="tank", total_damage=30_000,
                    total_healing=0, total_damage_taken=200_000),
            ],
        )]
    return RaidAnalysis(
        metadata=metadata, composition=comp,
        healers=healers, tanks=tanks, dps=dps,
        consumables=[], encounters=encounters,
    )


class TestReferenceImport:
    def test_import_as_reference(self, db):
        analysis = _make_analysis("ref001", title="Ref Raid")
        db.import_raid(analysis, source="reference")

        guild_raids = db.get_raid_list()
        assert len(guild_raids) == 0

        ref_raids = db.get_reference_raids()
        assert len(ref_raids) == 1
        assert ref_raids[0]["report_id"] == "ref001"
        assert ref_raids[0]["title"] == "Ref Raid"

    def test_default_source_is_guild(self, db):
        analysis = _make_analysis("guild001", title="Guild Raid")
        db.import_raid(analysis)

        guild_raids = db.get_raid_list()
        assert len(guild_raids) == 1

        ref_raids = db.get_reference_raids()
        assert len(ref_raids) == 0

    def test_get_raid_source(self, db):
        db.import_raid(_make_analysis("g1"), source="guild")
        db.import_raid(_make_analysis("r1"), source="reference")

        assert db.get_raid_source("g1") == "guild"
        assert db.get_raid_source("r1") == "reference"
        assert db.get_raid_source("nonexistent") is None


class TestGuildIsolation:
    def test_characters_exclude_reference_only(self, db):
        db.import_raid(_make_analysis("g1", healer_name="GuildHealer",
                                      tank_name="GuildTank",
                                      dps_name="GuildDPS"), source="guild")
        db.import_raid(_make_analysis("r1", healer_name="RefHealer",
                                      tank_name="RefTank",
                                      dps_name="RefDPS"), source="reference")

        chars = db.get_all_characters()
        names = [c.name for c in chars]
        assert "GuildHealer" in names
        assert "GuildTank" in names
        assert "GuildDPS" in names
        assert "RefHealer" not in names
        assert "RefTank" not in names
        assert "RefDPS" not in names

    def test_character_history_guild_only(self, db):
        db.import_raid(_make_analysis("g1", healer_name="SharedHealer"),
                       source="guild")
        db.import_raid(_make_analysis("r1", healer_name="SharedHealer"),
                       source="reference")

        history = db.get_character_history("SharedHealer")
        assert history is not None
        assert history.total_raids == 1

    def test_raid_list_excludes_reference(self, db):
        db.import_raid(_make_analysis("g1", title="Guild Run"), source="guild")
        db.import_raid(_make_analysis("r1", title="Ref Run"), source="reference")

        raids = db.get_raid_list()
        assert len(raids) == 1
        assert raids[0]["title"] == "Guild Run"

    def test_imported_report_codes_returns_all(self, db):
        db.import_raid(_make_analysis("g1"), source="guild")
        db.import_raid(_make_analysis("r1"), source="reference")

        codes = db.get_imported_report_codes()
        assert "g1" in codes
        assert "r1" in codes

    def test_distinct_zones_filters_by_source(self, db):
        g_analysis = _make_analysis("g1")
        g_analysis.metadata = RaidMetadata(
            report_id="g1", title="G", owner="O",
            start_time=1_700_000_000_000, end_time=1_700_003_600_000,
            zone="Karazhan",
        )
        r_analysis = _make_analysis("r1")
        r_analysis.metadata = RaidMetadata(
            report_id="r1", title="R", owner="O",
            start_time=1_700_000_000_000, end_time=1_700_003_600_000,
            zone="Gruul's Lair",
        )
        db.import_raid(g_analysis, source="guild")
        db.import_raid(r_analysis, source="reference")

        guild_zones = db.get_distinct_zones("guild")
        ref_zones = db.get_distinct_zones("reference")
        assert "Karazhan" in guild_zones
        assert "Gruul's Lair" not in guild_zones
        assert "Gruul's Lair" in ref_zones
        assert "Karazhan" not in ref_zones

    def test_healer_trend_guild_only(self, db):
        db.import_raid(_make_analysis("g1", healer_name="Healer1"),
                       source="guild")
        db.import_raid(_make_analysis("r1", healer_name="Healer1"),
                       source="reference")

        trend = db.get_healer_trend("Healer1")
        assert len(trend) == 1

    def test_dps_trend_guild_only(self, db):
        db.import_raid(_make_analysis("g1", dps_name="DPS1"),
                       source="guild")
        db.import_raid(_make_analysis("r1", dps_name="DPS1"),
                       source="reference")

        trend = db.get_dps_trend("DPS1")
        assert len(trend) == 1


class TestLabelManagement:
    def test_set_and_retrieve_label(self, db):
        db.import_raid(_make_analysis("r1"), source="reference")
        db.update_raid_label("r1", "Top guild Kara run")

        raids = db.get_reference_raids()
        assert len(raids) == 1
        assert raids[0]["label"] == "Top guild Kara run"


class TestComparisonAggregates:
    def test_comparison_aggregates_guild(self, db):
        db.import_raid(_make_analysis("g1"), source="guild")

        agg = db.get_comparison_aggregates("guild")
        assert agg["raid_count"] == 1
        assert agg["avg_healing"] == 500_000
        assert agg["avg_damage"] == 400_000

    def test_comparison_aggregates_reference(self, db):
        db.import_raid(_make_analysis("r1"), source="reference")

        agg = db.get_comparison_aggregates("reference")
        assert agg["raid_count"] == 1
        assert agg["avg_healing"] == 500_000

    def test_comparison_aggregates_empty(self, db):
        agg = db.get_comparison_aggregates("reference")
        assert agg["raid_count"] == 0
        assert agg["avg_healing"] is None

    def test_comparison_side_by_side(self, db):
        g = _make_analysis("g1", healer_name="GH")
        g.healers[0].total_healing = 600_000
        db.import_raid(g, source="guild")

        r = _make_analysis("r1", healer_name="RH")
        r.healers[0].total_healing = 400_000
        db.import_raid(r, source="reference")

        guild_agg = db.get_comparison_aggregates("guild")
        ref_agg = db.get_comparison_aggregates("reference")

        assert guild_agg["avg_healing"] == 600_000
        assert ref_agg["avg_healing"] == 400_000


class TestEncounterComparison:
    def test_common_encounters(self, db):
        db.import_raid(_make_analysis("g1", encounter_id=658), source="guild")
        db.import_raid(_make_analysis("r1", encounter_id=658), source="reference")

        common = db.get_common_encounters()
        assert len(common) == 1
        assert common[0]["name"] == "Attumen"

    def test_no_common_encounters(self, db):
        db.import_raid(_make_analysis("g1", encounter_id=658), source="guild")
        db.import_raid(_make_analysis("r1", encounter_id=659), source="reference")

        common = db.get_common_encounters()
        assert len(common) == 0

    def test_encounter_comparison_values(self, db):
        db.import_raid(_make_analysis("g1", encounter_id=658), source="guild")
        db.import_raid(_make_analysis("r1", encounter_id=658), source="reference")

        result = db.get_encounter_comparison(658)
        assert "guild" in result
        assert "reference" in result
        assert result["guild"]["kill_count"] == 1
        assert result["reference"]["kill_count"] == 1
        assert result["guild"]["avg_duration"] is not None


class TestDeleteRaid:
    def test_delete_reference_raid(self, db):
        db.import_raid(_make_analysis("g1"), source="guild")
        db.import_raid(_make_analysis("r1"), source="reference")

        db.delete_raid("r1")

        assert len(db.get_reference_raids()) == 0
        assert len(db.get_raid_list()) == 1

    def test_delete_guild_raid_unaffects_reference(self, db):
        db.import_raid(_make_analysis("g1"), source="guild")
        db.import_raid(_make_analysis("r1"), source="reference")

        db.delete_raid("g1")

        assert len(db.get_raid_list()) == 0
        assert len(db.get_reference_raids()) == 1


class TestMigration:
    def test_migrate_adds_source_column_to_existing_db(self, tmp_path):
        """Simulate an existing database without the source column."""
        import sqlite3
        from warcraftlogs_client.database import PerformanceDB

        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version VALUES (2);
            CREATE TABLE characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                player_class TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            CREATE TABLE raids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                owner TEXT,
                raid_date TEXT NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER,
                imported_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE healer_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL REFERENCES characters(id),
                raid_id INTEGER NOT NULL REFERENCES raids(id),
                total_healing INTEGER NOT NULL DEFAULT 0,
                total_overhealing INTEGER NOT NULL DEFAULT 0,
                overheal_percent REAL NOT NULL DEFAULT 0.0,
                fear_ward_casts INTEGER NOT NULL DEFAULT 0,
                total_dispels INTEGER NOT NULL DEFAULT 0,
                UNIQUE(character_id, raid_id)
            );
            CREATE TABLE tank_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL REFERENCES characters(id),
                raid_id INTEGER NOT NULL REFERENCES raids(id),
                total_damage_taken INTEGER NOT NULL DEFAULT 0,
                total_mitigated INTEGER NOT NULL DEFAULT 0,
                mitigation_percent REAL NOT NULL DEFAULT 0.0,
                UNIQUE(character_id, raid_id)
            );
            CREATE TABLE dps_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL REFERENCES characters(id),
                raid_id INTEGER NOT NULL REFERENCES raids(id),
                role TEXT NOT NULL CHECK(role IN ('melee', 'ranged')),
                total_damage INTEGER NOT NULL DEFAULT 0,
                UNIQUE(character_id, raid_id)
            );
            CREATE TABLE consumable_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL REFERENCES characters(id),
                raid_id INTEGER NOT NULL REFERENCES raids(id),
                consumable_name TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                timestamps TEXT DEFAULT NULL,
                UNIQUE(character_id, raid_id, consumable_name)
            );
        """)
        conn.execute(
            "INSERT INTO raids (report_id, title, owner, raid_date, start_time, end_time) "
            "VALUES ('old1', 'Old Raid', 'Owner', '2024-01-01', 1700000000000, 1700003600000)"
        )
        conn.commit()
        conn.close()

        with PerformanceDB(db_path) as db:
            raids = db.get_raid_list()
            assert len(raids) == 1
            assert db.get_raid_source("old1") == "guild"

            db.import_raid(_make_analysis("ref1"), source="reference")
            assert len(db.get_raid_list()) == 1
            assert len(db.get_reference_raids()) == 1


class TestReimportProtection:
    def test_same_report_keeps_original_source(self, db):
        db.import_raid(_make_analysis("x1", title="Original"), source="guild")
        db.import_raid(_make_analysis("x1", title="Updated"), source="reference")

        assert db.get_raid_source("x1") == "guild"
        guild_raids = db.get_raid_list()
        assert len(guild_raids) == 1
        assert guild_raids[0]["title"] == "Updated"


class TestGuildRaidsForComparison:
    def test_returns_zone_and_size(self, db):
        a = _make_analysis("g1", title="Guild Raid")
        a.metadata.zone = "Karazhan"
        db.import_raid(a, source="guild")

        raids = db.get_guild_raids_for_comparison()
        assert len(raids) == 1
        assert raids[0]["report_id"] == "g1"
        assert raids[0]["zone"] == "Karazhan"
        assert "raid_size" in raids[0]

    def test_excludes_reference(self, db):
        db.import_raid(_make_analysis("g1"), source="guild")
        db.import_raid(_make_analysis("r1"), source="reference")

        raids = db.get_guild_raids_for_comparison()
        assert len(raids) == 1
        assert raids[0]["report_id"] == "g1"


class TestHeadToHeadHelpers:
    def test_compute_class_performance_groups_by_class_role(self):
        from warcraftlogs_client.gui.reference_view import _compute_class_performance

        analysis = _make_analysis("test1")
        analysis.dps.append(DPSPerformance(
            name="DPS2", player_class="Rogue", source_id=4,
            role="melee", total_damage=600_000, abilities=[],
        ))
        result = _compute_class_performance(analysis)

        rogue_melee = [r for r in result if r["class"] == "Rogue" and r["role"] == "melee"]
        assert len(rogue_melee) == 1
        assert rogue_melee[0]["count"] == 2
        assert rogue_melee[0]["avg_metric"] == 500_000

        priest_healer = [r for r in result if r["class"] == "Priest" and r["role"] == "healer"]
        assert len(priest_healer) == 1
        assert priest_healer[0]["count"] == 1

    def test_compute_consumable_summary(self):
        from warcraftlogs_client.gui.reference_view import _compute_consumable_summary

        analysis = _make_analysis("test1")
        analysis.consumables = [
            ConsumableUsage(player_name="P1", player_role="melee",
                            report_id="test1", consumable_name="Flask of the Titans",
                            count=2, timestamps=[]),
            ConsumableUsage(player_name="P2", player_role="melee",
                            report_id="test1", consumable_name="Flask of the Titans",
                            count=1, timestamps=[]),
            ConsumableUsage(player_name="P1", player_role="melee",
                            report_id="test1", consumable_name="Mana Potion",
                            count=3, timestamps=[]),
        ]
        result = _compute_consumable_summary(analysis)

        assert result["Flask of the Titans"]["total_uses"] == 3
        assert result["Flask of the Titans"]["unique_users"] == 2
        assert result["Mana Potion"]["total_uses"] == 3
        assert result["Mana Potion"]["unique_users"] == 1

    def test_match_encounters_finds_shared(self):
        from warcraftlogs_client.gui.reference_view import _match_encounters

        guild = _make_analysis("g1", encounter_id=658)
        ref = _make_analysis("r1", encounter_id=658)

        rows = _match_encounters(guild, ref)
        assert len(rows) == 1
        assert rows[0]["name"] == "Attumen"
        assert rows[0]["guild"]["total_damage"] > 0
        assert rows[0]["ref"]["total_damage"] > 0

    def test_match_encounters_no_overlap(self):
        from warcraftlogs_client.gui.reference_view import _match_encounters

        guild = _make_analysis("g1", encounter_id=658, encounter_name="Attumen")
        ref = _make_analysis("r1", encounter_id=999, encounter_name="Curator")

        rows = _match_encounters(guild, ref)
        assert len(rows) == 0

    def test_match_encounters_name_fallback(self):
        """Same boss name but different encounter_id still matches via fallback."""
        from warcraftlogs_client.gui.reference_view import _match_encounters

        guild = _make_analysis("g1", encounter_id=658)
        ref = _make_analysis("r1", encounter_id=999)

        rows = _match_encounters(guild, ref)
        assert len(rows) == 1
        assert rows[0]["name"] == "Attumen"

    def test_compute_class_performance_multi_role(self):
        """Paladin appearing as both healer and tank gets separate rows."""
        from warcraftlogs_client.gui.reference_view import _compute_class_performance

        analysis = _make_analysis("test1")
        analysis.healers.append(HealerPerformance(
            name="PalaH", player_class="Paladin", source_id=10,
            total_healing=300_000, total_overhealing=50_000,
            spells=[], dispels=[], resources=[], fear_ward_casts=0,
        ))
        analysis.tanks.append(TankPerformance(
            name="PalaT", player_class="Paladin", source_id=11,
            total_damage_taken=500_000, total_mitigated=350_000,
            damage_taken_breakdown=[], abilities_used=[],
        ))
        result = _compute_class_performance(analysis)

        paladin_rows = [r for r in result if r["class"] == "Paladin"]
        roles = {r["role"] for r in paladin_rows}
        assert "healer" in roles
        assert "tank" in roles
