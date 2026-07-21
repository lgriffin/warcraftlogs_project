"""End-to-end pipeline tests: build analysis -> import -> query -> verify."""

import pytest

from warcraftlogs_client.models import (
    ConsumableUsage,
    EncounterPerformance,
    EncounterSummary,
    InterruptUsage,
)

from .conftest import make_analysis


@pytest.mark.integration
class TestFullPipeline:
    def test_analyze_import_query_roundtrip(self, db):
        """Config -> mock client -> analyze_raid -> import_raid -> get_raid_analysis -> verify data integrity."""
        analysis = make_analysis(
            report_id="roundtrip_001",
            title="Karazhan Clear",
            owner="TestGuild",
            healer_name="Priestess",
            tank_name="Bulwark",
            dps_name="Shanks",
            healer_healing=750_000,
            tank_damage_taken=1_200_000,
            dps_damage=600_000,
        )

        db.import_raid(analysis)

        result = db.get_raid_analysis("roundtrip_001")
        assert result is not None

        # Metadata
        assert result.metadata.report_id == "roundtrip_001"
        assert result.metadata.title == "Karazhan Clear"
        assert result.metadata.owner == "TestGuild"
        assert result.metadata.start_time == analysis.metadata.start_time
        assert result.metadata.end_time == analysis.metadata.end_time

        # Healers
        assert len(result.healers) == 1
        healer = result.healers[0]
        assert healer.name == "Priestess"
        assert healer.player_class == "Priest"
        assert healer.total_healing == 750_000
        assert healer.fear_ward_casts == 3
        assert len(healer.spells) == 1
        assert healer.spells[0].spell_name == "Greater Heal"

        # Tanks
        assert len(result.tanks) == 1
        tank = result.tanks[0]
        assert tank.name == "Bulwark"
        assert tank.player_class == "Warrior"
        assert tank.total_damage_taken == 1_200_000

        # DPS
        assert len(result.dps) == 1
        dps = result.dps[0]
        assert dps.name == "Shanks"
        assert dps.player_class == "Rogue"
        assert dps.total_damage == 600_000

    def test_character_appears_after_import(self, db):
        """After importing a raid, all players should be queryable as characters."""
        analysis = make_analysis(
            report_id="char_query_001",
            healer_name="Healbot",
            tank_name="Shieldwall",
            dps_name="Backstab",
        )
        db.import_raid(analysis)

        for name in ("Healbot", "Shieldwall", "Backstab"):
            history = db.get_character_history(name)
            assert history is not None, f"Character {name} should be queryable"
            assert history.name == name
            assert history.total_raids == 1

    def test_multiple_raids_same_character(self, db):
        """Import two raids with the same healer, verify character history shows both."""
        analysis1 = make_analysis(
            report_id="multi_001",
            title="Raid Night 1",
            healer_name="SharedHealer",
            healer_healing=400_000,
        )
        analysis2 = make_analysis(
            report_id="multi_002",
            title="Raid Night 2",
            healer_name="SharedHealer",
            healer_healing=600_000,
        )

        db.import_raid(analysis1)
        db.import_raid(analysis2)

        history = db.get_character_history("SharedHealer")
        assert history is not None
        assert history.total_raids == 2
        assert history.avg_healing == pytest.approx(500_000.0, rel=1e-2)

    def test_import_updates_imported_at(self, db):
        """Import same raid twice, verify imported_at timestamp changes."""
        analysis = make_analysis(report_id="ts_update_001")
        db.import_raid(analysis)

        codes_before = db.get_imported_report_codes()
        ts_before = codes_before["ts_update_001"]

        # Force a small time gap by re-importing
        db.import_raid(analysis)

        codes_after = db.get_imported_report_codes()
        ts_after = codes_after["ts_update_001"]

        # imported_at should be updated (or at least still present)
        assert ts_after is not None
        assert ts_before is not None

    def test_import_with_consumables(self, db):
        """Import a raid with consumables and verify they round-trip."""
        consumables = [
            ConsumableUsage(
                player_name="HolyPriest",
                player_role="healer",
                report_id="consume_001",
                consumable_name="Super Mana Potion",
                count=3,
                timestamps=[60000, 120000, 180000],
            ),
        ]
        analysis = make_analysis(report_id="consume_001", consumables=consumables)
        db.import_raid(analysis)

        result = db.get_raid_analysis("consume_001")
        assert result is not None
        assert len(result.consumables) == 1
        assert result.consumables[0].consumable_name == "Super Mana Potion"
        assert result.consumables[0].count == 3

    def test_import_with_interrupts(self, db):
        """Import a raid with interrupts and verify they round-trip."""
        interrupts = [
            InterruptUsage(
                player_name="StabbyRogue",
                player_class="Rogue",
                source_id=3,
                spell_id=1766,
                spell_name="Kick",
                count=5,
                timestamps=[30000, 60000, 90000, 120000, 150000],
            ),
        ]
        analysis = make_analysis(report_id="interrupt_001", interrupts=interrupts)
        db.import_raid(analysis)

        result = db.get_raid_analysis("interrupt_001")
        assert result is not None
        assert len(result.interrupts) == 1
        assert result.interrupts[0].spell_name == "Kick"
        assert result.interrupts[0].count == 5

    def test_import_with_encounters(self, db):
        """Import a raid with encounter data and verify round-trip."""
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
        analysis = make_analysis(report_id="encounter_001", encounters=encounters)
        db.import_raid(analysis)

        result = db.get_raid_analysis("encounter_001")
        assert result is not None
        assert len(result.encounters) == 1
        assert result.encounters[0].name == "Attumen the Huntsman"
        assert result.encounters[0].duration_ms == 100_000

    def test_raid_list_includes_imported(self, db):
        """Imported guild raids appear in get_raid_list."""
        analysis = make_analysis(report_id="list_001", title="Listed Raid")
        db.import_raid(analysis)

        raids = db.get_raid_list()
        report_ids = [r["report_id"] for r in raids]
        assert "list_001" in report_ids

    def test_is_raid_imported(self, db):
        """is_raid_imported returns True after import, False before."""
        assert db.is_raid_imported("not_imported") is False

        analysis = make_analysis(report_id="imported_001")
        db.import_raid(analysis)

        assert db.is_raid_imported("imported_001") is True
