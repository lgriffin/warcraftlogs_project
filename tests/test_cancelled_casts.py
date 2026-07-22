"""Tests for cancelled cast analysis and DB persistence."""

from unittest.mock import MagicMock

import pytest

from warcraftlogs_client.analysis import _analyze_cancelled_casts, _correlate_cancelled_casts
from warcraftlogs_client.models import (
    BossEvent,
    CancelledCastCorrelation,
    CancelledCastDetail,
    CancelledCastSummary,
    EncounterSummary,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    SpellUsage,
)


@pytest.fixture
def simple_composition():
    return RaidComposition(
        melee=[PlayerIdentity(name="Rogue", player_class="Rogue", source_id=1, role="melee")],
    )


@pytest.fixture
def two_player_composition():
    return RaidComposition(
        melee=[PlayerIdentity(name="Rogue", player_class="Rogue", source_id=1, role="melee")],
        ranged=[PlayerIdentity(name="Mage", player_class="Mage", source_id=2, role="ranged")],
    )


def _make_raid(report_id, cancelled_casts=None):
    return RaidAnalysis(
        metadata=RaidMetadata(
            report_id=report_id,
            title=f"Raid {report_id}",
            owner="TestGuild",
            start_time=1_700_000_000_000,
            end_time=1_700_003_600_000,
        ),
        composition=RaidComposition(),
        healers=[
            HealerPerformance(
                name="Priest", player_class="Priest", source_id=10,
                total_healing=100_000, total_overhealing=10_000,
                spells=[SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=20, total_amount=100_000)],
            ),
        ],
        cancelled_casts=cancelled_casts or [],
    )


