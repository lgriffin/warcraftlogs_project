"""Tests for cancelled cast analysis and DB persistence."""

from unittest.mock import MagicMock

import pytest

from warcraftlogs_client.analysis import _analyze_cancelled_casts
from warcraftlogs_client.models import (
    CancelledCastDetail,
    CancelledCastSummary,
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
