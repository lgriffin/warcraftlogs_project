"""Tests for totem uptime analysis and DB persistence."""

import json

import pytest

from warcraftlogs_client.analysis import (
    _analyze_totem_uptimes,
    _load_totem_config,
    _merge_bands,
)
from warcraftlogs_client.models import (
    AuraBand,
    AuraUptime,
    EncounterPerformance,
    EncounterSummary,
    PlayerIdentity,
    RaidComposition,
)


@pytest.fixture
def totem_config_file(tmp_path):
    config = {
        "totems": {
            "25587": {"name": "Windfury Totem", "duration": 120},
            "3738": {"name": "Wrath of Air Totem", "duration": 120},
            "25533": {"name": "Searing Totem", "duration": 60},
        }
    }
    path = tmp_path / "totem_config.json"
    path.write_text(json.dumps(config))
    return str(path)


@pytest.fixture
def sample_encounters():
    return [
        EncounterSummary(
            encounter_id=658,
            name="Attumen the Huntsman",
            start_time=100000,
            end_time=340000,
            duration_ms=240000,
            players=[
                EncounterPerformance(
                    name="Shamido",
                    player_class="Shaman",
                    source_id=5,
                    role="melee",
                    total_damage=150_000,
                    total_healing=0,
                    total_damage_taken=20_000,
                ),
            ],
        ),
    ]


@pytest.fixture
def shaman_composition():
    return RaidComposition(
        melee=[
            PlayerIdentity(name="Shamido", player_class="Shaman", source_id=5, role="melee"),
        ],
        ranged=[
            PlayerIdentity(name="RestoSham", player_class="Shaman", source_id=6, role="ranged"),
        ],
    )


class TestLoadTotemConfig:
    def test_loads_totems(self, totem_config_file, monkeypatch):
        import warcraftlogs_client.paths as paths

        monkeypatch.setattr(paths, "get_totem_config_path", lambda: totem_config_file)
        config = _load_totem_config()
        assert 25587 in config
        assert config[25587]["name"] == "Windfury Totem"
        assert config[25587]["duration"] == 120

    def test_returns_empty_when_missing(self, tmp_path, monkeypatch):
        import warcraftlogs_client.paths as paths

        monkeypatch.setattr(paths, "get_totem_config_path", lambda: str(tmp_path / "missing.json"))
        config = _load_totem_config()
        assert config == {}


class TestMergeBands:
    def test_non_overlapping(self):
        bands = [
            AuraBand(start_time=100, end_time=200),
            AuraBand(start_time=300, end_time=400),
        ]
        merged = _merge_bands(bands)
        assert len(merged) == 2

    def test_overlapping(self):
        bands = [
            AuraBand(start_time=100, end_time=300),
            AuraBand(start_time=200, end_time=400),
        ]
        merged = _merge_bands(bands)
        assert len(merged) == 1
        assert merged[0].start_time == 100
        assert merged[0].end_time == 400

    def test_adjacent(self):
        bands = [
            AuraBand(start_time=100, end_time=200),
            AuraBand(start_time=200, end_time=300),
        ]
        merged = _merge_bands(bands)
        assert len(merged) == 1
        assert merged[0].end_time == 300

    def test_contained(self):
        bands = [
            AuraBand(start_time=100, end_time=500),
            AuraBand(start_time=200, end_time=300),
        ]
        merged = _merge_bands(bands)
        assert len(merged) == 1
        assert merged[0].end_time == 500

    def test_empty(self):
        assert _merge_bands([]) == []

    def test_unsorted_input(self):
        bands = [
            AuraBand(start_time=300, end_time=400),
            AuraBand(start_time=100, end_time=200),
        ]
        merged = _merge_bands(bands)
        assert len(merged) == 2
        assert merged[0].start_time == 100


