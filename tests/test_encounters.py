"""Tests for per-boss encounter analysis feature."""

import pytest
from unittest.mock import MagicMock, patch

from warcraftlogs_client.models import (
    EncounterPerformance,
    EncounterSummary,
    RaidAnalysis,
    RaidComposition,
    PlayerIdentity,
)
from warcraftlogs_client.analysis import _analyze_encounters


# ── Analysis tests ──

class TestAnalyzeEncounters:
    def test_filters_to_boss_kills_only(self, mock_client, sample_composition):
        mock_client.get_fights.return_value = [
            {"id": 1, "name": "Trash", "startTime": 0, "endTime": 10000,
             "kill": True, "encounterID": 0},
            {"id": 2, "name": "Attumen", "startTime": 12000, "endTime": 60000,
             "kill": True, "encounterID": 658},
            {"id": 3, "name": "Moroes", "startTime": 70000, "endTime": 90000,
             "kill": False, "encounterID": 659},
        ]
        mock_client.get_encounter_table.return_value = []

        result = _analyze_encounters(mock_client, "abc123", sample_composition)

        assert len(result) == 1
        assert result[0].name == "Attumen"
        assert result[0].encounter_id == 658

    def test_empty_fights_returns_empty(self, mock_client, sample_composition):
        mock_client.get_fights.return_value = []
        result = _analyze_encounters(mock_client, "abc123", sample_composition)
        assert result == []

    def test_trash_only_returns_empty(self, mock_client, sample_composition):
        mock_client.get_fights.return_value = [
            {"id": 1, "name": "Trash", "startTime": 0, "endTime": 5000,
             "kill": True, "encounterID": 0},
        ]
        result = _analyze_encounters(mock_client, "abc123", sample_composition)
        assert result == []

    def test_merges_damage_healing_taken(self, mock_client, sample_composition):
        mock_client.get_fights.return_value = [
            {"id": 1, "name": "Boss", "startTime": 0, "endTime": 60000,
             "kill": True, "encounterID": 100},
        ]

        def fake_table(report_id, start, end, data_type):
            if data_type == "DamageDone":
                return [{"name": "StabbyRogue", "type": "Player", "total": 200000}]
            elif data_type == "Healing":
                return [{"name": "HolyPriest", "type": "Player", "total": 100000}]
            elif data_type == "DamageTaken":
                return [
                    {"name": "TankWarrior", "type": "Player", "total": 300000},
                    {"name": "StabbyRogue", "type": "Player", "total": 10000},
                ]
            return []

        mock_client.get_encounter_table.side_effect = fake_table

        result = _analyze_encounters(mock_client, "abc123", sample_composition)

        assert len(result) == 1
        enc = result[0]
        assert enc.name == "Boss"
        assert enc.duration_ms == 60000

        by_name = {p.name: p for p in enc.players}
        assert by_name["StabbyRogue"].total_damage == 200000
        assert by_name["StabbyRogue"].total_damage_taken == 10000
        assert by_name["StabbyRogue"].role == "melee"
        assert by_name["HolyPriest"].total_healing == 100000
        assert by_name["HolyPriest"].role == "healer"
        assert by_name["TankWarrior"].total_damage_taken == 300000
        assert by_name["TankWarrior"].role == "tank"

    def test_skips_pets(self, mock_client, sample_composition):
        mock_client.get_fights.return_value = [
            {"id": 1, "name": "Boss", "startTime": 0, "endTime": 60000,
             "kill": True, "encounterID": 100},
        ]
        mock_client.get_encounter_table.side_effect = lambda *args: [
            {"name": "StabbyRogue", "type": "Player", "total": 100000},
            {"name": "Wolf", "type": "Pet", "total": 20000},
        ] if args[3] == "DamageDone" else []

        result = _analyze_encounters(mock_client, "abc123", sample_composition)
        assert len(result[0].players) == 1
        assert result[0].players[0].name == "StabbyRogue"

    def test_api_error_skips_encounter(self, mock_client, sample_composition):
        mock_client.get_fights.return_value = [
            {"id": 1, "name": "Boss1", "startTime": 0, "endTime": 30000,
             "kill": True, "encounterID": 100},
            {"id": 2, "name": "Boss2", "startTime": 40000, "endTime": 80000,
             "kill": True, "encounterID": 200},
        ]

        call_count = [0]

        def fail_on_first(*args):
            call_count[0] += 1
            if call_count[0] <= 1:
                raise KeyError("API error")
            return [{"name": "StabbyRogue", "type": "Player", "total": 50000}]

        mock_client.get_encounter_table.side_effect = fail_on_first

        result = _analyze_encounters(mock_client, "abc123", sample_composition)
        assert len(result) == 1
        assert result[0].name == "Boss2"

    def test_multiple_boss_kills(self, mock_client, sample_composition):
        mock_client.get_fights.return_value = [
            {"id": 1, "name": "Boss1", "startTime": 0, "endTime": 30000,
             "kill": True, "encounterID": 100},
            {"id": 2, "name": "Trash", "startTime": 35000, "endTime": 38000,
             "kill": True, "encounterID": 0},
            {"id": 3, "name": "Boss2", "startTime": 40000, "endTime": 80000,
             "kill": True, "encounterID": 200},
        ]
        mock_client.get_encounter_table.return_value = []

        result = _analyze_encounters(mock_client, "abc123", sample_composition)
        assert len(result) == 2
        assert result[0].name == "Boss1"
        assert result[1].name == "Boss2"

    def test_assigns_unknown_role_for_unknown_players(self, mock_client, sample_composition):
        mock_client.get_fights.return_value = [
            {"id": 1, "name": "Boss", "startTime": 0, "endTime": 60000,
             "kill": True, "encounterID": 100},
        ]
        mock_client.get_encounter_table.side_effect = lambda *args: [
            {"name": "UnknownPlayer", "type": "Player", "total": 5000},
        ] if args[3] == "DamageDone" else []

        result = _analyze_encounters(mock_client, "abc123", sample_composition)
        assert result[0].players[0].name == "UnknownPlayer"
        assert result[0].players[0].role == "unknown"
        assert result[0].players[0].player_class == "Unknown"


