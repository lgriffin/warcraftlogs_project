"""Flasks and elixirs: the bundled catalogue, preparation, and boss-pull coverage from buffs-table auras."""

from __future__ import annotations

import json

import pytest
from wcl_core import paths
from wcl_core.flasks import (
    BATTLE_ELIXIR,
    FLASK,
    GUARDIAN_ELIXIR,
    NOT_PREPARED,
    PREPARED_ELIXIRS,
    PREPARED_FLASK,
    PULL_GRACE_MS,
    FlaskCatalog,
    boss_pulls,
    flask_coverage,
    load_catalog,
    preparation,
)

from warcraftlogs_client.analysis import _analyze_consumables, _analyze_consumables_and_flasks
from warcraftlogs_client.models import PlayerIdentity

CONFIG = {
    "buff_consumables": {"28507": "Haste Potion"},
    "flasks": {"28520": "Flask of Relentless Assault"},
    "battle_elixirs": {"28497": "Elixir of Major Agility"},
    "guardian_elixirs": {"28502": "Elixir of Major Defense"},
}
CATALOG = FlaskCatalog.from_config(CONFIG)
ROGUE = PlayerIdentity("StabbyRogue", "Rogue", 3, "melee")


def _aura(guid: int, *bands: tuple[int, int], name: str = "") -> dict:
    return {
        "guid": guid,
        "name": name,
        "totalUses": len(bands),
        "bands": [{"startTime": s, "endTime": e} for s, e in bands],
    }


# ── Catalogue ──


class TestCatalogue:
    def test_bundled_config_has_every_kind_and_no_id_in_two_sections(self):
        config = json.loads(paths.get_consumes_config_path().read_text(encoding="utf-8"))
        catalog = load_catalog()
        kinds = {kind for _name, kind in catalog.auras.values()}
        assert kinds == {FLASK, BATTLE_ELIXIR, GUARDIAN_ELIXIR}
        sections = ("buff_consumables", "cast_consumables", "flasks", "battle_elixirs", "guardian_elixirs")
        ids = [spell_id for s in sections for spell_id in config[s]]
        assert len(ids) == len(set(ids)), "an aura id is listed in two sections"
        assert catalog.kind_of("Flask of Relentless Assault") == FLASK
        assert catalog.kind_of("adept's elixir") == BATTLE_ELIXIR
        assert catalog.kind_of("Elixir of Major Mageblood") == GUARDIAN_ELIXIR
        assert catalog.kind_of("Haste Potion") == ""

    def test_names_keep_config_order_and_bad_entries_are_skipped(self, caplog):
        catalog = FlaskCatalog.from_config({**CONFIG, "flasks": {"x": "Bad", "28520": "Flask of Relentless Assault"}})
        assert catalog.names == ("Flask of Relentless Assault", "Elixir of Major Agility", "Elixir of Major Defense")
        assert "Ignoring flasks entry" in caplog.text
        assert FlaskCatalog.from_config({"flasks": "nope"}).names == ()


class TestPreparation:
    @pytest.mark.parametrize(
        ("names", "expected"),
        [
            (["Flask of Relentless Assault"], PREPARED_FLASK),
            (["Flask of Relentless Assault", "Elixir of Major Agility"], PREPARED_FLASK),
            (["Elixir of Major Agility", "ELIXIR OF MAJOR DEFENSE"], PREPARED_ELIXIRS),
            (["Elixir of Major Agility"], NOT_PREPARED),
            (["Elixir of Major Defense", "Haste Potion"], NOT_PREPARED),
            ([], NOT_PREPARED),
        ],
    )
    def test_a_flask_or_a_battle_and_guardian_elixir(self, names, expected):
        assert preparation(names, CATALOG) == expected

    def test_boss_pulls_are_fights_with_an_encounter_kills_and_wipes(self):
        fights = [
            {"startTime": 900, "encounterID": 649, "kill": True},
            {"startTime": 100, "encounterID": 0},  # trash
            {"startTime": 500, "encounterID": 649, "kill": False},
        ]
        assert boss_pulls(fights) == [500, 900]


