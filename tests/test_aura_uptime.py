"""Tests for aura (debuff) uptime analysis and DB persistence."""

import json

import pytest

from warcraftlogs_client.analysis import _analyze_aura_uptimes, _load_debuff_config
from warcraftlogs_client.models import (
    AuraBand,
    AuraUptime,
    EncounterPerformance,
    EncounterSummary,
    InterruptUsage,
)


@pytest.fixture
def debuff_config_file(tmp_path):
    config = {
        "boss_debuffs": {
            "11597": "Sunder Armor",
            "22959": "Fire Vulnerability",
        }
    }
    path = tmp_path / "debuff_config.json"
    path.write_text(json.dumps(config))
    return str(path)


@pytest.fixture
def sample_encounters():
    return [
        EncounterSummary(
            encounter_id=658,
            name="Attumen the Huntsman",
            start_time=10000,
            end_time=110000,
            duration_ms=100000,
            players=[
                EncounterPerformance(
                    name="StabbyRogue",
                    player_class="Rogue",
                    source_id=3,
                    role="melee",
                    total_damage=150_000,
                    total_healing=0,
                    total_damage_taken=20_000,
                ),
            ],
        ),
    ]


class TestLoadDebuffConfig:
    def test_loads_boss_debuffs(self, debuff_config_file, monkeypatch):
        import warcraftlogs_client.paths as paths

        monkeypatch.setattr(paths, "get_debuff_config_path", lambda: debuff_config_file)
        config = _load_debuff_config()
        assert config == {11597: "Sunder Armor", 22959: "Fire Vulnerability"}

    def test_returns_empty_when_missing(self, tmp_path, monkeypatch):
        import warcraftlogs_client.paths as paths

        monkeypatch.setattr(paths, "get_debuff_config_path", lambda: str(tmp_path / "missing.json"))
        config = _load_debuff_config()
        assert config == {}

    def test_returns_empty_when_no_boss_debuffs_key(self, tmp_path, monkeypatch):
        import warcraftlogs_client.paths as paths

        path = tmp_path / "debuff_config.json"
        path.write_text(json.dumps({"some_other_key": {}}))
        monkeypatch.setattr(paths, "get_debuff_config_path", lambda: str(path))
        config = _load_debuff_config()
        assert config == {}


class TestAnalyzeAuraUptimes:
    def test_computes_uptime_from_bands(self, mock_client, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod, "_load_debuff_config",
            lambda: {11597: "Sunder Armor", 22959: "Fire Vulnerability"},
        )

        mock_client.get_debuffs_table.return_value = {
            "data": {
                "auras": [
                    {
                        "guid": 11597,
                        "name": "Sunder Armor",
                        "bands": [
                            {"startTime": 10000, "endTime": 60000},
                            {"startTime": 70000, "endTime": 110000},
                        ],
                    },
                ]
            }
        }

        results, warnings = _analyze_aura_uptimes(mock_client, "test_report", sample_encounters)

        assert len(warnings) == 0
        assert len(results) == 1
        uptime = results[0]
        assert uptime.spell_name == "Sunder Armor"
        assert uptime.fight_name == "Attumen the Huntsman"
        assert uptime.uptime_percent == 90.0
        assert len(uptime.bands) == 2

    def test_clamps_bands_to_fight_window(self, mock_client, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod, "_load_debuff_config",
            lambda: {11597: "Sunder Armor"},
        )

        mock_client.get_debuffs_table.return_value = {
            "data": {
                "auras": [
                    {
                        "guid": 11597,
                        "name": "Sunder Armor",
                        "bands": [
                            {"startTime": 5000, "endTime": 120000},
                        ],
                    },
                ]
            }
        }

        results, _ = _analyze_aura_uptimes(mock_client, "test_report", sample_encounters)
        assert len(results) == 1
        assert results[0].uptime_percent == 100.0
        assert results[0].bands[0].start_time == 10000
        assert results[0].bands[0].end_time == 110000

    def test_filters_by_config(self, mock_client, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod, "_load_debuff_config",
            lambda: {11597: "Sunder Armor"},
        )

        mock_client.get_debuffs_table.return_value = {
            "data": {
                "auras": [
                    {
                        "guid": 11597,
                        "name": "Sunder Armor",
                        "bands": [{"startTime": 10000, "endTime": 110000}],
                    },
                    {
                        "guid": 99999,
                        "name": "Unknown Debuff",
                        "bands": [{"startTime": 10000, "endTime": 110000}],
                    },
                ]
            }
        }

        results, _ = _analyze_aura_uptimes(mock_client, "test_report", sample_encounters)
        assert len(results) == 1
        assert results[0].spell_name == "Sunder Armor"

    def test_empty_config_returns_empty(self, mock_client, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(analysis_mod, "_load_debuff_config", lambda: {})
        results, warnings = _analyze_aura_uptimes(mock_client, "test_report", sample_encounters)
        assert results == []
        assert warnings == []

    def test_api_error_produces_warning(self, mock_client, sample_encounters, monkeypatch):
        import requests

        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod, "_load_debuff_config",
            lambda: {11597: "Sunder Armor"},
        )
        mock_client.get_debuffs_table.side_effect = requests.RequestException("timeout")

        _results, warnings = _analyze_aura_uptimes(mock_client, "test_report", sample_encounters)
        assert len(warnings) == 1
        assert "Failed to analyze debuff uptimes" in warnings[0]


class TestAuraUptimeDatabase:
    def test_import_and_load_round_trip(self, db, sample_raid_analysis, sample_encounter_summary):
        sample_raid_analysis.encounters = [sample_encounter_summary]
        sample_raid_analysis.aura_uptimes = [
            AuraUptime(
                spell_id=11597,
                spell_name="Sunder Armor",
                fight_name="Attumen the Huntsman",
                fight_start=12000,
                fight_end=180000,
                uptime_percent=85.3,
                bands=[AuraBand(start_time=12000, end_time=100000), AuraBand(start_time=120000, end_time=180000)],
            ),
        ]

        db.import_raid(sample_raid_analysis)
        loaded = db.get_raid_analysis("abc123")

        assert loaded is not None
        assert len(loaded.aura_uptimes) == 1
        au = loaded.aura_uptimes[0]
        assert au.spell_name == "Sunder Armor"
        assert au.uptime_percent == 85.3
        assert len(au.bands) == 2
        assert au.bands[0].start_time == 12000
        assert au.bands[1].end_time == 180000

    def test_interrupts_import_and_load(self, db, sample_raid_analysis):
        sample_raid_analysis.interrupts = [
            InterruptUsage(
                player_name="StabbyRogue",
                player_class="Rogue",
                source_id=3,
                spell_id=1766,
                spell_name="Kick",
                count=5,
                timestamps=[10000, 20000, 30000, 40000, 50000],
            ),
        ]

        db.import_raid(sample_raid_analysis)
        loaded = db.get_raid_analysis("abc123")

        assert loaded is not None
        assert len(loaded.interrupts) == 1
        iu = loaded.interrupts[0]
        assert iu.spell_name == "Kick"
        assert iu.count == 5
        assert iu.player_name == "StabbyRogue"
