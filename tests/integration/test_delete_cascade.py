"""Verify cascading deletes: removing a raid cleans all related data."""

import pytest

from warcraftlogs_client.models import (
    ConsumableUsage,
    EncounterPerformance,
    EncounterSummary,
    InterruptUsage,
)

from .conftest import make_analysis


@pytest.mark.integration
class TestDeleteCascade:
    def test_delete_removes_all_performance_data(self, db):
        """Import a raid, delete it, verify all related tables are empty."""
        consumables = [
            ConsumableUsage(
                player_name="HolyPriest",
                player_role="healer",
                report_id="del_001",
                consumable_name="Super Mana Potion",
                count=2,
            ),
        ]
        interrupts = [
            InterruptUsage(
                player_name="StabbyRogue",
                player_class="Rogue",
                source_id=3,
                spell_id=1766,
                spell_name="Kick",
                count=4,
            ),
        ]
        encounters = [
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
                        total_healing=50_000,
                    ),
                ],
            ),
        ]
        analysis = make_analysis(
            report_id="del_001",
            consumables=consumables,
            interrupts=interrupts,
            encounters=encounters,
        )
        db.import_raid(analysis)

        # Confirm data exists before delete
        assert db.is_raid_imported("del_001") is True
        result = db.get_raid_analysis("del_001")
        assert result is not None
        assert len(result.healers) == 1
        assert len(result.consumables) == 1
        assert len(result.interrupts) == 1
        assert len(result.encounters) == 1

        db.delete_raid("del_001")

        # Raid should be gone
        assert db.is_raid_imported("del_001") is False
        assert db.get_raid_analysis("del_001") is None

        # Verify no orphaned data in raid list
        raids = db.get_raid_list()
        assert all(r["report_id"] != "del_001" for r in raids)

    def test_delete_preserves_characters(self, db):
        """Characters should survive raid deletion (they may appear in other raids)."""
        analysis = make_analysis(
            report_id="del_char_001",
            healer_name="SurvivorHealer",
        )
        db.import_raid(analysis)

        # Import a second raid with the same character
        analysis2 = make_analysis(
            report_id="del_char_002",
            healer_name="SurvivorHealer",
        )
        db.import_raid(analysis2)

        # Delete first raid
        db.delete_raid("del_char_001")

        # Character should still be queryable via the second raid
        history = db.get_character_history("SurvivorHealer")
        assert history is not None
        assert history.total_raids == 1

    def test_delete_nonexistent_raid(self, db):
        """Deleting a report_id that doesn't exist should not crash."""
        # Should not raise any exception
        db.delete_raid("nonexistent_report_999")

        # DB should still be functional
        raids = db.get_raid_list()
        assert isinstance(raids, list)

    def test_delete_one_of_two_raids(self, db):
        """Import 2 raids, delete 1. Verify the other raid's data is intact."""
        analysis1 = make_analysis(
            report_id="keep_001",
            title="Keep This Raid",
            healer_name="KeepHealer",
            healer_healing=400_000,
        )
        analysis2 = make_analysis(
            report_id="remove_001",
            title="Remove This Raid",
            healer_name="RemoveHealer",
            healer_healing=300_000,
        )

        db.import_raid(analysis1)
        db.import_raid(analysis2)

        # Both should exist
        assert db.is_raid_imported("keep_001") is True
        assert db.is_raid_imported("remove_001") is True

        # Delete one
        db.delete_raid("remove_001")

        # The kept raid should be fully intact
        assert db.is_raid_imported("keep_001") is True
        assert db.is_raid_imported("remove_001") is False

        kept = db.get_raid_analysis("keep_001")
        assert kept is not None
        assert kept.metadata.title == "Keep This Raid"
        assert len(kept.healers) == 1
        assert kept.healers[0].name == "KeepHealer"
        assert kept.healers[0].total_healing == 400_000

        # Removed healer should have no raid history
        removed_history = db.get_character_history("RemoveHealer")
        assert removed_history is not None
        assert removed_history.total_raids == 0

    def test_delete_cleans_encounters(self, db):
        """Encounter data should be cleaned up when the parent raid is deleted."""
        encounters = [
            EncounterSummary(
                encounter_id=653,
                name="Moroes",
                start_time=1_700_000_300_000,
                end_time=1_700_000_400_000,
                duration_ms=100_000,
                players=[
                    EncounterPerformance(
                        name="HolyPriest",
                        player_class="Priest",
                        source_id=1,
                        role="healer",
                        total_healing=30_000,
                    ),
                ],
            ),
        ]
        analysis = make_analysis(report_id="del_enc_001", encounters=encounters)
        db.import_raid(analysis)

        result = db.get_raid_analysis("del_enc_001")
        assert result is not None
        assert len(result.encounters) == 1

        db.delete_raid("del_enc_001")

        assert db.get_raid_analysis("del_enc_001") is None
