"""Tests for Raid Diff comparison logic."""

import pytest

pytest.importorskip("PySide6")

from warcraftlogs_client.gui.raid_diff_view import RaidDiffView
from warcraftlogs_client.models import (
    ConsumableUsage,
    DPSPerformance,
    EncounterPerformance,
    EncounterSummary,
    HealerPerformance,
    InterruptUsage,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    TankPerformance,
)


@pytest.fixture
def raid_a():
    return RaidAnalysis(
        metadata=RaidMetadata(
            report_id="raid_a",
            title="Karazhan Week 1",
            owner="TestGuild",
            start_time=1_700_000_000_000,
            end_time=1_700_003_600_000,
        ),
        composition=RaidComposition(
            tanks=[PlayerIdentity(name="Tank1", player_class="Warrior", source_id=1, role="tank")],
            healers=[PlayerIdentity(name="Healer1", player_class="Priest", source_id=2, role="healer")],
            melee=[PlayerIdentity(name="Melee1", player_class="Rogue", source_id=3, role="melee")],
            ranged=[],
        ),
        healers=[
            HealerPerformance(
                name="Healer1",
                player_class="Priest",
                source_id=2,
                total_healing=500_000,
                total_overhealing=80_000,
                spells=[],
                dispels=[],
                resources=[],
                fear_ward_casts=0,
            ),
        ],
        tanks=[
            TankPerformance(
                name="Tank1",
                player_class="Warrior",
                source_id=1,
                total_damage_taken=600_000,
                total_mitigated=450_000,
                damage_taken_breakdown=[],
                abilities_used=[],
            ),
        ],
        dps=[
            DPSPerformance(
                name="Melee1",
                player_class="Rogue",
                source_id=3,
                role="melee",
                total_damage=350_000,
                abilities=[],
            ),
        ],
        consumables=[
            ConsumableUsage(
                player_name="Melee1",
                player_role="melee",
                report_id="raid_a",
                consumable_name="Super Mana Potion",
                count=2,
                timestamps=[60_000, 180_000],
            ),
        ],
        interrupts=[
            InterruptUsage(
                player_name="Melee1",
                player_class="Rogue",
                source_id=3,
                spell_id=1766,
                spell_name="Kick",
                count=4,
                timestamps=[10000, 20000, 30000, 40000],
            ),
        ],
        encounters=[
            EncounterSummary(
                encounter_id=658,
                name="Attumen",
                start_time=10000,
                end_time=100000,
                duration_ms=90000,
                players=[
                    EncounterPerformance(
                        name="Melee1",
                        player_class="Rogue",
                        source_id=3,
                        role="melee",
                        total_damage=120_000,
                        total_healing=0,
                        total_damage_taken=15_000,
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def raid_b():
    return RaidAnalysis(
        metadata=RaidMetadata(
            report_id="raid_b",
            title="Karazhan Week 2",
            owner="TestGuild",
            start_time=1_700_604_800_000,
            end_time=1_700_608_400_000,
        ),
        composition=RaidComposition(
            tanks=[PlayerIdentity(name="Tank1", player_class="Warrior", source_id=1, role="tank")],
            healers=[PlayerIdentity(name="Healer1", player_class="Priest", source_id=2, role="healer")],
            melee=[
                PlayerIdentity(name="Melee1", player_class="Rogue", source_id=3, role="melee"),
                PlayerIdentity(name="Melee2", player_class="Warrior", source_id=4, role="melee"),
            ],
            ranged=[PlayerIdentity(name="Range1", player_class="Mage", source_id=5, role="ranged")],
        ),
        healers=[
            HealerPerformance(
                name="Healer1",
                player_class="Priest",
                source_id=2,
                total_healing=600_000,
                total_overhealing=90_000,
                spells=[],
                dispels=[],
                resources=[],
                fear_ward_casts=0,
            ),
        ],
        tanks=[
            TankPerformance(
                name="Tank1",
                player_class="Warrior",
                source_id=1,
                total_damage_taken=500_000,
                total_mitigated=400_000,
                damage_taken_breakdown=[],
                abilities_used=[],
            ),
        ],
        dps=[
            DPSPerformance(
                name="Melee1",
                player_class="Rogue",
                source_id=3,
                role="melee",
                total_damage=400_000,
                abilities=[],
            ),
            DPSPerformance(
                name="Melee2",
                player_class="Warrior",
                source_id=4,
                role="melee",
                total_damage=300_000,
                abilities=[],
            ),
            DPSPerformance(
                name="Range1",
                player_class="Mage",
                source_id=5,
                role="ranged",
                total_damage=380_000,
                abilities=[],
            ),
        ],
        consumables=[
            ConsumableUsage(
                player_name="Melee1",
                player_role="melee",
                report_id="raid_b",
                consumable_name="Super Mana Potion",
                count=3,
                timestamps=[60_000, 180_000, 300_000],
            ),
            ConsumableUsage(
                player_name="Range1",
                player_role="ranged",
                report_id="raid_b",
                consumable_name="Flask of Supreme Power",
                count=1,
                timestamps=[5000],
            ),
        ],
        interrupts=[
            InterruptUsage(
                player_name="Melee1",
                player_class="Rogue",
                source_id=3,
                spell_id=1766,
                spell_name="Kick",
                count=6,
                timestamps=[10000, 20000, 30000, 40000, 50000, 60000],
            ),
            InterruptUsage(
                player_name="Range1",
                player_class="Mage",
                source_id=5,
                spell_id=2139,
                spell_name="Counterspell",
                count=2,
                timestamps=[15000, 45000],
            ),
        ],
        encounters=[
            EncounterSummary(
                encounter_id=658,
                name="Attumen",
                start_time=10000,
                end_time=85000,
                duration_ms=75000,
                players=[
                    EncounterPerformance(
                        name="Melee1",
                        player_class="Rogue",
                        source_id=3,
                        role="melee",
                        total_damage=140_000,
                        total_healing=0,
                        total_damage_taken=12_000,
                    ),
                    EncounterPerformance(
                        name="Melee2",
                        player_class="Warrior",
                        source_id=4,
                        role="melee",
                        total_damage=100_000,
                        total_healing=0,
                        total_damage_taken=18_000,
                    ),
                ],
            ),
        ],
    )


class TestConsumableSummary:
    def test_computes_total_uses(self, raid_a):
        summary = RaidDiffView._compute_consumable_summary(raid_a)
        assert "Super Mana Potion" in summary
        assert summary["Super Mana Potion"]["total_uses"] == 2
        assert summary["Super Mana Potion"]["unique_users"] == 1

    def test_multiple_consumables(self, raid_b):
        summary = RaidDiffView._compute_consumable_summary(raid_b)
        assert len(summary) == 2
        assert summary["Super Mana Potion"]["total_uses"] == 3
        assert summary["Flask of Supreme Power"]["total_uses"] == 1
        assert summary["Flask of Supreme Power"]["unique_users"] == 1

    def test_empty_consumables(self):
        analysis = RaidAnalysis(
            metadata=RaidMetadata(
                report_id="empty",
                title="Empty",
                owner="Guild",
                start_time=0,
                end_time=100,
            ),
            composition=RaidComposition(),
            healers=[],
            tanks=[],
            dps=[],
            consumables=[],
        )
        summary = RaidDiffView._compute_consumable_summary(analysis)
        assert summary == {}


class TestInterruptSummary:
    def test_computes_total_by_spell(self, raid_a):
        summary = RaidDiffView._compute_interrupt_summary(raid_a)
        assert summary == {"Kick": 4}

    def test_aggregates_multiple_players(self, raid_b):
        summary = RaidDiffView._compute_interrupt_summary(raid_b)
        assert summary["Kick"] == 6
        assert summary["Counterspell"] == 2

    def test_empty_interrupts(self):
        analysis = RaidAnalysis(
            metadata=RaidMetadata(
                report_id="empty",
                title="Empty",
                owner="Guild",
                start_time=0,
                end_time=100,
            ),
            composition=RaidComposition(),
            healers=[],
            tanks=[],
            dps=[],
            consumables=[],
        )
        summary = RaidDiffView._compute_interrupt_summary(analysis)
        assert summary == {}