class TestAnalyzeTotemUptimes:
    def test_computes_uptime_from_casts(self, mock_client, shaman_composition, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod,
            "_load_totem_config",
            lambda: {25587: {"name": "Windfury Totem", "duration": 120}},
        )

        mock_client.get_cast_events_paginated.side_effect = [
            [
                {"type": "cast", "abilityGameID": 25587, "timestamp": 100000},
                {"type": "cast", "abilityGameID": 25587, "timestamp": 220000},
                {"type": "cast", "abilityGameID": 99999, "timestamp": 110000},
            ],
            [],
        ]

        results, warnings = _analyze_totem_uptimes(mock_client, "test_report", shaman_composition, sample_encounters)

        assert len(warnings) == 0
        assert len(results) == 1
        uptime = results[0]
        assert uptime.spell_name == "Windfury Totem"
        assert uptime.fight_name == "Attumen the Huntsman"
        assert uptime.uptime_percent == 100.0

    def test_partial_uptime(self, mock_client, shaman_composition, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod,
            "_load_totem_config",
            lambda: {25587: {"name": "Windfury Totem", "duration": 120}},
        )

        mock_client.get_cast_events_paginated.side_effect = [
            [
                {"type": "cast", "abilityGameID": 25587, "timestamp": 100000},
            ],
            [],
        ]

        results, _ = _analyze_totem_uptimes(mock_client, "test_report", shaman_composition, sample_encounters)

        assert len(results) == 1
        assert results[0].uptime_percent == 50.0

    def test_merges_multiple_shamans(self, mock_client, shaman_composition, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod,
            "_load_totem_config",
            lambda: {25587: {"name": "Windfury Totem", "duration": 120}},
        )

        mock_client.get_cast_events_paginated.side_effect = [
            [{"type": "cast", "abilityGameID": 25587, "timestamp": 100000}],
            [{"type": "cast", "abilityGameID": 25587, "timestamp": 200000}],
        ]

        results, _ = _analyze_totem_uptimes(mock_client, "test_report", shaman_composition, sample_encounters)

        assert len(results) == 1
        assert results[0].uptime_percent > 50.0

    def test_empty_config_returns_empty(self, mock_client, shaman_composition, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(analysis_mod, "_load_totem_config", lambda: {})
        results, warnings = _analyze_totem_uptimes(mock_client, "test_report", shaman_composition, sample_encounters)
        assert results == []
        assert warnings == []

    def test_no_shamans_returns_empty(self, mock_client, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod,
            "_load_totem_config",
            lambda: {25587: {"name": "Windfury Totem", "duration": 120}},
        )
        comp = RaidComposition(
            melee=[PlayerIdentity(name="Rogue", player_class="Rogue", source_id=1, role="melee")],
        )
        results, _ = _analyze_totem_uptimes(mock_client, "test", comp, sample_encounters)
        assert results == []

    def test_ignores_casts_fully_outside_fight(self, mock_client, shaman_composition, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod,
            "_load_totem_config",
            lambda: {25587: {"name": "Windfury Totem", "duration": 10}},
        )

        mock_client.get_cast_events_paginated.side_effect = [
            [
                {"type": "cast", "abilityGameID": 25587, "timestamp": 50000},
                {"type": "cast", "abilityGameID": 25587, "timestamp": 350000},
            ],
            [],
        ]

        results, _ = _analyze_totem_uptimes(mock_client, "test_report", shaman_composition, sample_encounters)
        assert results == []

    def test_prepull_totem_counts(self, mock_client, shaman_composition, sample_encounters, monkeypatch):
        import warcraftlogs_client.analysis as analysis_mod

        monkeypatch.setattr(
            analysis_mod,
            "_load_totem_config",
            lambda: {25587: {"name": "Windfury Totem", "duration": 120}},
        )

        mock_client.get_cast_events_paginated.side_effect = [
            [
                {"type": "cast", "abilityGameID": 25587, "timestamp": 95000},
            ],
            [],
        ]

        results, _ = _analyze_totem_uptimes(mock_client, "test_report", shaman_composition, sample_encounters)
        assert len(results) == 1
        assert results[0].uptime_percent > 0
        assert results[0].bands[0].start_time == 100000


class TestTotemUptimeDatabase:
    def test_import_and_load_round_trip(self, db, sample_raid_analysis, sample_encounter_summary):
        sample_raid_analysis.encounters = [sample_encounter_summary]
        sample_raid_analysis.totem_uptimes = [
            AuraUptime(
                spell_id=25587,
                spell_name="Windfury Totem",
                fight_name="Attumen the Huntsman",
                fight_start=12000,
                fight_end=180000,
                uptime_percent=92.5,
                bands=[
                    AuraBand(start_time=12000, end_time=132000),
                    AuraBand(start_time=140000, end_time=180000),
                ],
            ),
        ]

        db.import_raid(sample_raid_analysis)
        loaded = db.get_raid_analysis("abc123")

        assert loaded is not None
        assert len(loaded.totem_uptimes) == 1
        tu = loaded.totem_uptimes[0]
        assert tu.spell_name == "Windfury Totem"
        assert tu.uptime_percent == 92.5
        assert len(tu.bands) == 2
        assert tu.bands[0].start_time == 12000
        assert tu.bands[1].end_time == 180000
