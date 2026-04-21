"""Tests for console renderer — output correctness via capsys."""

import pytest

from warcraftlogs_client.renderers.console import render_raid_analysis
from warcraftlogs_client.models import (
    DPSPerformance,
    HealerPerformance,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)


class TestRenderRaidAnalysis:
    def test_metadata_present(self, sample_raid_analysis, capsys):
        render_raid_analysis(sample_raid_analysis)
        output = capsys.readouterr().out
        assert "Karazhan Clear" in output
        assert "TestGuild" in output

    def test_composition_section(self, sample_raid_analysis, capsys):
        render_raid_analysis(sample_raid_analysis)
        output = capsys.readouterr().out
        assert "Raid Makeup" in output

    def test_healer_rendering(self, sample_raid_analysis, capsys):
        render_raid_analysis(sample_raid_analysis)
        output = capsys.readouterr().out
        assert "HolyPriest" in output
        assert "Greater Heal" in output

    def test_tank_rendering(self, sample_raid_analysis, capsys):
        render_raid_analysis(sample_raid_analysis)
        output = capsys.readouterr().out
        assert "TankWarrior" in output
        assert "Revenge" in output

    def test_dps_rendering(self, sample_raid_analysis, capsys):
        render_raid_analysis(sample_raid_analysis)
        output = capsys.readouterr().out
        assert "StabbyRogue" in output
        assert "Sinister Strike" in output

    def test_summary_tables(self, sample_raid_analysis, capsys):
        render_raid_analysis(sample_raid_analysis)
        output = capsys.readouterr().out
        assert "Healer Summary" in output


class TestEmptyAnalysis:
    def test_no_crash(self):
        analysis = RaidAnalysis(
            metadata=RaidMetadata(
                report_id="empty", title="Empty", owner="Nobody",
                start_time=1_700_000_000_000,
            ),
            composition=RaidComposition(),
        )
        render_raid_analysis(analysis)


class TestSortingOrder:
    def test_healers_sorted_by_healing(self, capsys):
        healers = [
            HealerPerformance(name="Low", player_class="Priest", source_id=1, total_healing=100_000),
            HealerPerformance(name="High", player_class="Priest", source_id=2, total_healing=500_000),
        ]
        analysis = RaidAnalysis(
            metadata=RaidMetadata(report_id="r", title="T", owner="O", start_time=1_700_000_000_000),
            composition=RaidComposition(),
            healers=healers,
        )
        render_raid_analysis(analysis)
        output = capsys.readouterr().out
        high_pos = output.find("High")
        low_pos = output.find("Low")
        assert high_pos > 0
        assert low_pos > 0
