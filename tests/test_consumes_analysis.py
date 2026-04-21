"""Tests for ConsumesAnalyzer — spike detection, counting, role determination."""

import json
import os

import pytest

from warcraftlogs_client.consumes_analysis import ConsumesAnalyzer


@pytest.fixture
def config_path(tmp_path):
    config = {
        "buff_consumables": {"28507": "Haste Potion"},
        "cast_consumables": {"28499": "Super Mana Potion"},
    }
    path = tmp_path / "consumes_config.json"
    path.write_text(json.dumps(config))
    return str(path)


@pytest.fixture
def analyzer(config_path):
    return ConsumesAnalyzer(config_path=config_path)


class TestDetectSpikes:
    def test_finds_spike(self, analyzer):
        events = [{"timestamp": 1000 + i * 100, "player": f"P{i}"} for i in range(12)]
        spikes = analyzer._detect_spikes(events, window_size=60000, min_players=10)
        assert len(spikes) == 1
        assert spikes[0]["player_count"] >= 10

    def test_no_spike_below_threshold(self, analyzer):
        events = [{"timestamp": 1000 + i * 100, "player": f"P{i}"} for i in range(5)]
        spikes = analyzer._detect_spikes(events, window_size=60000, min_players=10)
        assert len(spikes) == 0

    def test_multiple_windows(self, analyzer):
        batch1 = [{"timestamp": 1000 + i * 100, "player": f"P{i}"} for i in range(12)]
        batch2 = [{"timestamp": 200_000 + i * 100, "player": f"Q{i}"} for i in range(12)]
        spikes = analyzer._detect_spikes(batch1 + batch2, window_size=60000, min_players=10)
        assert len(spikes) == 2

    def test_custom_min_players(self, analyzer):
        events = [{"timestamp": 1000 + i * 100, "player": f"P{i}"} for i in range(3)]
        spikes = analyzer._detect_spikes(events, window_size=60000, min_players=3)
        assert len(spikes) == 1

    def test_empty_events(self, analyzer):
        assert analyzer._detect_spikes([], window_size=60000, min_players=10) == []


class TestCountConsumablesFromTable:
    def test_buff_consumables(self, analyzer):
        table_data = {
            "data": {"auras": [
                {"guid": 28507, "totalUses": 2, "bands": [
                    {"startTime": 10_000}, {"startTime": 20_000},
                ]},
            ]},
        }
        analyzer._count_consumables_from_table("Player1", "dps", "r1", table_data, [])
        assert analyzer.consumes_data["Player1"]["r1"]["Haste Potion"] == 2

    def test_cast_consumables(self, analyzer):
        table_data = {"data": {"auras": []}}
        cast_events = [
            {"abilityGameID": 28499, "type": "cast", "timestamp": 5000},
            {"abilityGameID": 28499, "type": "cast", "timestamp": 10000},
        ]
        analyzer._count_consumables_from_table("Player1", "healer", "r1", table_data, cast_events)
        assert analyzer.consumes_data["Player1"]["r1"]["Super Mana Potion"] == 2

    def test_ignores_unknown_abilities(self, analyzer):
        table_data = {"data": {"auras": [
            {"guid": 99999, "totalUses": 5, "bands": []},
        ]}}
        analyzer._count_consumables_from_table("Player1", "dps", "r1", table_data, [])
        assert len(analyzer.consumes_data["Player1"]["r1"]) == 0


class TestDetermineRoleFromUsage:
    def test_healer_by_mana_potion(self, analyzer):
        analyzer.consumes_data["Player1"]["r1"]["Super Mana Potion"] = 3
        assert analyzer._determine_role_from_usage("Player1") == "healer"

    def test_unknown_default(self, analyzer):
        assert analyzer._determine_role_from_usage("Nobody") == "unknown"


class TestFindNextBossKill:
    def test_found(self, analyzer):
        analyzer.boss_kills["r1"] = [
            {"name": "Attumen", "timestamp": 50_000},
            {"name": "Moroes", "timestamp": 150_000},
        ]
        result = analyzer._find_next_boss_kill("r1", 40_000)
        assert result["name"] == "Attumen"

    def test_none(self, analyzer):
        analyzer.boss_kills["r1"] = [
            {"name": "Attumen", "timestamp": 50_000},
        ]
        assert analyzer._find_next_boss_kill("r1", 100_000) is None


class TestIsHealer:
    def test_is_healer(self, analyzer):
        analyzer.healers_by_raid["r1"] = {"Priest1"}
        assert analyzer._is_healer("Priest1", "r1") is True

    def test_not_healer(self, analyzer):
        analyzer.healers_by_raid["r1"] = {"Priest1"}
        assert analyzer._is_healer("Rogue1", "r1") is False


class TestConfigLoading:
    def test_valid_config(self, config_path):
        a = ConsumesAnalyzer(config_path=config_path)
        assert "buff_consumables" in a.config

    def test_missing_config(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ConsumesAnalyzer(config_path=str(tmp_path / "missing.json"))


class TestCsvExport:
    def test_export(self, analyzer, tmp_path):
        analyzer.consumes_data["Player1"]["r1"]["Haste Potion"] = 2
        analyzer.raid_metadata["r1"] = {"title": "Kara", "date": 1700000000}
        csv_path = str(tmp_path / "output.csv")
        analyzer._export_to_csv(csv_path)
        assert os.path.exists(csv_path)
        with open(csv_path) as f:
            content = f.read()
        assert "Player1" in content
        assert "Haste Potion" in content
