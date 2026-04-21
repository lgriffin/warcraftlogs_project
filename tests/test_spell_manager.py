"""Tests for SpellManager — alias resolution, event processing, resource tracking."""

import json
import os

import pytest

from warcraftlogs_client.spell_manager import (
    SpellBreakdown,
    SpellManager,
    get_spell_manager,
    reset_spell_manager,
)


@pytest.fixture
def spell_dir(tmp_path):
    aliases = {"melee_variants": {"100": 1, "200": 1}}
    names = {"heals": {"2060": "Greater Heal", "139": "Renew"}, "misc": {"1": "Melee"}}
    (tmp_path / "spell_aliases.json").write_text(json.dumps(aliases))
    (tmp_path / "spell_names.json").write_text(json.dumps(names))
    return str(tmp_path)


@pytest.fixture
def mgr(spell_dir):
    return SpellManager(spell_data_dir=spell_dir)


class TestGetCanonicalId:
    def test_with_alias(self, mgr):
        assert mgr.get_canonical_id(100) == 1

    def test_without_alias(self, mgr):
        assert mgr.get_canonical_id(9999) == 9999


class TestGetSpellName:
    def test_found(self, mgr):
        assert mgr.get_spell_name(2060) == "Greater Heal"

    def test_not_found(self, mgr):
        assert mgr.get_spell_name(77777) == "(ID 77777)"

    def test_via_alias(self, mgr):
        assert mgr.get_spell_name(100) == "Melee"


class TestGetVariantIds:
    def test_reverse_lookup(self, mgr):
        variants = mgr.get_variant_ids(1)
        assert 100 in variants
        assert 200 in variants
        assert 1 in variants

    def test_no_variants(self, mgr):
        variants = mgr.get_variant_ids(2060)
        assert 2060 in variants


class TestProcessSpellEvents:
    def test_aggregation(self, mgr):
        events = [
            {"abilityGameID": 100, "amount": 50},
            {"abilityGameID": 200, "amount": 30},
            {"abilityGameID": 2060, "amount": 100},
        ]
        totals = mgr.process_spell_events(events)
        assert totals[1] == 80
        assert totals[2060] == 100

    def test_excludes_judgement_of_light(self, mgr):
        events = [
            {"abilityGameID": 20343, "amount": 999},
            {"abilityGameID": 2060, "amount": 100},
        ]
        totals = mgr.process_spell_events(events)
        assert 20343 not in totals
        assert totals[2060] == 100

    def test_custom_exclusions(self, mgr):
        events = [
            {"abilityGameID": 2060, "amount": 100},
            {"abilityGameID": 139, "amount": 50},
        ]
        totals = mgr.process_spell_events(events, exclude_ids={139})
        assert 139 not in totals
        assert totals[2060] == 100

    def test_empty_events(self, mgr):
        assert mgr.process_spell_events([]) == {}


class TestProcessCastEntries:
    def test_aggregation(self, mgr):
        entries = [
            {"guid": 2060, "name": "Greater Heal", "total": 50},
            {"guid": 139, "name": "Renew", "hitCount": 80},
        ]
        names, casts = mgr.process_cast_entries(entries)
        assert casts[2060] == 50
        assert casts[139] == 80
        assert names[2060] == "Greater Heal"

    def test_excludes_judgement_of_light(self, mgr):
        entries = [
            {"guid": 20343, "name": "Judgement of Light", "total": 999},
            {"guid": 2060, "name": "Greater Heal", "total": 10},
        ]
        names, casts = mgr.process_cast_entries(entries)
        assert 20343 not in casts


class TestGetResourcesUsed:
    def test_super_mana_potion(self, mgr):
        entries = [{"guid": 28499, "name": "Super Mana Potion", "total": 3}]
        resources = mgr.get_resources_used(entries)
        assert resources["Super Mana Potion"] == 3

    def test_dark_rune(self, mgr):
        entries = [{"guid": 27869, "name": "Dark Rune", "hitCount": 2}]
        resources = mgr.get_resources_used(entries)
        assert resources["Dark Rune"] == 2

    def test_empty(self, mgr):
        assert mgr.get_resources_used([]) == {}


class TestGetFearWardUsage:
    def test_found(self, mgr):
        entries = [{"guid": 6346, "total": 5}]
        result = mgr.get_fear_ward_usage(entries)
        assert result is not None
        assert result["casts"] == 5
        assert result["spell"] == "Fear Ward"

    def test_not_found(self, mgr):
        entries = [{"guid": 999, "total": 5}]
        assert mgr.get_fear_ward_usage(entries) is None


class TestCalculateDispels:
    def test_finds_dispel_magic(self, mgr):
        entries = [{"guid": 988, "total": 12}]
        dispels = mgr.calculate_dispels(entries, "Priest")
        assert dispels["Dispel Magic"] == 12

    def test_finds_cleanse(self, mgr):
        entries = [{"guid": 4987, "hitCount": 8}]
        dispels = mgr.calculate_dispels(entries, "Paladin")
        assert dispels["Cleanse"] == 8

    def test_empty(self, mgr):
        assert mgr.calculate_dispels([], "Priest") == {}


class TestMissingFiles:
    def test_missing_aliases_file(self, tmp_path):
        (tmp_path / "spell_names.json").write_text("{}")
        mgr = SpellManager(spell_data_dir=str(tmp_path))
        assert mgr.get_canonical_id(123) == 123

    def test_missing_names_file(self, tmp_path):
        (tmp_path / "spell_aliases.json").write_text("{}")
        mgr = SpellManager(spell_data_dir=str(tmp_path))
        assert mgr.get_spell_name(123) == "(ID 123)"

    def test_invalid_json(self, tmp_path):
        (tmp_path / "spell_aliases.json").write_text("{bad json")
        (tmp_path / "spell_names.json").write_text("{bad json")
        mgr = SpellManager(spell_data_dir=str(tmp_path))
        assert mgr.get_canonical_id(5) == 5
        assert mgr.get_spell_name(5) == "(ID 5)"


class TestAddMappings:
    def test_add_spell_mapping(self, mgr):
        mgr.add_spell_mapping(99999, "New Spell")
        assert mgr.get_spell_name(99999) == "New Spell"

    def test_add_spell_alias(self, mgr):
        mgr.add_spell_alias(55555, 2060)
        assert mgr.get_canonical_id(55555) == 2060


class TestValidateConfiguration:
    def test_valid_config(self, mgr):
        assert mgr.validate_configuration() is True

    def test_circular_alias_detection(self, tmp_path):
        aliases = {"group": {"1": 2, "2": 3, "3": 1}}
        (tmp_path / "spell_aliases.json").write_text(json.dumps(aliases))
        (tmp_path / "spell_names.json").write_text("{}")
        mgr = SpellManager(spell_data_dir=str(tmp_path))
        assert mgr.validate_configuration() is False


class TestModuleLevelFunctions:
    def test_get_spell_manager_singleton(self):
        m1 = get_spell_manager()
        m2 = get_spell_manager()
        assert m1 is m2

    def test_reset_spell_manager(self):
        m1 = get_spell_manager()
        reset_spell_manager()
        m2 = get_spell_manager()
        assert m1 is not m2
