"""Reference report comparison workflow tests."""

import pytest

from warcraftlogs_client.models import (
    EncounterPerformance,
    EncounterSummary,
)

from .conftest import make_analysis


@pytest.mark.integration
class TestReferenceWorkflow:
    def test_import_guild_and_reference(self, db):
        """Import a guild raid and a reference raid. Both should be queryable."""
        guild_analysis = make_analysis(
            report_id="guild_ref_001",
            title="Guild Kara Run",
            owner="OurGuild",
            healer_healing=400_000,
        )
        ref_analysis = make_analysis(
            report_id="ref_ref_001",
            title="Top Guild Kara",
            owner="EliteGuild",
            healer_healing=800_000,
        )

        db.import_raid(guild_analysis, source="guild")
        db.import_raid(ref_analysis, source="reference")

        # Both should be marked as imported
        assert db.is_raid_imported("guild_ref_001") is True
        assert db.is_raid_imported("ref_ref_001") is True

        # Both should be retrievable
        guild_result = db.get_raid_analysis("guild_ref_001")
        ref_result = db.get_raid_analysis("ref_ref_001")
        assert guild_result is not None
        assert ref_result is not None
        assert guild_result.healers[0].total_healing == 400_000
        assert ref_result.healers[0].total_healing == 800_000

    def test_reference_isolation(self, db):
        """Reference raids should not appear in guild-only queries (get_raid_list)."""
        guild_analysis = make_analysis(
            report_id="iso_guild_001",
            title="Guild Run",
        )
        ref_analysis = make_analysis(
            report_id="iso_ref_001",
            title="Reference Run",
        )

        db.import_raid(guild_analysis, source="guild")
        db.import_raid(ref_analysis, source="reference")

        # get_raid_list returns only guild raids
        raid_list = db.get_raid_list()
        report_ids = [r["report_id"] for r in raid_list]
        assert "iso_guild_001" in report_ids
        assert "iso_ref_001" not in report_ids

        # get_reference_raids returns only reference raids
        ref_list = db.get_reference_raids()
        ref_report_ids = [r["report_id"] for r in ref_list]
        assert "iso_ref_001" in ref_report_ids
        assert "iso_guild_001" not in ref_report_ids

    def test_comparison_queries(self, db):
        """With both guild and reference raids imported, comparison aggregates should work."""
        # Create encounters for both guild and reference raids
        guild_encounters = [
            EncounterSummary(
                encounter_id=652,
                name="Attumen the Huntsman",
                start_time=1_700_000_100_000,
                end_time=1_700_000_200_000,
                duration_ms=100_000,
                players=[
                    EncounterPerformance(
                        name="HolyPriest",
                        player_class="Priest",
                        source_id=1,
                        role="healer",
                        total_healing=40_000,
                        total_damage=0,
                    ),
                ],
            ),
        ]
        ref_encounters = [
            EncounterSummary(
                encounter_id=652,
                name="Attumen the Huntsman",
                start_time=1_700_000_100_000,
                end_time=1_700_000_180_000,
                duration_ms=80_000,
                players=[
                    EncounterPerformance(
                        name="RefHealer",
                        player_class="Priest",
                        source_id=1,
                        role="healer",
                        total_healing=60_000,
                        total_damage=0,
                    ),
                ],
            ),
        ]

        guild_analysis = make_analysis(
            report_id="cmp_guild_001",
            title="Guild Kara",
            healer_healing=400_000,
            encounters=guild_encounters,
        )
        ref_analysis = make_analysis(
            report_id="cmp_ref_001",
            title="Reference Kara",
            healer_name="RefHealer",
            healer_healing=600_000,
            encounters=ref_encounters,
        )

        db.import_raid(guild_analysis, source="guild")
        db.import_raid(ref_analysis, source="reference")

        # Comparison aggregates for guild vs reference
        guild_agg = db.get_comparison_aggregates(source="guild")
        ref_agg = db.get_comparison_aggregates(source="reference")

        assert guild_agg is not None
        assert ref_agg is not None

        # Encounter comparison for the shared boss
        encounter_cmp = db.get_encounter_comparison(encounter_id=652)
        assert "guild" in encounter_cmp
        assert "reference" in encounter_cmp

    def test_reference_character_history_isolation(self, db):
        """Character history for guild source should not include reference raid data."""
        guild_analysis = make_analysis(
            report_id="hist_guild_001",
            healer_name="CrossHealer",
            healer_healing=300_000,
        )
        ref_analysis = make_analysis(
            report_id="hist_ref_001",
            healer_name="CrossHealer",
            healer_healing=900_000,
        )

        db.import_raid(guild_analysis, source="guild")
        db.import_raid(ref_analysis, source="reference")

        # Default get_character_history uses source="guild"
        history = db.get_character_history("CrossHealer", source="guild")
        assert history is not None
        assert history.total_raids == 1
        assert history.avg_healing == pytest.approx(300_000.0, rel=1e-2)

        # Reference source should show the reference data
        ref_history = db.get_character_history("CrossHealer", source="reference")
        assert ref_history is not None
        assert ref_history.total_raids == 1
        assert ref_history.avg_healing == pytest.approx(900_000.0, rel=1e-2)

    def test_delete_reference_preserves_guild(self, db):
        """Deleting a reference raid should not affect guild data."""
        guild_analysis = make_analysis(
            report_id="dref_guild_001",
            title="Guild Run",
            healer_name="SharedName",
            healer_healing=500_000,
        )
        ref_analysis = make_analysis(
            report_id="dref_ref_001",
            title="Reference Run",
            healer_name="SharedName",
            healer_healing=700_000,
        )

        db.import_raid(guild_analysis, source="guild")
        db.import_raid(ref_analysis, source="reference")

        db.delete_raid("dref_ref_001")

        # Guild data intact
        assert db.is_raid_imported("dref_guild_001") is True
        guild_result = db.get_raid_analysis("dref_guild_001")
        assert guild_result is not None
        assert guild_result.healers[0].total_healing == 500_000

        # Reference gone
        assert db.is_raid_imported("dref_ref_001") is False
