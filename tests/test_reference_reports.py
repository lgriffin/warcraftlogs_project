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


def _make_analysis(
    report_id,
    title="Test Raid",
    healer_name="Healer1",
    tank_name="Tank1",
    dps_name="DPS1",
    encounter_id=None,
    encounter_name="Attumen",
):
    metadata = RaidMetadata(
        report_id=report_id,
        title=title,
        owner="Owner",
        start_time=1_700_000_000_000,
        end_time=1_700_003_600_000,
    )
    comp = RaidComposition(
        tanks=[PlayerIdentity(name=tank_name, player_class="Warrior", source_id=1, role="tank")],
        healers=[PlayerIdentity(name=healer_name, player_class="Priest", source_id=2, role="healer")],
        melee=[PlayerIdentity(name=dps_name, player_class="Rogue", source_id=3, role="melee")],
        ranged=[],
    )
    healers = [
        HealerPerformance(
            name=healer_name,
            player_class="Priest",
            source_id=2,
            total_healing=500_000,
            total_overhealing=100_000,
            spells=[],
            dispels=[],
            resources=[],
            fear_ward_casts=0,
        )
    ]
    tanks = [
        TankPerformance(
            name=tank_name,
            player_class="Warrior",
            source_id=1,
            total_damage_taken=800_000,
            total_mitigated=600_000,
            damage_taken_breakdown=[],
            abilities_used=[],
        )
    ]
    dps = [
        DPSPerformance(
            name=dps_name,
            player_class="Rogue",
            source_id=3,
            role="melee",
            total_damage=400_000,
            abilities=[],
        )
    ]
    encounters = []
    if encounter_id is not None:
        encounters = [
            EncounterSummary(
                encounter_id=encounter_id,
                name=encounter_name,
                start_time=12000,
                end_time=180000,
                duration_ms=168000,
                players=[
                    EncounterPerformance(
                        name=dps_name,
                        player_class="Rogue",
                        source_id=3,
                        role="melee",
                        total_damage=150_000,
                        total_healing=0,
                        total_damage_taken=20_000,
                    ),
                    EncounterPerformance(
                        name=healer_name,
                        player_class="Priest",
                        source_id=2,
                        role="healer",
                        total_damage=5_000,
                        total_healing=120_000,
                        total_damage_taken=15_000,
                    ),
                    EncounterPerformance(
                        name=tank_name,
                        player_class="Warrior",
                        source_id=1,
                        role="tank",
                        total_damage=30_000,
                        total_healing=0,
                        total_damage_taken=200_000,
                    ),
                ],
            )
        ]
    return RaidAnalysis(
        metadata=metadata,
        composition=comp,
        healers=healers,
        tanks=tanks,
        dps=dps,
        consumables=[],
        encounters=encounters,
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
        db.import_raid(
            _make_analysis("g1", healer_name="GuildHealer", tank_name="GuildTank", dps_name="GuildDPS"), source="guild"
        )
        db.import_raid(
            _make_analysis("r1", healer_name="RefHealer", tank_name="RefTank", dps_name="RefDPS"), source="reference"
        )

        chars = db.get_all_characters()
        names = [c.name for c in chars]
        assert "GuildHealer" in names
        assert "GuildTank" in names
        assert "GuildDPS" in names
        assert "RefHealer" not in names
        assert "RefTank" not in names
        assert "RefDPS" not in names

    def test_character_history_guild_only(self, db):
        db.import_raid(_make_analysis("g1", healer_name="SharedHealer"), source="guild")
        db.import_raid(_make_analysis("r1", healer_name="SharedHealer"), source="reference")

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
            report_id="g1",
            title="G",
            owner="O",
            start_time=1_700_000_000_000,
            end_time=1_700_003_600_000,
            zone="Karazhan",
        )
        r_analysis = _make_analysis("r1")
        r_analysis.metadata = RaidMetadata(
            report_id="r1",
            title="R",
            owner="O",
            start_time=1_700_000_000_000,
            end_time=1_700_003_600_000,
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
        db.import_raid(_make_analysis("g1", healer_name="Healer1"), source="guild")
        db.import_raid(_make_analysis("r1", healer_name="Healer1"), source="reference")

        trend = db.get_healer_trend("Healer1")
        assert len(trend) == 1

    def test_dps_trend_guild_only(self, db):
        db.import_raid(_make_analysis("g1", dps_name="DPS1"), source="guild")
        db.import_raid(_make_analysis("r1", dps_name="DPS1"), source="reference")

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


try:
    import PySide6  # noqa: F401

    HAS_PYSIDE6 = True
except ImportError:
    HAS_PYSIDE6 = False

requires_pyside6 = pytest.mark.skipif(not HAS_PYSIDE6, reason="PySide6 not installed")


@requires_pyside6
class TestHeadToHeadHelpers:
    def test_compute_class_performance_groups_by_class_role(self):
        from warcraftlogs_client.gui.reference_view import _compute_class_performance

        analysis = _make_analysis("test1")
        analysis.dps.append(
            DPSPerformance(
                name="DPS2",
                player_class="Rogue",
                source_id=4,
                role="melee",
                total_damage=600_000,
                abilities=[],
            )
        )
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
            ConsumableUsage(
                player_name="P1",
                player_role="melee",
                report_id="test1",
                consumable_name="Flask of the Titans",
                count=2,
                timestamps=[],
            ),
            ConsumableUsage(
                player_name="P2",
                player_role="melee",
                report_id="test1",
                consumable_name="Flask of the Titans",
                count=1,
                timestamps=[],
            ),
            ConsumableUsage(
                player_name="P1",
                player_role="melee",
                report_id="test1",
                consumable_name="Mana Potion",
                count=3,
                timestamps=[],
            ),
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
        analysis.healers.append(
            HealerPerformance(
                name="PalaH",
                player_class="Paladin",
                source_id=10,
                total_healing=300_000,
                total_overhealing=50_000,
                spells=[],
                dispels=[],
                resources=[],
                fear_ward_casts=0,
            )
        )
        analysis.tanks.append(
            TankPerformance(
                name="PalaT",
                player_class="Paladin",
                source_id=11,
                total_damage_taken=500_000,
                total_mitigated=350_000,
                damage_taken_breakdown=[],
                abilities_used=[],
            )
        )
        result = _compute_class_performance(analysis)

        paladin_rows = [r for r in result if r["class"] == "Paladin"]
        roles = {r["role"] for r in paladin_rows}
        assert "healer" in roles
        assert "tank" in roles


@requires_pyside6
class TestBuildTimelineData:
    def test_returns_per_player_timestamps(self):
        from warcraftlogs_client.gui.analysis_helpers import build_timeline_data

        analysis = _make_analysis("t1")
        analysis.consumables = [
            ConsumableUsage(
                player_name="P1",
                player_role="melee",
                report_id="t1",
                consumable_name="Flask",
                count=2,
                timestamps=[5000, 120000],
            ),
            ConsumableUsage(
                player_name="P2",
                player_role="healer",
                report_id="t1",
                consumable_name="Flask",
                count=1,
                timestamps=[3000],
            ),
        ]
        rows = build_timeline_data(analysis, "Flask")
        assert len(rows) == 2
        assert rows[0]["player"] == "P2"
        assert rows[0]["timestamps"] == "00:03"
        assert rows[1]["player"] == "P1"
        assert rows[1]["timestamps"] == "00:05, 02:00"

    def test_returns_empty_for_missing_consumable(self):
        from warcraftlogs_client.gui.analysis_helpers import build_timeline_data

        analysis = _make_analysis("t1")
        analysis.consumables = []
        assert build_timeline_data(analysis, "Flask") == []


@requires_pyside6
class TestComputeEngineeringStats:
    def test_computes_min_median_max(self):
        from warcraftlogs_client.gui.analysis_helpers import compute_engineering_stats

        analysis = _make_analysis("e1")
        analysis.dps[0].abilities = [
            SpellUsage(spell_id=1, spell_name="Super Sapper Charge", casts=4, total_amount=12000),
        ]
        analysis.dps.append(
            DPSPerformance(
                name="DPS2",
                player_class="Rogue",
                source_id=4,
                role="melee",
                total_damage=500_000,
                abilities=[
                    SpellUsage(spell_id=1, spell_name="Super Sapper Charge", casts=4, total_amount=8000),
                ],
            )
        )
        result = compute_engineering_stats(analysis)
        assert "Super Sapper Charge" in result
        stats = result["Super Sapper Charge"]
        assert stats["total_casts"] == 8
        assert stats["total_damage"] == 20000
        assert stats["users"] == 2
        assert stats["min_avg"] == 2000
        assert stats["max_avg"] == 3000
        assert stats["median_avg"] == 2500

    def test_no_engineering_returns_empty(self):
        from warcraftlogs_client.gui.analysis_helpers import compute_engineering_stats

        analysis = _make_analysis("e1")
        analysis.dps[0].abilities = [
            SpellUsage(spell_id=1, spell_name="Sinister Strike", casts=50, total_amount=100000),
        ]
        assert compute_engineering_stats(analysis) == {}


@requires_pyside6
class TestClassifyConsumableUsage:
    def test_boss_vs_trash_classification(self):
        from warcraftlogs_client.gui.analysis_helpers import classify_consumable_usage

        analysis = _make_analysis("c1", encounter_id=658)
        analysis.consumables = [
            ConsumableUsage(
                player_name="P1",
                player_role="melee",
                report_id="c1",
                consumable_name="Destruction Potion",
                count=3,
                timestamps=[15000, 50000, 200000],
            ),
        ]
        result = classify_consumable_usage(analysis)
        assert "Destruction Potion" in result
        assert result["Destruction Potion"]["boss"] == 2
        assert result["Destruction Potion"]["trash"] == 1

    def test_no_encounters_all_trash(self):
        from warcraftlogs_client.gui.analysis_helpers import classify_consumable_usage

        analysis = _make_analysis("c1")
        analysis.consumables = [
            ConsumableUsage(
                player_name="P1",
                player_role="melee",
                report_id="c1",
                consumable_name="Flask",
                count=1,
                timestamps=[5000],
            ),
        ]
        result = classify_consumable_usage(analysis)
        assert result["Flask"]["boss"] == 0
        assert result["Flask"]["trash"] == 1


@requires_pyside6
class TestSharedEncounterScoping:
    def _guild_with_extra_encounters(self):
        """Guild with 3 encounters (2 shared + 1 extra), ref with 2."""
        from warcraftlogs_client.gui.analysis_helpers import (
            compute_shared_encounter_window,
            scope_analysis_to_window,
        )

        guild = _make_analysis("g1", encounter_id=658, encounter_name="Hydross")
        guild.encounters = [
            EncounterSummary(encounter_id=658, name="Hydross", start_time=10000, end_time=50000, duration_ms=40000),
            EncounterSummary(encounter_id=659, name="Lurker", start_time=80000, end_time=150000, duration_ms=70000),
            EncounterSummary(
                encounter_id=730, name="Void Reaver", start_time=300000, end_time=400000, duration_ms=100000
            ),
        ]
        guild.consumables = [
            ConsumableUsage(
                player_name="P1",
                player_role="melee",
                report_id="g1",
                consumable_name="Destruction Potion",
                count=4,
                timestamps=[9000, 15000, 90000, 350000],
            ),
        ]
        ref = _make_analysis("r1", encounter_id=658, encounter_name="Hydross")
        ref.encounters = [
            EncounterSummary(encounter_id=658, name="Hydross", start_time=5000, end_time=45000, duration_ms=40000),
            EncounterSummary(encounter_id=659, name="Lurker", start_time=60000, end_time=130000, duration_ms=70000),
        ]
        return guild, ref, compute_shared_encounter_window, scope_analysis_to_window

    def test_no_extra_encounters_returns_no_scoping(self):
        from warcraftlogs_client.gui.analysis_helpers import compute_shared_encounter_window

        guild = _make_analysis("g1", encounter_id=658, encounter_name="Hydross")
        ref = _make_analysis("r1", encounter_id=658, encounter_name="Hydross")
        result = compute_shared_encounter_window(guild, ref)
        assert result is not None
        assert result["has_extra_encounters"] is False

    def test_detects_extra_guild_encounters(self):
        guild, ref, compute, _ = self._guild_with_extra_encounters()
        result = compute(guild, ref)
        assert result["has_extra_encounters"] is True
        assert "Void Reaver" in result["guild_extra_names"]
        assert result["shared_count"] == 2
        assert result["window_start"] == 10000
        assert result["window_end"] == 150000

    def test_consumable_timestamps_filtered(self):
        guild, ref, compute, scope = self._guild_with_extra_encounters()
        info = compute(guild, ref)
        scoped = scope(guild, info["window_start"], info["window_end"])
        ts = scoped.consumables[0].timestamps
        assert 15000 in ts
        assert 90000 in ts
        assert 350000 not in ts
        assert scoped.consumables[0].count == len(ts)

    def test_scoping_does_not_mutate_original(self):
        guild, ref, compute, scope = self._guild_with_extra_encounters()
        original_count = guild.consumables[0].count
        original_ts = list(guild.consumables[0].timestamps)
        info = compute(guild, ref)
        scope(guild, info["window_start"], info["window_end"])
        assert guild.consumables[0].count == original_count
        assert guild.consumables[0].timestamps == original_ts

    def test_no_encounters_returns_none(self):
        from warcraftlogs_client.gui.analysis_helpers import compute_shared_encounter_window

        guild = _make_analysis("g1")
        ref = _make_analysis("r1")
        assert compute_shared_encounter_window(guild, ref) is None
