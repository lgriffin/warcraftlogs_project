"""Extended database tests — analytics queries, raid groups, and edge cases."""

import json

import pytest

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


def _make_analysis(report_id, title, start_time, healing=500_000, damage=400_000,
                   damage_taken=800_000, mitigated=600_000, consumes_count=3):
    meta = RaidMetadata(
        report_id=report_id, title=title, owner="TestGuild",
        start_time=start_time,
    )
    comp = RaidComposition(
        tanks=[PlayerIdentity(name="Tank", player_class="Warrior", source_id=1, role="tank")],
        healers=[PlayerIdentity(name="Healer", player_class="Priest", source_id=2, role="healer")],
        melee=[PlayerIdentity(name="DPS", player_class="Rogue", source_id=3, role="melee")],
        ranged=[],
    )
    return RaidAnalysis(
        metadata=meta, composition=comp,
        healers=[HealerPerformance(
            name="Healer", player_class="Priest", source_id=2,
            total_healing=healing, total_overhealing=int(healing * 0.2),
            spells=[SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=50, total_amount=healing)],
        )],
        tanks=[TankPerformance(
            name="Tank", player_class="Warrior", source_id=1,
            total_damage_taken=damage_taken, total_mitigated=mitigated,
            damage_taken_breakdown=[SpellUsage(spell_id=1, spell_name="Melee", casts=100)],
            abilities_used=[SpellUsage(spell_id=6572, spell_name="Revenge", casts=40)],
        )],
        dps=[DPSPerformance(
            name="DPS", player_class="Rogue", source_id=3, role="melee",
            total_damage=damage,
            abilities=[SpellUsage(spell_id=1, spell_name="Melee", casts=200, total_amount=damage)],
        )],
        consumables=[ConsumableUsage(
            player_name="Healer", player_role="healer",
            report_id=report_id, consumable_name="Super Mana Potion",
            count=consumes_count, timestamps=[60_000, 180_000, 300_000][:consumes_count],
        )],
    )


class TestConsumableSummary:
    def test_pivoted_by_raid(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000, consumes_count=3))
        db.import_raid(_make_analysis("r2", "Raid 2", 1_700_100_000_000, consumes_count=5))
        summary = db.get_consumable_summary("Healer", limit=5)
        assert len(summary) == 2
        assert summary[0]["Super Mana Potion"] in (3, 5)

    def test_empty_for_unknown(self, db):
        assert db.get_consumable_summary("Nobody") == []


class TestHealerSpellTrend:
    def test_returns_spell_data(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000))
        trend = db.get_healer_spell_trend("Healer")
        assert len(trend) >= 1
        assert trend[0]["spell_name"] == "Greater Heal"
        assert trend[0]["casts"] == 50

    def test_empty_for_unknown(self, db):
        assert db.get_healer_spell_trend("Nobody") == []


class TestDpsAbilityTrend:
    def test_returns_ability_data(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000))
        trend = db.get_dps_ability_trend("DPS")
        assert len(trend) >= 1
        assert trend[0]["spell_name"] == "Melee"

    def test_empty_for_unknown(self, db):
        assert db.get_dps_ability_trend("Nobody") == []


class TestCharacterConsistency:
    def test_empty_for_unknown(self, db):
        assert db.get_character_consistency("Nobody") == {}

    def test_needs_two_raids_minimum(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000))
        result = db.get_character_consistency("Healer")
        assert "healing_consistency" not in result

    def test_computes_with_two_raids(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000, healing=500_000))
        db.import_raid(_make_analysis("r2", "Raid 2", 1_700_100_000_000, healing=600_000))
        result = db.get_character_consistency("Healer")
        assert "healing_consistency" in result
        assert 0 <= result["healing_consistency"] <= 100

    def test_dps_consistency(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000, damage=300_000))
        db.import_raid(_make_analysis("r2", "Raid 2", 1_700_100_000_000, damage=350_000))
        result = db.get_character_consistency("DPS")
        assert "damage_consistency" in result

    def test_tank_consistency(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000,
                                      damage_taken=800_000, mitigated=600_000))
        db.import_raid(_make_analysis("r2", "Raid 2", 1_700_100_000_000,
                                      damage_taken=900_000, mitigated=700_000))
        result = db.get_character_consistency("Tank")
        assert "mitigation_consistency" in result


class TestConsumableCompliance:
    def test_empty_for_unknown(self, db):
        assert db.get_character_consumable_compliance("Nobody") == {}

    def test_full_compliance(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000, consumes_count=3))
        result = db.get_character_consumable_compliance("Healer")
        assert result["total_raids"] == 1
        assert result["compliance_pct"] == 100.0
        assert result["avg_per_raid"] == 3.0