# ── Coverage ──


class TestCoverage:
    def test_flask_and_elixir_pair_pulls(self):
        auras = [
            _aura(28520, (0, 100_000)),  # flask for the first pull only
            _aura(28497, (150_000, 400_000)),  # battle elixir ...
            _aura(28502, (190_000, 400_000)),  # ... and a guardian one for the second
            _aura(28507, (0, 400_000)),  # a potion buff is not a flask
        ]
        cov = flask_coverage(ROGUE, "r1", auras, [50_000, 200_000, 500_000], CATALOG)
        assert (cov.boss_pulls, cov.flask_pulls, cov.elixir_pair_pulls, cov.prepared_pulls) == (3, 1, 1, 2)
        assert cov.to_dict() == {
            "name": "StabbyRogue",
            "role": "melee",
            "report_id": "r1",
            "boss_pulls": 3,
            "prepared_pulls": 2,
            "flask_pulls": 1,
            "elixir_pair_pulls": 1,
            "flasks": ["Flask of Relentless Assault"],
            "battle_elixirs": ["Elixir of Major Agility"],
            "guardian_elixirs": ["Elixir of Major Defense"],
        }

    def test_an_aura_drunk_on_the_pull_counts_and_one_that_ran_out_does_not(self):
        pull = 100_000
        on_pull = flask_coverage(ROGUE, "r1", [_aura(28520, (pull + PULL_GRACE_MS, 200_000))], [pull], CATALOG)
        late = flask_coverage(ROGUE, "r1", [_aura(28520, (pull + PULL_GRACE_MS + 1, 200_000))], [pull], CATALOG)
        expired = flask_coverage(ROGUE, "r1", [_aura(28520, (0, pull))], [pull], CATALOG)
        assert (on_pull.flask_pulls, late.flask_pulls, expired.flask_pulls) == (1, 0, 0)
        assert expired.flasks == ["Flask of Relentless Assault"]  # still listed as used in the raid

    def test_a_flask_pull_is_not_also_an_elixir_pair_pull(self):
        auras = [_aura(28520, (0, 10)), _aura(28497, (0, 10)), _aura(28502, (0, 10))]
        cov = flask_coverage(ROGUE, "r1", auras, [5], CATALOG)
        assert (cov.flask_pulls, cov.elixir_pair_pulls) == (1, 0)


class TestAnalysis:
    @pytest.fixture(autouse=True)
    def config(self, monkeypatch):
        monkeypatch.setattr("warcraftlogs_client.analysis._load_consumes_config", lambda: CONFIG)

    def test_flasks_and_elixirs_are_recorded_as_consumables_with_coverage(self, mock_client, sample_composition):
        mock_client.get_buffs_table.return_value = {
            "data": {"auras": [_aura(28520, (0, 50_000), (60_000, 400_000)), _aura(28507, (300_000, 315_000))]}
        }
        consumables, coverage, warnings = _analyze_consumables_and_flasks(
            mock_client, "r1", sample_composition, [100_000, 350_000]
        )
        assert warnings == []
        flasks = [c for c in consumables if c.consumable_name == "Flask of Relentless Assault"]
        assert len(flasks) == 4  # every player in the composition got the same table
        assert (flasks[0].count, flasks[0].timestamps) == (2, [0, 60_000])
        assert [c.prepared_pulls for c in coverage] == [2, 2, 2, 2]
        assert {c.player_name for c in coverage} == {p.name for p in sample_composition.all_players}

    def test_no_boss_pulls_means_no_coverage(self, mock_client, sample_composition):
        mock_client.get_buffs_table.return_value = {"data": {"auras": [_aura(28520, (0, 50_000))]}}
        _consumables, coverage, _warnings = _analyze_consumables_and_flasks(mock_client, "r1", sample_composition, [])
        assert coverage == []
        consumables, _warnings = _analyze_consumables(mock_client, "r1", sample_composition)
        assert {c.consumable_name for c in consumables} == {"Flask of Relentless Assault"}