class TestAnalyzeCancelledCasts:
    def test_all_completed(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 3000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 4000},
        ]

        results, _warnings = _analyze_cancelled_casts(client, "test", simple_composition)
        assert len(results) == 1
        assert results[0].total_casts == 2
        assert results[0].cancelled_casts == 0
        assert results[0].cancel_rate == 0.0

    def test_all_cancelled(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 2000},
        ]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        assert len(results) == 1
        assert results[0].total_casts == 0
        assert results[0].cancelled_casts == 2
        assert results[0].cancel_rate == 100.0

    def test_mixed_casts(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 3000},
            # cancelled — next begincast replaces it
            {"type": "begincast", "abilityGameID": 100, "timestamp": 4000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 5000},
        ]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        assert results[0].total_casts == 2
        assert results[0].cancelled_casts == 1
        assert results[0].cancel_rate == pytest.approx(33.3, abs=0.1)

    def test_multiple_spell_ids(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "begincast", "abilityGameID": 200, "timestamp": 1500},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "cast", "abilityGameID": 200, "timestamp": 2500},
        ]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        assert results[0].total_casts == 2
        assert results[0].cancelled_casts == 0

    def test_instant_casts_only(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "cast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
        ]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        assert results == []

    def test_trailing_begincast_counted_as_cancelled(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 3000},
        ]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        assert results[0].total_casts == 1
        assert results[0].cancelled_casts == 1

    def test_multiple_players(self, two_player_composition):
        client = MagicMock()
        client.get_cast_events_paginated.side_effect = [
            [
                {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
                {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            ],
            [
                {"type": "begincast", "abilityGameID": 200, "timestamp": 1000},
                {"type": "begincast", "abilityGameID": 200, "timestamp": 2000},
            ],
        ]

        results, _ = _analyze_cancelled_casts(client, "test", two_player_composition)
        assert len(results) == 2
        rogue = next(r for r in results if r.player_name == "Rogue")
        mage = next(r for r in results if r.player_name == "Mage")
        assert rogue.cancel_rate == 0.0
        assert mage.cancel_rate == 100.0

    def test_api_error_produces_warning(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.side_effect = ValueError("API error")

        results, warnings = _analyze_cancelled_casts(client, "test", simple_composition)
        assert results == []
        assert len(warnings) == 1
        assert "Rogue" in warnings[0]

    def test_empty_events(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = []

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        assert results == []

    def test_spell_details_populated(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 3000},
            {"type": "begincast", "abilityGameID": 200, "timestamp": 4000},
            {"type": "cast", "abilityGameID": 200, "timestamp": 5000},
        ]
        client.get_cast_table.return_value = [
            {"guid": 100, "name": "Fireball"},
            {"guid": 200, "name": "Frostbolt"},
        ]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        assert len(results) == 1
        details = results[0].spell_details
        assert len(details) == 2

        fireball = next(d for d in details if d.spell_name == "Fireball")
        assert fireball.total_casts == 1
        assert fireball.cancelled_casts == 1
        assert fireball.cancel_rate == 50.0

        frostbolt = next(d for d in details if d.spell_name == "Frostbolt")
        assert frostbolt.total_casts == 1
        assert frostbolt.cancelled_casts == 0
        assert frostbolt.cancel_rate == 0.0

    def test_spell_details_sorted_by_cancelled_desc(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "begincast", "abilityGameID": 200, "timestamp": 3000},
            {"type": "begincast", "abilityGameID": 200, "timestamp": 4000},
            {"type": "begincast", "abilityGameID": 200, "timestamp": 5000},
        ]
        client.get_cast_table.return_value = [
            {"guid": 100, "name": "Fireball"},
            {"guid": 200, "name": "Frostbolt"},
        ]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        details = results[0].spell_details
        assert details[0].spell_name == "Frostbolt"
        assert details[0].cancelled_casts == 3
        assert details[1].spell_name == "Fireball"
        assert details[1].cancelled_casts == 0


class TestCancelledCastDatabase:
    def test_import_and_load_round_trip(self, db):
        cc = CancelledCastSummary(
            player_name="Mage", player_class="Mage", source_id=1,
            total_casts=50, cancelled_casts=5, cancel_rate=9.1,
        )
        raid = _make_raid("r1", cancelled_casts=[cc])
        db.import_raid(raid)

        loaded = db.get_raid_analysis("r1")
        assert loaded is not None
        assert len(loaded.cancelled_casts) == 1
        lcc = loaded.cancelled_casts[0]
        assert lcc.player_name == "Mage"
        assert lcc.total_casts == 50
        assert lcc.cancelled_casts == 5
        assert lcc.cancel_rate == pytest.approx(9.1)

    def test_cancelled_cast_trend(self, db):
        for i, rate in enumerate([10.0, 8.0, 5.0]):
            cc = CancelledCastSummary(
                player_name="Mage", player_class="Mage", source_id=1,
                total_casts=100, cancelled_casts=int(rate), cancel_rate=rate,
            )
            raid = _make_raid(f"r{i}", cancelled_casts=[cc])
            db.import_raid(raid)

        trend = db.get_cancelled_cast_trend("Mage")
        assert len(trend) == 3
        rates = [r["cancel_rate"] for r in trend]
        assert all(isinstance(r, float) for r in rates)

    def test_cancelled_cast_trend_empty_for_unknown(self, db):
        assert db.get_cancelled_cast_trend("Nobody") == []

    def test_raid_summary(self, db):
        ccs = [
            CancelledCastSummary(
                player_name="Mage", player_class="Mage", source_id=1,
                total_casts=100, cancelled_casts=10, cancel_rate=10.0,
            ),
            CancelledCastSummary(
                player_name="Rogue", player_class="Rogue", source_id=2,
                total_casts=50, cancelled_casts=2, cancel_rate=4.0,
            ),
        ]
        raid = _make_raid("r1", cancelled_casts=ccs)
        db.import_raid(raid)

        conn = db._get_conn()
        raid_id = conn.execute("SELECT id FROM raids WHERE report_id = 'r1'").fetchone()["id"]
        summary = db.get_cancelled_cast_raid_summary(raid_id)

        assert len(summary) == 2
        assert summary[0]["player_name"] == "Rogue"
        assert summary[1]["player_name"] == "Mage"

    def test_spell_details_round_trip(self, db):
        details = [
            CancelledCastDetail(
                spell_id=100, spell_name="Fireball",
                total_casts=10, cancelled_casts=3, cancel_rate=23.1,
            ),
            CancelledCastDetail(
                spell_id=200, spell_name="Frostbolt",
                total_casts=20, cancelled_casts=1, cancel_rate=4.8,
            ),
        ]
        cc = CancelledCastSummary(
            player_name="Mage", player_class="Mage", source_id=1,
            total_casts=30, cancelled_casts=4, cancel_rate=11.8,
            spell_details=details,
        )
        raid = _make_raid("r1", cancelled_casts=[cc])
        db.import_raid(raid)

        loaded = db.get_raid_analysis("r1")
        assert loaded is not None
        lcc = loaded.cancelled_casts[0]
        assert len(lcc.spell_details) == 2
        fireball = next(d for d in lcc.spell_details if d.spell_name == "Fireball")
        assert fireball.cancelled_casts == 3
        assert fireball.cancel_rate == pytest.approx(23.1)
        frostbolt = next(d for d in lcc.spell_details if d.spell_name == "Frostbolt")
        assert frostbolt.cancelled_casts == 1

    def test_delete_raid_cleans_up_spell_details(self, db):
        details = [
            CancelledCastDetail(
                spell_id=100, spell_name="Fireball",
                total_casts=10, cancelled_casts=3, cancel_rate=23.1,
            ),
        ]
        cc = CancelledCastSummary(
            player_name="Mage", player_class="Mage", source_id=1,
            total_casts=10, cancelled_casts=3, cancel_rate=23.1,
            spell_details=details,
        )
        raid = _make_raid("r1", cancelled_casts=[cc])
        db.import_raid(raid)
        db.delete_raid("r1")

        conn = db._get_conn()
        count = conn.execute("SELECT COUNT(*) as cnt FROM cancelled_cast_spells").fetchone()["cnt"]
        assert count == 0

    def test_delete_raid_cleans_up(self, db):
        cc = CancelledCastSummary(
            player_name="Mage", player_class="Mage", source_id=1,
            total_casts=50, cancelled_casts=5, cancel_rate=9.1,
        )
        raid = _make_raid("r1", cancelled_casts=[cc])
        db.import_raid(raid)
        db.delete_raid("r1")

        assert db.get_cancelled_cast_trend("Mage") == []


class TestCancelledCastTimestamps:
    def test_timestamps_collected(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 3000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 5000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 6000},
        ]
        client.get_cast_table.return_value = [{"guid": 100, "name": "Fireball"}]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        fireball = results[0].spell_details[0]
        assert fireball.spell_name == "Fireball"
        assert fireball.cancelled_casts == 1
        assert fireball.timestamps == [3000]

    def test_timestamps_match_cancelled_not_completed(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 3000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 4000},
        ]
        client.get_cast_table.return_value = [{"guid": 100, "name": "Fireball"}]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        fireball = results[0].spell_details[0]
        assert fireball.cancelled_casts == 2
        assert fireball.timestamps == [1000, 2000]

    def test_trailing_begincast_timestamp(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 5000},
        ]
        client.get_cast_table.return_value = [{"guid": 100, "name": "Fireball"}]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        fireball = results[0].spell_details[0]
        assert fireball.cancelled_casts == 1
        assert fireball.timestamps == [5000]

    def test_timestamps_sorted(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 200, "timestamp": 500},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "begincast", "abilityGameID": 200, "timestamp": 1500},
            {"type": "begincast", "abilityGameID": 100, "timestamp": 2000},
        ]
        client.get_cast_table.return_value = [
            {"guid": 100, "name": "Fireball"},
            {"guid": 200, "name": "Frostbolt"},
        ]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        for detail in results[0].spell_details:
            assert detail.timestamps == sorted(detail.timestamps)

    def test_no_timestamps_when_no_cancels(self, simple_composition):
        client = MagicMock()
        client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 100, "timestamp": 1000},
            {"type": "cast", "abilityGameID": 100, "timestamp": 2000},
        ]
        client.get_cast_table.return_value = [{"guid": 100, "name": "Fireball"}]

        results, _ = _analyze_cancelled_casts(client, "test", simple_composition)
        fireball = results[0].spell_details[0]
        assert fireball.cancelled_casts == 0
        assert fireball.timestamps == []

    def test_timestamps_round_trip(self, db):
        details = [
            CancelledCastDetail(
                spell_id=100, spell_name="Fireball",
                total_casts=10, cancelled_casts=3, cancel_rate=23.1,
                timestamps=[1000, 3000, 5000],
            ),
            CancelledCastDetail(
                spell_id=200, spell_name="Frostbolt",
                total_casts=20, cancelled_casts=0, cancel_rate=0.0,
                timestamps=[],
            ),
        ]
        cc = CancelledCastSummary(
            player_name="Mage", player_class="Mage", source_id=1,
            total_casts=30, cancelled_casts=3, cancel_rate=9.1,
            spell_details=details,
        )
        raid = _make_raid("r1", cancelled_casts=[cc])
        db.import_raid(raid)

        loaded = db.get_raid_analysis("r1")
        assert loaded is not None
        lcc = loaded.cancelled_casts[0]
        fireball = next(d for d in lcc.spell_details if d.spell_name == "Fireball")
        assert fireball.timestamps == [1000, 3000, 5000]
        frostbolt = next(d for d in lcc.spell_details if d.spell_name == "Frostbolt")
        assert frostbolt.timestamps == []