# ── Database roundtrip tests ──

class TestEncounterDatabase:
    def test_import_and_load_encounters(self, db, sample_raid_analysis, sample_encounter_summary):
        sample_raid_analysis.encounters = [sample_encounter_summary]
        db.import_raid(sample_raid_analysis)

        loaded = db.get_raid_analysis("abc123")
        assert loaded is not None
        assert len(loaded.encounters) == 1

        enc = loaded.encounters[0]
        assert enc.encounter_id == 658
        assert enc.name == "Attumen the Huntsman"
        assert enc.duration_ms == 168000
        assert len(enc.players) == 3

        by_name = {p.name: p for p in enc.players}
        assert by_name["StabbyRogue"].total_damage == 150_000
        assert by_name["HolyPriest"].total_healing == 120_000
        assert by_name["TankWarrior"].total_damage_taken == 200_000

    def test_no_encounters_loaded_for_old_raids(self, db, sample_raid_analysis):
        db.import_raid(sample_raid_analysis)
        loaded = db.get_raid_analysis("abc123")
        assert loaded.encounters == []

    def test_delete_raid_cascades_encounters(self, db, sample_raid_analysis, sample_encounter_summary):
        sample_raid_analysis.encounters = [sample_encounter_summary]
        db.import_raid(sample_raid_analysis)

        db.delete_raid("abc123")

        conn = db._get_conn()
        assert conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM encounter_performance").fetchone()[0] == 0

    def test_clear_all_clears_encounters(self, db, sample_raid_analysis, sample_encounter_summary):
        sample_raid_analysis.encounters = [sample_encounter_summary]
        db.import_raid(sample_raid_analysis)

        db.clear_all()

        conn = db._get_conn()
        assert conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM encounter_performance").fetchone()[0] == 0

    def test_reimport_updates_encounter_data(self, db, sample_raid_analysis, sample_encounter_summary):
        sample_raid_analysis.encounters = [sample_encounter_summary]
        db.import_raid(sample_raid_analysis)

        sample_encounter_summary.players[0].total_damage = 999_999
        db.import_raid(sample_raid_analysis)

        loaded = db.get_raid_analysis("abc123")
        by_name = {p.name: p for p in loaded.encounters[0].players}
        assert by_name["StabbyRogue"].total_damage == 999_999

    def test_encounter_history(self, db, sample_raid_analysis, sample_encounter_summary):
        sample_raid_analysis.encounters = [sample_encounter_summary]
        db.import_raid(sample_raid_analysis)

        history = db.get_encounter_history(658)
        assert len(history) == 1
        assert history[0]["name"] == "Attumen the Huntsman"
        assert history[0]["total_damage"] > 0

    def test_character_encounter_history(self, db, sample_raid_analysis, sample_encounter_summary):
        sample_raid_analysis.encounters = [sample_encounter_summary]
        db.import_raid(sample_raid_analysis)

        history = db.get_character_encounter_history("StabbyRogue", 658)
        assert len(history) == 1
        assert history[0]["total_damage"] == 150_000
        assert history[0]["encounter_name"] == "Attumen the Huntsman"


