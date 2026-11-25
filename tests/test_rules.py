"""Game rulesets (``wcl_core.rules``): what is bundled, how a raid's ruleset is picked, and that analysis uses it."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from wcl_core import paths
from wcl_core.analysis import (
    _get_resources_from_events,
    _identify_healers,
    _identify_tanks,
    analyze_raid,
    apply_role_overrides,
)
from wcl_core.flasks import load_catalog
from wcl_core.game_version import BURNING_CRUSADE, CLASSIC_ERA, WRATH
from wcl_core.models import PlayerIdentity, RaidComposition, RaidMetadata
from wcl_core.rules import DEFAULT_RULESET, RULESETS, TBC, GameRules, default_rules, load_ruleset, rules_for

CATALOGS = (
    "consumes_config.json",
    "interrupt_config.json",
    "debuff_config.json",
    "totem_config.json",
    "cooldowns_config.json",
)


class TestBundledRulesets:
    @pytest.mark.parametrize("name", sorted(set(RULESETS.values()) | {DEFAULT_RULESET}))
    def test_each_ruleset_ships_its_rules_and_every_catalog(self, name):
        folder = paths.get_ruleset_dir(name)
        assert (folder / "rules.json").is_file()
        for catalog in CATALOGS:
            assert (folder / catalog).is_file(), catalog
            json.loads((folder / catalog).read_text(encoding="utf-8"))

    @pytest.mark.parametrize(("expansion", "name"), sorted(RULESETS.items()))
    def test_each_ruleset_is_for_the_expansion_it_is_filed_under(self, expansion, name):
        assert load_ruleset(name).expansion == expansion

    def test_the_tbc_ruleset_holds_the_rules_the_analysis_always_used(self):
        rules = load_ruleset(TBC)
        assert rules.name == TBC
        assert rules.expansion == BURNING_CRUSADE
        assert rules.tank_classes == {"Warrior", "Druid", "Paladin"}
        assert rules.healer_classes == {"Priest", "Paladin", "Druid", "Shaman"}
        assert rules.hybrid_classes == {"Paladin", "Druid", "Shaman", "Priest"}
        assert rules.always_ranged == {"Mage", "Warlock", "Hunter"}
        assert rules.always_melee == {"Rogue", "Warrior"}
        assert rules.resource_spells == {28499: "Super Mana Potion", 27869: "Dark Rune", 16666: "Demonic Rune"}
        assert rules.class_resources == {
            "Priest": 0,
            "Paladin": 0,
            "Druid": 0,
            "Shaman": 0,
            "Mage": 0,
            "Warlock": 0,
            "Hunter": 0,
            "Warrior": 1,
            "Rogue": 3,
        }
        assert rules.heroism_ids == {32182, 2825}

    def test_the_default_config_paths_are_the_default_rulesets_catalogs(self):
        rules = default_rules()
        assert paths.get_consumes_config_path() == rules.config_path("consumes_config.json")
        assert paths.get_cooldowns_config_path() == rules.config_path("cooldowns_config.json")


class TestPickingARuleset:
    def test_tbc_raids_get_the_tbc_ruleset(self):
        assert rules_for(BURNING_CRUSADE).name == TBC

    @pytest.mark.parametrize("expansion", [None, "", CLASSIC_ERA, WRATH, "Some Future Expansion"])
    def test_an_expansion_without_a_ruleset_gets_the_default_one(self, expansion):
        assert rules_for(expansion) is default_rules()

    def test_a_ruleset_is_read_once(self):
        assert load_ruleset(TBC) is load_ruleset(TBC)


def _rules_in(tmp_path, **classes: list[str]) -> GameRules:
    raw = {"expansion": "Test Expansion", "classes": classes, "heroism_ids": [1]}
    (tmp_path / "rules.json").write_text(json.dumps(raw), encoding="utf-8")
    return GameRules.from_dir(tmp_path)


class TestAnalysisFollowsTheRuleset:
    def test_a_ruleset_is_read_from_its_folder(self, tmp_path):
        rules = _rules_in(tmp_path, tank=["Death Knight"])
        assert rules.name == tmp_path.name
        assert rules.expansion == "Test Expansion"
        assert rules.tank_classes == {"Death Knight"}
        assert rules.healer_classes == frozenset()
        assert rules.resource_spells == {}
        assert rules.config_path("consumes_config.json") == tmp_path / "consumes_config.json"

    def test_dps_override_uses_the_rulesets_ranged_classes(self, tmp_path):
        hunter = PlayerIdentity(name="Arrow", player_class="Hunter", source_id=1, role="tank")
        composition = RaidComposition(tanks=[hunter], healers=[], melee=[], ranged=[])

        tbc, _ = apply_role_overrides(composition, {"Arrow": "dps"})
        assert [p.name for p in tbc.ranged] == ["Arrow"]

        melee_hunters = replace(default_rules(), always_ranged=frozenset(), always_melee=frozenset({"Hunter"}))
        moved, _ = apply_role_overrides(composition, {"Arrow": "dps"}, rules=melee_hunters)
        assert [p.name for p in moved.melee] == ["Arrow"]

    def test_tank_and_healer_candidates_come_from_the_ruleset(self, mock_client):
        actors = [{"name": "Rot", "subType": "Death Knight", "id": 7}]
        mock_client.get_damage_taken_data.return_value = [{"type": "damage", "amount": 500_000, "mitigated": 500_000}]
        mock_client.get_healing_data.return_value = [{"type": "heal", "amount": 5_000_000}]

        assert _identify_tanks(mock_client, "r1", actors, 150_000, 40) == []
        assert _identify_healers(mock_client, "r1", actors, 200_000) == []

        dk_rules = replace(
            default_rules(), tank_classes=frozenset({"Death Knight"}), healer_classes=frozenset({"Death Knight"})
        )
        assert [t.name for t in _identify_tanks(mock_client, "r1", actors, 150_000, 40, dk_rules)] == ["Rot"]
        assert [h.name for h in _identify_healers(mock_client, "r1", actors, 200_000, dk_rules)] == ["Rot"]

    def test_analyze_raid_picks_the_ruleset_from_the_reports_expansion(self, mock_client, monkeypatch):
        import wcl_core.analysis as analysis_mod

        picked: list[str | None] = []

        def spy(expansion):
            picked.append(expansion)
            return default_rules()

        monkeypatch.setattr(analysis_mod, "rules_for", spy)
        mock_client.get_report_metadata.return_value = RaidMetadata(
            report_id="r1", title="T", owner="o", start_time=0, zone="Karazhan"
        )
        mock_client.get_master_data.return_value = []
        mock_client.get_fights.return_value = []
        analyze_raid(mock_client, "r1")
        assert picked == [BURNING_CRUSADE]

    def test_the_flask_catalog_is_read_from_a_ruleset(self):
        assert load_catalog(TBC) == load_catalog()
        assert "Flask of Supreme Power" in load_catalog(TBC).names

    def test_mana_consumables_from_casts_are_the_rulesets(self, mock_client):
        mock_client.get_cast_events_paginated.return_value = [
            {"type": "cast", "abilityGameID": 28499},
            {"type": "begincast", "abilityGameID": 28499},
            {"type": "cast", "abilityGameID": 17531},
        ]
        assert _get_resources_from_events(mock_client, "r1", 1) == {"Super Mana Potion": 1}

        classic = replace(default_rules(), resource_spells={17531: "Major Mana Potion"})
        assert _get_resources_from_events(mock_client, "r1", 1, classic) == {"Major Mana Potion": 1}