def _make_encounter(name="Boss", start=0, end=60000):
    return EncounterSummary(
        encounter_id=1, name=name, start_time=start, end_time=end,
        duration_ms=end - start,
    )


def _make_cancelled_casts(timestamps, spell_id=100, spell_name="Fireball"):
    detail = CancelledCastDetail(
        spell_id=spell_id, spell_name=spell_name,
        total_casts=10, cancelled_casts=len(timestamps),
        cancel_rate=round(len(timestamps) / 10 * 100, 1),
        timestamps=timestamps,
    )
    return [CancelledCastSummary(
        player_name="Mage", player_class="Mage", source_id=1,
        total_casts=10, cancelled_casts=len(timestamps),
        cancel_rate=detail.cancel_rate, spell_details=[detail],
    )]


class TestCancelledCastCorrelation:
    def test_boss_cast_within_window(self):
        client = MagicMock()
        client.get_all_actors.return_value = [
            {"id": 50, "name": "Shade of Aran", "type": "Boss", "subType": "Boss"},
        ]
        client.get_enemy_ability_names.return_value = {9999: "Flame Wreath"}
        client.get_enemy_cast_events.return_value = [
            {"type": "cast", "abilityGameID": 9999, "timestamp": 4000, "sourceID": 50},
        ]
        client.get_raid_damage_taken_events.return_value = []

        enc = _make_encounter(start=0, end=60000)
        cc = _make_cancelled_casts([5000])

        _correlate_cancelled_casts(client, "test", cc, [enc])

        detail = cc[0].spell_details[0]
        assert len(detail.correlations) == 1
        assert detail.correlations[0].cancel_timestamp == 5000
        events = detail.correlations[0].nearby_events
        boss_casts = [e for e in events if e.event_type == "boss_cast"]
        assert len(boss_casts) >= 1
        assert boss_casts[0].ability_id == 9999
        assert boss_casts[0].ability_name == "Flame Wreath"

    def test_boss_cast_outside_window(self):
        client = MagicMock()
        client.get_all_actors.return_value = []
        client.get_enemy_cast_events.return_value = [
            {"type": "cast", "abilityGameID": 9999, "timestamp": 1000, "sourceID": 50},
        ]
        client.get_raid_damage_taken_events.return_value = []

        enc = _make_encounter(start=0, end=60000)
        cc = _make_cancelled_casts([5000])

        _correlate_cancelled_casts(client, "test", cc, [enc])

        detail = cc[0].spell_details[0]
        corr = detail.correlations
        if corr:
            boss_casts = [e for e in corr[0].nearby_events if e.event_type == "boss_cast"]
            assert len(boss_casts) == 0

    def test_damage_event_correlation(self):
        client = MagicMock()
        client.get_all_actors.return_value = [
            {"id": 50, "name": "Prince Malchezaar", "type": "Boss", "subType": "Boss"},
        ]
        client.get_enemy_ability_names.return_value = {8888: "Shadow Nova"}
        client.get_enemy_cast_events.return_value = []
        client.get_raid_damage_taken_events.return_value = [
            {"type": "damage", "abilityGameID": 8888, "timestamp": 4500, "sourceID": 50, "amount": 5000},
        ]

        enc = _make_encounter(start=0, end=60000)
        cc = _make_cancelled_casts([5000])

        _correlate_cancelled_casts(client, "test", cc, [enc])

        detail = cc[0].spell_details[0]
        assert len(detail.correlations) == 1
        dmg_events = [e for e in detail.correlations[0].nearby_events if e.event_type == "damage"]
        assert len(dmg_events) == 1
        assert dmg_events[0].ability_id == 8888
        assert dmg_events[0].ability_name == "Shadow Nova"
        assert dmg_events[0].source_name == "Prince Malchezaar"

    def test_boss_death_correlation(self):
        client = MagicMock()
        client.get_all_actors.return_value = []
        client.get_enemy_cast_events.return_value = []
        client.get_raid_damage_taken_events.return_value = []

        enc = _make_encounter(name="Curator", start=0, end=10000)
        cc = _make_cancelled_casts([8000])

        _correlate_cancelled_casts(client, "test", cc, [enc])

        detail = cc[0].spell_details[0]
        assert len(detail.correlations) == 1
        death_events = [e for e in detail.correlations[0].nearby_events if e.event_type == "boss_death"]
        assert len(death_events) == 1
        assert death_events[0].source_name == "Curator"

    def test_multiple_events_in_window(self):
        client = MagicMock()
        client.get_all_actors.return_value = [
            {"id": 50, "name": "Boss", "type": "Boss", "subType": "Boss"},
        ]
        client.get_enemy_cast_events.return_value = [
            {"type": "cast", "abilityGameID": 111, "timestamp": 4500, "sourceID": 50},
            {"type": "cast", "abilityGameID": 222, "timestamp": 5500, "sourceID": 50},
        ]
        client.get_raid_damage_taken_events.return_value = [
            {"type": "damage", "abilityGameID": 333, "timestamp": 4800, "sourceID": 50, "amount": 3000},
        ]

        enc = _make_encounter(start=0, end=60000)
        cc = _make_cancelled_casts([5000])

        _correlate_cancelled_casts(client, "test", cc, [enc])

        detail = cc[0].spell_details[0]
        assert len(detail.correlations) == 1
        assert len(detail.correlations[0].nearby_events) == 3

    def test_damage_deduplication(self):
        client = MagicMock()
        client.get_all_actors.return_value = []
        client.get_enemy_cast_events.return_value = []
        client.get_raid_damage_taken_events.return_value = [
            {"type": "damage", "abilityGameID": 8888, "timestamp": 4500, "sourceID": 50, "amount": 3000},
            {"type": "damage", "abilityGameID": 8888, "timestamp": 4500, "sourceID": 50, "amount": 2500},
            {"type": "damage", "abilityGameID": 8888, "timestamp": 4500, "sourceID": 50, "amount": 2800},
        ]

        enc = _make_encounter(start=0, end=60000)
        cc = _make_cancelled_casts([5000])

        _correlate_cancelled_casts(client, "test", cc, [enc])

        detail = cc[0].spell_details[0]
        assert len(detail.correlations) == 1
        dmg_events = [e for e in detail.correlations[0].nearby_events if e.event_type == "damage"]
        assert len(dmg_events) == 1

    def test_correlation_round_trip(self, db):
        corr = CancelledCastCorrelation(
            cancel_timestamp=5000,
            nearby_events=[
                BossEvent(
                    timestamp=4000, event_type="boss_cast",
                    ability_name="Flame Wreath", ability_id=9999,
                    source_name="Shade of Aran", offset_ms=-1000,
                ),
            ],
        )
        details = [
            CancelledCastDetail(
                spell_id=100, spell_name="Fireball",
                total_casts=10, cancelled_casts=1, cancel_rate=9.1,
                timestamps=[5000], correlations=[corr],
            ),
        ]
        cc = CancelledCastSummary(
            player_name="Mage", player_class="Mage", source_id=1,
            total_casts=10, cancelled_casts=1, cancel_rate=9.1,
            spell_details=details,
        )
        raid = _make_raid("r1", cancelled_casts=[cc])
        db.import_raid(raid)

        loaded = db.get_raid_analysis("r1")
        assert loaded is not None
        lcc = loaded.cancelled_casts[0]
        fireball = lcc.spell_details[0]
        assert len(fireball.correlations) == 1
        assert fireball.correlations[0].cancel_timestamp == 5000
        ev = fireball.correlations[0].nearby_events[0]
        assert ev.event_type == "boss_cast"
        assert ev.ability_name == "Flame Wreath"
        assert ev.ability_id == 9999
        assert ev.source_name == "Shade of Aran"
        assert ev.offset_ms == -1000

    def test_no_correlation_when_no_encounters(self):
        client = MagicMock()
        cc = _make_cancelled_casts([5000])

        _correlate_cancelled_casts(client, "test", cc, [])

        detail = cc[0].spell_details[0]
        assert detail.correlations == []
        client.get_enemy_cast_events.assert_not_called()