# ── Client method tests ──

class TestGetEncounterTable:
    def test_query_formation(self):
        from warcraftlogs_client.client import WarcraftLogsClient
        token_mgr = MagicMock()
        token_mgr.get_token.return_value = "fake_token"
        client = WarcraftLogsClient(token_mgr, cache_enabled=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"reportData": {"report": {"table": {
                "data": {"entries": [
                    {"name": "Player1", "total": 100000},
                ]}
            }}}}
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = client.get_encounter_table("abc123", 1000, 5000, "DamageDone")

        assert len(result) == 1
        assert result[0]["name"] == "Player1"
        assert result[0]["total"] == 100000

        call_args = mock_post.call_args
        query = call_args[1]["json"]["query"]
        assert "DamageDone" in query
        assert "startTime: 1000" in query
        assert "endTime: 5000" in query
        assert "sourceID" not in query

    def test_handles_empty_response(self):
        from warcraftlogs_client.client import WarcraftLogsClient
        token_mgr = MagicMock()
        token_mgr.get_token.return_value = "fake_token"
        client = WarcraftLogsClient(token_mgr, cache_enabled=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"reportData": {"report": {"table": {}}}}
        }

        with patch("requests.post", return_value=mock_response):
            result = client.get_encounter_table("abc123", 0, 60000, "Healing")

        assert result == []


# ── Model tests ──

class TestEncounterModels:
    def test_encounter_summary_fields(self, sample_encounter_summary):
        assert sample_encounter_summary.encounter_id == 658
        assert sample_encounter_summary.name == "Attumen the Huntsman"
        assert sample_encounter_summary.duration_ms == 168000
        assert len(sample_encounter_summary.players) == 3

    def test_encounter_performance_fields(self):
        ep = EncounterPerformance(
            name="Test", player_class="Mage", source_id=1, role="ranged",
            total_damage=100, total_healing=50, total_damage_taken=10)
        assert ep.total_damage == 100
        assert ep.total_healing == 50
        assert ep.role == "ranged"

    def test_raid_analysis_encounters_default_empty(self):
        from warcraftlogs_client.models import RaidMetadata, RaidComposition
        analysis = RaidAnalysis(
            metadata=RaidMetadata(report_id="x", title="t", owner="o", start_time=0),
            composition=RaidComposition(),
        )
        assert analysis.encounters == []


# ── Migration tests ──

class TestEncounterMigration:
    def test_migration_creates_tables(self, db):
        conn = db._get_conn()
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "encounters" in tables
        assert "encounter_performance" in tables