class TestPersonalBests:
    def test_empty_for_unknown(self, db):
        assert db.get_character_personal_bests("Nobody") == []

    def test_returns_bests(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000, healing=500_000))
        db.import_raid(_make_analysis("r2", "Raid 2", 1_700_100_000_000, healing=700_000))
        bests = db.get_character_personal_bests("Healer")
        labels = [b["label"] for b in bests]
        assert "Best Healing" in labels
        assert "Worst Healing" in labels
        best = next(b for b in bests if b["label"] == "Best Healing")
        assert best["value"] == 700_000


class TestSpiderData:
    def test_empty_for_unknown(self, db):
        assert db.get_character_spider_data("Nobody") == {}

    def test_returns_dimensions(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000))
        data = db.get_character_spider_data("Healer")
        assert "healing" in data
        assert "activity" in data
        assert "consumables" in data


class TestRaidCalendar:
    def test_empty_for_unknown(self, db):
        assert db.get_character_raid_calendar("Nobody") == []

    def test_returns_entries(self, db):
        db.import_raid(_make_analysis("r1", "Raid 1", 1_700_000_000_000))
        entries = db.get_character_raid_calendar("Healer")
        assert len(entries) >= 1
        assert "raid_date" in entries[0]


class TestRaidGroups:
    def test_create_group(self, db):
        group = db.create_raid_group("Team A", ["Wed", "Thu"])
        assert group.name == "Team A"
        assert group.raid_days == ["Wed", "Thu"]
        assert group.id is not None

    def test_get_all_groups(self, db):
        db.create_raid_group("Team A")
        db.create_raid_group("Team B")
        groups = db.get_all_raid_groups()
        assert len(groups) == 2

    def test_get_single_group(self, db):
        created = db.create_raid_group("Team A")
        fetched = db.get_raid_group(created.id)
        assert fetched is not None
        assert fetched.name == "Team A"

    def test_get_nonexistent_group(self, db):
        assert db.get_raid_group(999) is None

    def test_update_group_name(self, db):
        group = db.create_raid_group("Old Name")
        db.update_raid_group(group.id, name="New Name")
        updated = db.get_raid_group(group.id)
        assert updated.name == "New Name"

    def test_update_group_days(self, db):
        group = db.create_raid_group("Team", ["Mon"])
        db.update_raid_group(group.id, raid_days=["Wed", "Sun"])
        updated = db.get_raid_group(group.id)
        assert updated.raid_days == ["Wed", "Sun"]

    def test_delete_group(self, db):
        group = db.create_raid_group("Temp")
        db.delete_raid_group(group.id)
        assert db.get_raid_group(group.id) is None

    def test_add_member(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        group = db.create_raid_group("Team A")
        result = db.add_raid_group_member(group.id, "HolyPriest")
        assert result is True
        fetched = db.get_raid_group(group.id)
        assert "HolyPriest" in fetched.members

    def test_add_unknown_member(self, db):
        group = db.create_raid_group("Team A")
        result = db.add_raid_group_member(group.id, "Unknown")
        assert result is False

    def test_add_duplicate_member(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        group = db.create_raid_group("Team A")
        db.add_raid_group_member(group.id, "HolyPriest")
        result = db.add_raid_group_member(group.id, "HolyPriest")
        assert result is False

    def test_remove_member(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        group = db.create_raid_group("Team A")
        db.add_raid_group_member(group.id, "HolyPriest")
        db.remove_raid_group_member(group.id, "HolyPriest")
        fetched = db.get_raid_group(group.id)
        assert "HolyPriest" not in fetched.members

    def test_groups_for_character(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        g1 = db.create_raid_group("Team A")
        g2 = db.create_raid_group("Team B")
        db.add_raid_group_member(g1.id, "HolyPriest")
        db.add_raid_group_member(g2.id, "HolyPriest")
        groups = db.get_groups_for_character("HolyPriest")
        assert set(groups) == {"Team A", "Team B"}


class TestMultiRaidTrends:
    def test_trend_ordering(self, db):
        db.import_raid(_make_analysis("r1", "Early", 1_700_000_000_000, healing=400_000))
        db.import_raid(_make_analysis("r2", "Late", 1_700_100_000_000, healing=600_000))
        trend = db.get_healer_trend("Healer")
        assert len(trend) == 2
        assert trend[0]["title"] == "Late"
        assert trend[1]["title"] == "Early"

    def test_trend_limit(self, db):
        for i in range(5):
            db.import_raid(_make_analysis(
                f"r{i}", f"Raid {i}", 1_700_000_000_000 + i * 100_000_000,
            ))
        trend = db.get_healer_trend("Healer", limit=3)
        assert len(trend) == 3
