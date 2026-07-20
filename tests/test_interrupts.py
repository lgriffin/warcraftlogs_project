"""Tests for interrupt tracking analysis."""

import json

import pytest

from warcraftlogs_client.analysis import _analyze_interrupts, _load_interrupt_config
from warcraftlogs_client.models import PlayerIdentity, RaidComposition


@pytest.fixture
def interrupt_config_file(tmp_path):
    config = {"1766": "Kick", "6552": "Pummel", "2139": "Counterspell"}
    path = tmp_path / "interrupt_config.json"
    path.write_text(json.dumps(config))
    return str(path)


@pytest.fixture
def sample_composition():
    return RaidComposition(
        tanks=[],
        healers=[],
        melee=[
            PlayerIdentity(name="StabbyRogue", player_class="Rogue", source_id=3, role="melee"),
            PlayerIdentity(name="SmashWarrior", player_class="Warrior", source_id=4, role="melee"),
        ],
        ranged=[
            PlayerIdentity(name="FrostMage", player_class="Mage", source_id=5, role="ranged"),
        ],
    )


class TestLoadInterruptConfig:
    def test_loads_config(self, interrupt_config_file, monkeypatch):
        import warcraftlogs_client.paths as paths

        monkeypatch.setattr(paths, "get_interrupt_config_path", lambda: interrupt_config_file)
        config = _load_interrupt_config()
        assert config == {1766: "Kick", 6552: "Pummel", 2139: "Counterspell"}

    def test_returns_empty_when_missing(self, tmp_path, monkeypatch):
        import warcraftlogs_client.paths as paths

        monkeypatch.setattr(paths, "get_interrupt_config_path", lambda: str(tmp_path / "missing.json"))
        config = _load_interrupt_config()
        assert config == {}


class TestAnalyzeInterrupts:
    def test_extracts_interrupts_from_cast_events(self, mock_client, sample_composition, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        config = {1766: "Kick", 6552: "Pummel", 2139: "Counterspell"}
        monkeypatch.setattr(analysis_mod, "_load_interrupt_config", lambda: config)

        mock_client.get_cast_events_paginated.side_effect = [
            [
                {"type": "cast", "abilityGameID": 1766, "timestamp": 10000},
                {"type": "cast", "abilityGameID": 1766, "timestamp": 30000},
                {"type": "cast", "abilityGameID": 26862, "timestamp": 15000},
            ],
            [
                {"type": "cast", "abilityGameID": 6552, "timestamp": 20000},
                {"type": "begincast", "abilityGameID": 6552, "timestamp": 19000},
            ],
            [],
        ]

        results, warnings = _analyze_interrupts(mock_client, "test_report", sample_composition)

        assert len(warnings) == 0
        assert len(results) == 2

        rogue_kicks = [r for r in results if r.player_name == "StabbyRogue"]
        assert len(rogue_kicks) == 1
        assert rogue_kicks[0].spell_name == "Kick"
        assert rogue_kicks[0].count == 2
        assert rogue_kicks[0].timestamps == [10000, 30000]

        warrior_pummels = [r for r in results if r.player_name == "SmashWarrior"]
        assert len(warrior_pummels) == 1
        assert warrior_pummels[0].spell_name == "Pummel"
        assert warrior_pummels[0].count == 1

    def test_empty_config_returns_empty(self, mock_client, sample_composition, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(analysis_mod, "_load_interrupt_config", lambda: {})
        results, warnings = _analyze_interrupts(mock_client, "test_report", sample_composition)
        assert results == []
        assert warnings == []

    def test_api_error_produces_warning(self, mock_client, sample_composition, monkeypatch):
        import requests

        import warcraftlogs_client.analysis as analysis_mod

        config = {1766: "Kick"}
        monkeypatch.setattr(analysis_mod, "_load_interrupt_config", lambda: config)
        mock_client.get_cast_events_paginated.side_effect = requests.RequestException("timeout")

        _results, warnings = _analyze_interrupts(mock_client, "test_report", sample_composition)
        assert len(warnings) == 3
        assert all("Failed to analyze interrupts" in w for w in warnings)

    def test_skips_begincast_events(self, mock_client, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        config = {1766: "Kick"}
        monkeypatch.setattr(analysis_mod, "_load_interrupt_config", lambda: config)

        comp = RaidComposition(
            melee=[PlayerIdentity(name="Rogue", player_class="Rogue", source_id=1, role="melee")],
        )
        mock_client.get_cast_events_paginated.return_value = [
            {"type": "begincast", "abilityGameID": 1766, "timestamp": 10000},
            {"type": "cast", "abilityGameID": 1766, "timestamp": 10500},
        ]

        results, _ = _analyze_interrupts(mock_client, "test", comp)
        assert len(results) == 1
        assert results[0].count == 1
