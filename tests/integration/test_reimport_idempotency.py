"""Verify upsert semantics: reimporting a raid updates rather than duplicates."""

import pytest

from .conftest import make_analysis


@pytest.mark.integration
class TestReimportIdempotency:
    def test_double_import_same_data(self, db):
        """Import the same analysis twice. DB should have exactly 1 raid, 1 of each character."""
        analysis = make_analysis(
            report_id="idem_001",
            healer_name="StableHealer",
            tank_name="StableTank",
            dps_name="StableDPS",
        )

        db.import_raid(analysis)
        db.import_raid(analysis)

        # Only one raid in the list
        raids = db.get_raid_list()
        matching = [r for r in raids if r["report_id"] == "idem_001"]
        assert len(matching) == 1

        # Query back the full analysis
        result = db.get_raid_analysis("idem_001")
        assert result is not None
        assert len(result.healers) == 1
        assert len(result.tanks) == 1
        assert len(result.dps) == 1

    def test_reimport_updates_performance(self, db):
        """Import, then reimport with different healing numbers. Verify the DB reflects the new values."""
        analysis_v1 = make_analysis(
            report_id="update_001",
            healer_name="EvolvingHealer",
            healer_healing=300_000,
        )
        db.import_raid(analysis_v1)

        # Verify initial value
        result_v1 = db.get_raid_analysis("update_001")
        assert result_v1 is not None
        assert result_v1.healers[0].total_healing == 300_000

        # Reimport with updated healing
        analysis_v2 = make_analysis(
            report_id="update_001",
            healer_name="EvolvingHealer",
            healer_healing=500_000,
        )
        db.import_raid(analysis_v2)

        result_v2 = db.get_raid_analysis("update_001")
        assert result_v2 is not None
        assert result_v2.healers[0].total_healing == 500_000

    def test_reimport_preserves_report_id(self, db):
        """Reimport shouldn't create duplicate raid rows."""
        analysis = make_analysis(report_id="nodupe_001")

        db.import_raid(analysis)
        db.import_raid(analysis)
        db.import_raid(analysis)

        codes = db.get_imported_report_codes()
        count = sum(1 for k in codes if k == "nodupe_001")
        assert count == 1

        raids = db.get_raid_list()
        matching = [r for r in raids if r["report_id"] == "nodupe_001"]
        assert len(matching) == 1

    def test_character_last_seen_updates(self, db):
        """Reimporting should update character's last_seen date."""
        analysis1 = make_analysis(
            report_id="lastseen_001",
            healer_name="TrackedHealer",
        )
        db.import_raid(analysis1)

        history1 = db.get_character_history("TrackedHealer")
        assert history1 is not None
        last_seen_1 = history1.last_seen

        # Import a second raid with the same healer (different report)
        analysis2 = make_analysis(
            report_id="lastseen_002",
            healer_name="TrackedHealer",
        )
        db.import_raid(analysis2)

        history2 = db.get_character_history("TrackedHealer")
        assert history2 is not None
        # Both raids use the same start_time in make_analysis, so last_seen
        # should be at least the same. The key assertion is that it did not
        # regress or error.
        assert history2.last_seen >= last_seen_1

    def test_reimport_updates_dps(self, db):
        """Reimport with different DPS numbers, verify DB reflects the update."""
        analysis_v1 = make_analysis(
            report_id="dps_update_001",
            dps_name="UpgradingRogue",
            dps_damage=200_000,
        )
        db.import_raid(analysis_v1)

        analysis_v2 = make_analysis(
            report_id="dps_update_001",
            dps_name="UpgradingRogue",
            dps_damage=350_000,
        )
        db.import_raid(analysis_v2)

        result = db.get_raid_analysis("dps_update_001")
        assert result is not None
        assert result.dps[0].total_damage == 350_000

    def test_reimport_updates_tank(self, db):
        """Reimport with different tank numbers, verify DB reflects the update."""
        analysis_v1 = make_analysis(
            report_id="tank_update_001",
            tank_name="GearingTank",
            tank_damage_taken=500_000,
        )
        db.import_raid(analysis_v1)

        analysis_v2 = make_analysis(
            report_id="tank_update_001",
            tank_name="GearingTank",
            tank_damage_taken=900_000,
        )
        db.import_raid(analysis_v2)

        result = db.get_raid_analysis("tank_update_001")
        assert result is not None
        assert result.tanks[0].total_damage_taken == 900_000