class TestCancelledCastTimelineWidget:
    def test_timeline_widget_set_data(self, qtbot):
        from warcraftlogs_client.gui.charts import CancelledCastTimelineWidget

        widget = CancelledCastTimelineWidget()
        qtbot.addWidget(widget)

        corr = CancelledCastCorrelation(
            cancel_timestamp=5000,
            nearby_events=[
                BossEvent(
                    timestamp=4000, event_type="boss_cast",
                    ability_name="Flame Wreath", ability_id=9999,
                    source_name="Shade of Aran", offset_ms=-1000,
                ),
            ],
        )
        detail = CancelledCastDetail(
            spell_id=100, spell_name="Fireball",
            total_casts=10, cancelled_casts=1, cancel_rate=9.1,
            timestamps=[5000], correlations=[corr],
        )
        enc = _make_encounter(start=0, end=60000)
        enc.boss_events = [
            BossEvent(timestamp=4000, event_type="boss_cast",
                      ability_name="Flame Wreath", ability_id=9999,
                      source_name="Shade of Aran"),
            BossEvent(timestamp=30000, event_type="boss_cast",
                      ability_name="Arcane Explosion", ability_id=8888,
                      source_name="Shade of Aran"),
            BossEvent(timestamp=60000, event_type="boss_death",
                      ability_name="Boss Died", ability_id=0,
                      source_name="Shade of Aran"),
        ]

        widget.set_data([detail], enc)

        assert widget.height() > 60
        assert len(widget._boss_lanes) == 3
        assert len(widget._cancel_markers) == 1

    def test_timeline_widget_empty_data(self, qtbot):
        from warcraftlogs_client.gui.charts import CancelledCastTimelineWidget

        widget = CancelledCastTimelineWidget()
        qtbot.addWidget(widget)

        enc = _make_encounter(start=0, end=60000)
        widget.set_data([], enc)

        assert widget.maximumHeight() == 60
        assert len(widget._boss_lanes) == 0
        assert len(widget._cancel_markers) == 0


