"""Tests for the analysis pipeline — role detection and data processing."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from warcraftlogs_client.analysis import (
    _classify_hybrid_role,
    _identify_composition,
    _identify_healers,
    _identify_tanks,
    _load_consumes_config,
    _analyze_consumables,
    analyze_raid,
)
from warcraftlogs_client.models import PlayerIdentity, RaidComposition, RaidMetadata


class TestClassifyHybridRole:
    def test_melee_heavy(self, mock_client):
        mock_client.get_damage_done_data.return_value = [
            {"type": "damage", "abilityGameID": 1, "amount": 700},
            {"type": "damage", "abilityGameID": 9999, "amount": 300},
        ]
        assert _classify_hybrid_role(mock_client, "r1", 1, "Warrior") == "melee"

    def test_ranged_heavy(self, mock_client):
        mock_client.get_damage_done_data.return_value = [
            {"type": "damage", "abilityGameID": 1, "amount": 100},
            {"type": "damage", "abilityGameID": 9999, "amount": 900},
        ]
        assert _classify_hybrid_role(mock_client, "r1", 1, "Druid") == "ranged"

    def test_no_damage_defaults_melee(self, mock_client):
        mock_client.get_damage_done_data.return_value = []
        assert _classify_hybrid_role(mock_client, "r1", 1, "Paladin") == "melee"

    def test_api_error_defaults_melee(self, mock_client):
        mock_client.get_damage_done_data.side_effect = RuntimeError("API error")
        assert _classify_hybrid_role(mock_client, "r1", 1, "Shaman") == "melee"

    def test_boundary_40_percent(self, mock_client):
        mock_client.get_damage_done_data.return_value = [
            {"type": "damage", "abilityGameID": 1, "amount": 40},
            {"type": "damage", "abilityGameID": 9999, "amount": 60},
        ]
        assert _classify_hybrid_role(mock_client, "r1", 1, "Druid") == "ranged"

    def test_exactly_41_percent_melee(self, mock_client):
        mock_client.get_damage_done_data.return_value = [
            {"type": "damage", "abilityGameID": 1, "amount": 41},
            {"type": "damage", "abilityGameID": 9999, "amount": 59},
        ]
        assert _classify_hybrid_role(mock_client, "r1", 1, "Druid") == "melee"


class TestIdentifyTanks:
    def test_above_threshold(self, mock_client):
        mock_client.get_damage_taken_data.return_value = [
            {"type": "damage", "amount": 200_000, "mitigated": 400_000},
        ]
        actors = [{"name": "Tank1", "id": 1, "type": "Player", "subType": "Warrior"}]
        tanks = _identify_tanks(mock_client, "r1", actors, 150_000, 40)
        assert len(tanks) == 1
        assert tanks[0].name == "Tank1"

    def test_below_threshold(self, mock_client):
        mock_client.get_damage_taken_data.return_value = [
            {"type": "damage", "amount": 50_000, "mitigated": 10_000},
        ]
        actors = [{"name": "Weak", "id": 1, "type": "Player", "subType": "Warrior"}]
        tanks = _identify_tanks(mock_client, "r1", actors, 150_000, 40)
        assert len(tanks) == 0

    def test_non_tank_class_ignored(self, mock_client):
        actors = [{"name": "Mage1", "id": 1, "type": "Player", "subType": "Mage"}]
        tanks = _identify_tanks(mock_client, "r1", actors, 150_000, 40)
        assert len(tanks) == 0


class TestIdentifyHealers:
    def test_above_threshold(self, mock_client):
        mock_client.get_healing_data.return_value = [
            {"type": "heal", "amount": 300_000},
        ]
        actors = [{"name": "Healer1", "id": 1, "type": "Player", "subType": "Priest"}]
        healers = _identify_healers(mock_client, "r1", actors, 200_000)
        assert len(healers) == 1

    def test_below_threshold(self, mock_client):
        mock_client.get_healing_data.return_value = [
            {"type": "heal", "amount": 50_000},
        ]
        actors = [{"name": "ShadowP", "id": 1, "type": "Player", "subType": "Priest"}]
        healers = _identify_healers(mock_client, "r1", actors, 200_000)
        assert len(healers) == 0


class TestIdentifyComposition:
    def test_full_raid(self, mock_client, sample_master_actors):
        mock_client.get_damage_taken_data.return_value = [
            {"type": "damage", "amount": 200_000, "mitigated": 500_000},
        ]
        mock_client.get_healing_data.return_value = [
            {"type": "heal", "amount": 300_000},
        ]
        mock_client.get_damage_done_data.return_value = []

        comp = _identify_composition(mock_client, "r1", sample_master_actors, 200_000, 150_000, 40)
        assert isinstance(comp, RaidComposition)
        assert len(comp.all_players) > 0

    def test_rogue_always_melee(self, mock_client):
        actors = [{"name": "R", "id": 1, "type": "Player", "subType": "Rogue"}]
        mock_client.get_damage_taken_data.return_value = []
        mock_client.get_healing_data.return_value = []
        comp = _identify_composition(mock_client, "r1", actors, 200_000, 150_000, 40)
        assert len(comp.melee) == 1
        assert comp.melee[0].name == "R"

    def test_mage_always_ranged(self, mock_client):
        actors = [{"name": "M", "id": 1, "type": "Player", "subType": "Mage"}]
        mock_client.get_damage_taken_data.return_value = []
        mock_client.get_healing_data.return_value = []
        comp = _identify_composition(mock_client, "r1", actors, 200_000, 150_000, 40)
        assert len(comp.ranged) == 1
        assert comp.ranged[0].name == "M"


class TestLoadConsumesConfig:
    def test_missing_file_returns_defaults(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "warcraftlogs_client.analysis.os.path.dirname",
            lambda _: str(tmp_path),
        )
        result = _load_consumes_config()
        assert result == {"buff_consumables": {}, "cast_consumables": {}}


class TestAnalyzeConsumables:
    def test_buff_tracking(self, mock_client, sample_composition, tmp_path, monkeypatch):
        config = {
            "buff_consumables": {"28507": "Haste Potion"},
            "cast_consumables": {},
        }
        config_path = tmp_path / "consumes_config.json"
        config_path.write_text(json.dumps(config))
        monkeypatch.setattr(
            "warcraftlogs_client.analysis._load_consumes_config",
            lambda: config,
        )

        mock_client.get_buffs_table.return_value = {
            "data": {"auras": [
                {"guid": 28507, "totalUses": 2, "bands": [
                    {"startTime": 10_000}, {"startTime": 20_000},
                ]},
            ]},
        }
        mock_client.get_cast_events_paginated.return_value = []

        result = _analyze_consumables(mock_client, "r1", sample_composition)
        haste = [c for c in result if c.consumable_name == "Haste Potion"]
        assert len(haste) > 0
        assert haste[0].count == 2

    def test_cast_tracking(self, mock_client, sample_composition, monkeypatch):
        config = {
            "buff_consumables": {},
            "cast_consumables": {"28499": "Super Mana Potion"},
        }
        monkeypatch.setattr(
            "warcraftlogs_client.analysis._load_consumes_config",
            lambda: config,
        )

        mock_client.get_buffs_table.return_value = {"data": {"auras": []}}
        mock_client.get_cast_events_paginated.return_value = [
            {"abilityGameID": 28499, "timestamp": 60_000},
            {"abilityGameID": 28499, "timestamp": 180_000},
        ]

        result = _analyze_consumables(mock_client, "r1", sample_composition)
        mana = [c for c in result if c.consumable_name == "Super Mana Potion"]
        assert len(mana) > 0
        assert mana[0].count == 2
        assert 60_000 in mana[0].timestamps


class TestAnalyzeRaid:
    def test_end_to_end(self, mock_client, monkeypatch):
        mock_client.get_report_metadata.return_value = RaidMetadata(
            report_id="r1", title="Test", owner="Owner",
            start_time=1_700_000_000_000,
        )
        mock_client.get_master_data.return_value = [
            {"name": "Healer", "id": 1, "type": "Player", "subType": "Priest"},
            {"name": "Tank", "id": 2, "type": "Player", "subType": "Warrior"},
            {"name": "DPS", "id": 3, "type": "Player", "subType": "Rogue"},
        ]
        mock_client.get_healing_data.return_value = [
            {"type": "heal", "amount": 300_000, "overheal": 50_000, "abilityGameID": 2060},
        ]
        mock_client.get_damage_taken_data.return_value = [
            {"type": "damage", "amount": 200_000, "mitigated": 500_000, "abilityGameID": 1},
        ]
        mock_client.get_damage_done_data.return_value = [
            {"type": "damage", "amount": 150_000, "abilityGameID": 1},
        ]
        mock_client.run_query.return_value = {
            "data": {"reportData": {"report": {"table": {"data": {"entries": []}}}}}
        }
        mock_client.get_buffs_table.return_value = {"data": {"auras": []}}
        mock_client.get_cast_events_paginated.return_value = []
        mock_client.get_damage_taken_table.return_value = []
        mock_client.get_damage_done_table.return_value = []

        monkeypatch.setattr(
            "warcraftlogs_client.analysis._load_consumes_config",
            lambda: {"buff_consumables": {}, "cast_consumables": {}},
        )

        analysis = analyze_raid(mock_client, "r1")
        assert analysis.metadata.report_id == "r1"
        assert len(analysis.composition.all_players) > 0
