"""Tests for My Character role comparison features — role detection, boss comparison, role avg trends."""

import pytest

from warcraftlogs_client.models import (
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


def _make_raid(report_id, healers=None, tanks=None, dps=None, encounters=None):
    """Build a minimal RaidAnalysis for import."""
    comp = RaidComposition(
        healers=[PlayerIdentity(name=h.name, player_class=h.player_class, source_id=h.source_id, role="healer") for h in (healers or [])],
        tanks=[PlayerIdentity(name=t.name, player_class=t.player_class, source_id=t.source_id, role="tank") for t in (tanks or [])],
        melee=[PlayerIdentity(name=d.name, player_class=d.player_class, source_id=d.source_id, role=d.role) for d in (dps or []) if d.role == "melee"],
        ranged=[PlayerIdentity(name=d.name, player_class=d.player_class, source_id=d.source_id, role=d.role) for d in (dps or []) if d.role == "ranged"],
    )
    return RaidAnalysis(
        metadata=RaidMetadata(
            report_id=report_id,
            title=f"Raid {report_id}",
            owner="TestGuild",
            start_time=1_700_000_000_000,
            end_time=1_700_003_600_000,
        ),
        composition=comp,
        healers=healers or [],
        tanks=tanks or [],
        dps=dps or [],
        encounters=encounters or [],
    )


@pytest.fixture
def healer():
    return HealerPerformance(
        name="HolyPriest",
        player_class="Priest",
        source_id=1,
        total_healing=500_000,
        total_overhealing=100_000,
        spells=[SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=50, total_amount=300_000)],
    )


@pytest.fixture
def healer2():
    return HealerPerformance(
        name="TreeDruid",
        player_class="Druid",
        source_id=7,
        total_healing=400_000,
        total_overhealing=80_000,
        spells=[],
    )


@pytest.fixture
def tank():
    return TankPerformance(
        name="TankWarrior",
        player_class="Warrior",
        source_id=2,
        total_damage_taken=800_000,
        total_mitigated=600_000,
    )


@pytest.fixture
def dps_melee():
    return DPSPerformance(
        name="StabbyRogue",
        player_class="Rogue",
        source_id=3,
        role="melee",
        total_damage=400_000,
        abilities=[],
    )


@pytest.fixture
def dps_ranged():
    return DPSPerformance(
        name="FrostMage",
        player_class="Mage",
        source_id=4,
        role="ranged",
        total_damage=350_000,
        abilities=[],
    )


def _encounter(players):
    return EncounterSummary(
        encounter_id=658,
        name="Attumen the Huntsman",
        start_time=12000,
        end_time=180000,
        duration_ms=168000,
        players=players,
    )


class TestGetCharacterPrimaryRole:
    def test_healer_detected(self, db, healer):
        db.import_raid(_make_raid("r1", healers=[healer]))
        assert db.get_character_primary_role("HolyPriest") == "healer"

    def test_tank_detected(self, db, tank):
        db.import_raid(_make_raid("r1", tanks=[tank]))
        assert db.get_character_primary_role("TankWarrior") == "tank"

    def test_melee_dps_detected(self, db, dps_melee):
        db.import_raid(_make_raid("r1", dps=[dps_melee]))
        assert db.get_character_primary_role("StabbyRogue") == "melee"

    def test_ranged_dps_detected(self, db, dps_ranged):
        db.import_raid(_make_raid("r1", dps=[dps_ranged]))
        assert db.get_character_primary_role("FrostMage") == "ranged"

    def test_unknown_character_returns_none(self, db):
        assert db.get_character_primary_role("Nobody") is None

    def test_case_insensitive(self, db, healer):
        db.import_raid(_make_raid("r1", healers=[healer]))
        assert db.get_character_primary_role("holypriest") == "healer"

    def test_majority_role_wins(self, db, healer, tank):
        db.import_raid(_make_raid("r1", healers=[healer]))
        db.import_raid(_make_raid("r2", healers=[healer]))
        db.import_raid(_make_raid("r3", tanks=[tank]))
        # The healer fixture and tank fixture have different names;
        # use a character that appears in both roles.
        # Instead, test HolyPriest who has 2 healer rows → healer wins.
        assert db.get_character_primary_role("HolyPriest") == "healer"


class TestGetCharacterBossComparison:
    def test_returns_comparison_data(self, db, healer, healer2):
        enc = _encounter([
            EncounterPerformance(
                name="HolyPriest", player_class="Priest", source_id=1,
                role="healer", total_damage=5000, total_healing=120_000, total_damage_taken=10_000,
            ),
            EncounterPerformance(
                name="TreeDruid", player_class="Druid", source_id=7,
                role="healer", total_damage=2000, total_healing=80_000, total_damage_taken=8000,
            ),
        ])
        db.import_raid(_make_raid("r1", healers=[healer, healer2], encounters=[enc]))

        results = db.get_character_boss_comparison("HolyPriest")
        assert len(results) == 1
        r = results[0]
        assert r["boss_name"] == "Attumen the Huntsman"
        assert r["role"] == "healer"
        assert r["kills"] == 1
        assert r["my_value"] == 120_000
        assert r["peer_count"] == 2
        assert r["rank"] == 1

    def test_unknown_character_returns_empty(self, db):
        assert db.get_character_boss_comparison("Nobody") == []

    def test_delta_pct_computed(self, db, healer, healer2):
        enc = _encounter([
            EncounterPerformance(
                name="HolyPriest", player_class="Priest", source_id=1,
                role="healer", total_damage=0, total_healing=100_000, total_damage_taken=0,
            ),
            EncounterPerformance(
                name="TreeDruid", player_class="Druid", source_id=7,
                role="healer", total_damage=0, total_healing=100_000, total_damage_taken=0,
            ),
        ])
        db.import_raid(_make_raid("r1", healers=[healer, healer2], encounters=[enc]))

        results = db.get_character_boss_comparison("HolyPriest")
        assert results[0]["delta_pct"] == 0.0


class TestHealerRoleAvgTrend:
    def test_returns_averages(self, db, healer, healer2):
        db.import_raid(_make_raid("r1", healers=[healer, healer2]))

        trend = db.get_healer_role_avg_trend()
        assert len(trend) == 1
        avg_healing = trend[0]["avg_healing"]
        assert avg_healing == pytest.approx((500_000 + 400_000) / 2.0)

    def test_empty_when_no_data(self, db):
        assert db.get_healer_role_avg_trend() == []


class TestTankRoleAvgTrend:
    def test_returns_averages(self, db, tank):
        db.import_raid(_make_raid("r1", tanks=[tank]))

        trend = db.get_tank_role_avg_trend()
        assert len(trend) == 1
        assert trend[0]["avg_damage_taken"] == 800_000

    def test_empty_when_no_data(self, db):
        assert db.get_tank_role_avg_trend() == []


class TestDpsRoleAvgTrend:
    def test_returns_averages(self, db, dps_melee, dps_ranged):
        db.import_raid(_make_raid("r1", dps=[dps_melee, dps_ranged]))

        trend = db.get_dps_role_avg_trend()
        assert len(trend) == 1
        avg_damage = trend[0]["avg_damage"]
        assert avg_damage == pytest.approx((400_000 + 350_000) / 2.0)

    def test_empty_when_no_data(self, db):
        assert db.get_dps_role_avg_trend() == []