class TestBossEventsDatabase:
    def test_boss_events_round_trip(self, db):
        enc = EncounterSummary(
            encounter_id=1, name="Shade of Aran",
            start_time=1000, end_time=60000, duration_ms=59000,
            boss_events=[
                BossEvent(timestamp=4000, event_type="boss_cast",
                          ability_name="Flame Wreath", ability_id=9999,
                          source_name="Shade of Aran"),
                BossEvent(timestamp=30000, event_type="damage",
                          ability_name="Arcane Explosion", ability_id=8888,
                          source_name="Shade of Aran"),
                BossEvent(timestamp=60000, event_type="boss_death",
                          ability_name="Boss Died", ability_id=0,
                          source_name="Shade of Aran"),
            ],
        )
        raid = _make_raid("r1")
        raid.encounters = [enc]
        db.import_raid(raid)

        loaded = db.get_raid_analysis("r1")
        assert loaded is not None
        assert len(loaded.encounters) == 1
        loaded_enc = loaded.encounters[0]
        assert len(loaded_enc.boss_events) == 3
        assert loaded_enc.boss_events[0].event_type == "boss_cast"
        assert loaded_enc.boss_events[0].ability_name == "Flame Wreath"
        assert loaded_enc.boss_events[0].ability_id == 9999
        assert loaded_enc.boss_events[1].event_type == "damage"
        assert loaded_enc.boss_events[2].event_type == "boss_death"

    def test_boss_events_empty_round_trip(self, db):
        enc = EncounterSummary(
            encounter_id=1, name="Curator",
            start_time=1000, end_time=60000, duration_ms=59000,
        )
        raid = _make_raid("r1")
        raid.encounters = [enc]
        db.import_raid(raid)

        loaded = db.get_raid_analysis("r1")
        assert loaded is not None
        assert len(loaded.encounters) == 1
        assert loaded.encounters[0].boss_events == []
