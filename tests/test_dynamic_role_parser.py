"""Tests for dynamic role identification logic."""

from warcraftlogs_client.dynamic_role_parser import group_players_by_class, identify_healers


class TestGroupPlayersByClass:
    def test_groups_correctly(self, sample_master_actors):
        groups = group_players_by_class(sample_master_actors)
        assert "Warrior" in groups
        assert "Priest" in groups
        assert len(groups["Warrior"]) == 1
        assert groups["Warrior"][0]["name"] == "TankWarrior"

    def test_npcs_excluded(self, sample_master_actors):
        groups = group_players_by_class(sample_master_actors)
        all_names = [p["name"] for players in groups.values() for p in players]
        assert "Onyxia" not in all_names

    def test_empty_input(self):
        groups = group_players_by_class([])
        assert len(groups) == 0

    def test_subtype_preserved(self, sample_master_actors):
        groups = group_players_by_class(sample_master_actors)
        for cls, players in groups.items():
            for p in players:
                assert p["subType"] == cls


class TestIdentifyHealers:
    def test_above_threshold(self, sample_master_actors):
        healing_totals = {"HolyPriest": 200_000}
        healers = identify_healers(sample_master_actors, healing_totals, 50_000)
        assert len(healers) == 1
        assert healers[0]["name"] == "HolyPriest"
        assert healers[0]["class"] == "Priest"

    def test_below_threshold(self, sample_master_actors):
        healing_totals = {"HolyPriest": 10_000}
        healers = identify_healers(sample_master_actors, healing_totals, 50_000)
        assert len(healers) == 0

    def test_non_healing_class_excluded(self, sample_master_actors):
        healing_totals = {"StabbyRogue": 999_999}
        healers = identify_healers(sample_master_actors, healing_totals, 50_000)
        assert len(healers) == 0

    def test_npc_filtered(self, sample_master_actors):
        healing_totals = {"Onyxia": 999_999}
        healers = identify_healers(sample_master_actors, healing_totals, 50_000)
        assert len(healers) == 0

    def test_multiple_healers(self):
        actors = [
            {"name": "Priest1", "id": 1, "type": "Player", "subType": "Priest"},
            {"name": "Paladin1", "id": 2, "type": "Player", "subType": "Paladin"},
            {"name": "Druid1", "id": 3, "type": "Player", "subType": "Druid"},
        ]
        totals = {"Priest1": 100_000, "Paladin1": 80_000, "Druid1": 60_000}
        healers = identify_healers(actors, totals, 50_000)
        assert len(healers) == 3

    def test_empty_healing_totals(self, sample_master_actors):
        healers = identify_healers(sample_master_actors, {}, 50_000)
        assert len(healers) == 0

    def test_exact_threshold_not_included(self, sample_master_actors):
        healing_totals = {"HolyPriest": 50_000}
        healers = identify_healers(sample_master_actors, healing_totals, 50_000)
        assert len(healers) == 0
