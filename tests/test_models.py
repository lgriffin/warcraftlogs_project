"""Tests for data model classes — computed properties and __post_init__ logic."""

from datetime import datetime

import pytest

from warcraftlogs_client.models import (
    CharacterProfile,
    ConsumableUsage,
    EncounterRanking,
    HealerPerformance,
    PotionSpike,
    RaidComposition,
    RaidMetadata,
    TankPerformance,
    PlayerIdentity,
    WOW_CLASS_NAMES,
)


class TestHealerPerformance:
    def test_overheal_percent_calculated(self):
        h = HealerPerformance(
            name="P", player_class="Priest", source_id=1,
            total_healing=900, total_overhealing=100,
        )
        assert h.overheal_percent == 10.0

    def test_overheal_percent_zero_total(self):
        h = HealerPerformance(
            name="P", player_class="Priest", source_id=1,
            total_healing=0, total_overhealing=0,
        )
        assert h.overheal_percent == 0.0

    def test_overheal_percent_all_overheal(self):
        h = HealerPerformance(
            name="P", player_class="Priest", source_id=1,
            total_healing=0, total_overhealing=1000,
        )
        assert h.overheal_percent == 100.0

    def test_overheal_percent_rounding(self):
        h = HealerPerformance(
            name="P", player_class="Priest", source_id=1,
            total_healing=2, total_overhealing=1,
        )
        assert h.overheal_percent == 33.3


class TestTankPerformance:
    def test_mitigation_percent_calculated(self):
        t = TankPerformance(
            name="T", player_class="Warrior", source_id=1,
            total_damage_taken=400, total_mitigated=600,
        )
        assert t.mitigation_percent == 60.0

    def test_mitigation_percent_zero_total(self):
        t = TankPerformance(
            name="T", player_class="Warrior", source_id=1,
            total_damage_taken=0, total_mitigated=0,
        )
        assert t.mitigation_percent == 0.0


class TestConsumableUsage:
    def test_timestamps_formatted_empty(self):
        c = ConsumableUsage(
            player_name="P", player_role="healer",
            report_id="r1", consumable_name="Potion",
        )
        assert c.timestamps_formatted == ""

    def test_timestamps_formatted_single(self):
        c = ConsumableUsage(
            player_name="P", player_role="healer",
            report_id="r1", consumable_name="Potion",
            count=1, timestamps=[90_000],
        )
        assert c.timestamps_formatted == "01:30"

    def test_timestamps_formatted_multiple(self):
        c = ConsumableUsage(
            player_name="P", player_role="healer",
            report_id="r1", consumable_name="Potion",
            count=2, timestamps=[60_000, 125_000],
        )
        assert c.timestamps_formatted == "01:00, 02:05"

    def test_timestamps_formatted_zero(self):
        c = ConsumableUsage(
            player_name="P", player_role="healer",
            report_id="r1", consumable_name="Potion",
            count=1, timestamps=[0],
        )
        assert c.timestamps_formatted == "00:00"


class TestPotionSpike:
    def test_time_formatted(self):
        s = PotionSpike(timestamp_ms=125_000, potion_name="P", player_count=10)
        assert s.time_formatted == "02:05"

    def test_time_formatted_zero(self):
        s = PotionSpike(timestamp_ms=0, potion_name="P", player_count=0)
        assert s.time_formatted == "00:00"


class TestRaidMetadata:
    def test_date_property(self, sample_raid_metadata):
        assert isinstance(sample_raid_metadata.date, datetime)

    def test_date_formatted(self, sample_raid_metadata):
        formatted = sample_raid_metadata.date_formatted
        assert isinstance(formatted, str)
        assert len(formatted) > 10

    def test_url(self, sample_raid_metadata):
        assert sample_raid_metadata.url == "https://www.warcraftlogs.com/reports/abc123"


class TestRaidComposition:
    def test_all_players_count(self, sample_composition):
        assert len(sample_composition.all_players) == 4

    def test_get_player_found(self, sample_composition):
        player = sample_composition.get_player("TankWarrior")
        assert player is not None
        assert player.role == "tank"

    def test_get_player_not_found(self, sample_composition):
        assert sample_composition.get_player("Nobody") is None

    def test_empty_composition(self):
        comp = RaidComposition()
        assert comp.all_players == []
        assert comp.get_player("X") is None


class TestEncounterRanking:
    def test_fastest_kill_formatted(self):
        r = EncounterRanking(encounter_id=1, encounter_name="Boss", fastest_kill_ms=125_000)
        assert r.fastest_kill_formatted == "2:05"

    def test_fastest_kill_formatted_exact_minute(self):
        r = EncounterRanking(encounter_id=1, encounter_name="Boss", fastest_kill_ms=180_000)
        assert r.fastest_kill_formatted == "3:00"


class TestCharacterProfile:
    def test_class_name_known(self):
        p = CharacterProfile(name="X", server="S", region="R", class_id=7)
        assert p.class_name == "Priest"

    def test_class_name_unknown(self):
        p = CharacterProfile(name="X", server="S", region="R", class_id=999)
        assert p.class_name == "Unknown"

    def test_all_class_ids_mapped(self):
        for cid, name in WOW_CLASS_NAMES.items():
            p = CharacterProfile(name="X", server="S", region="R", class_id=cid)
            assert p.class_name == name
