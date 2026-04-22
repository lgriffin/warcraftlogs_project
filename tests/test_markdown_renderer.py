"""Tests for markdown renderer — output correctness and file export."""

import os

import pytest

from warcraftlogs_client.renderers.markdown import (
    export_raid_analysis,
    render_raid_analysis,
)
from warcraftlogs_client.models import (
    ConsumableUsage,
    DPSPerformance,
    DispelUsage,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    ResourceUsage,
    SpellUsage,
    TankPerformance,
)


class TestRenderMetadata:
    def test_title_as_heading(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert md.startswith("# Karazhan Clear")

    def test_owner_present(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "**Owner:** TestGuild" in md

    def test_log_link(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "[abc123](https://www.warcraftlogs.com/reports/abc123)" in md


class TestRenderComposition:
    def test_tanks_listed(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "**Tanks**" in md
        assert "TankWarrior" in md

    def test_healers_listed(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "**Healers**" in md
        assert "HolyPriest" in md

    def test_dps_listed(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "**DPS**" in md
        assert "StabbyRogue" in md
        assert "FrostMage" in md


class TestHealerSummary:
    def test_healer_table_header(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "## Healer Summary" in md
        assert "### Priest" in md

    def test_spell_columns(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "Greater Heal" in md
        assert "Renew" in md

    def test_dispel_column(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "Dispel Magic" in md

    def test_resource_columns(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "Mana Pot" in md
        assert "Dark Rune" in md

    def test_healing_values(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "500,000" in md
        assert "16.7%" in md

    def test_multiple_classes(self):
        healers = [
            HealerPerformance(name="Priest1", player_class="Priest", source_id=1, total_healing=300_000),
            HealerPerformance(name="Pally1", player_class="Paladin", source_id=2, total_healing=200_000),
        ]
        analysis = RaidAnalysis(
            metadata=RaidMetadata(report_id="r", title="T", owner="O", start_time=1_700_000_000_000),
            composition=RaidComposition(),
            healers=healers,
        )
        md = render_raid_analysis(analysis)
        assert "### Priest" in md
        assert "### Paladin" in md


class TestTankSummary:
    def test_tank_section(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "## Tank Summary" in md

    def test_damage_taken_table(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "### Damage Taken" in md
        assert "Melee" in md
        assert "TankWarrior" in md

    def test_abilities_used_table(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "Warrior" in md
        assert "Revenge" in md

    def test_mitigation_percent(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "42.9%" in md


class TestDPSSummary:
    def test_melee_section(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "## Melee DPS Summary" in md
        assert "### Rogue" in md

    def test_dps_values(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "400,000" in md
        assert "Sinister Strike" in md

    def test_ranged_section(self):
        dps = [
            DPSPerformance(
                name="FrostMage", player_class="Mage", source_id=4,
                role="ranged", total_damage=350_000,
                abilities=[SpellUsage(spell_id=116, spell_name="Frostbolt", casts=200, total_amount=350_000)],
            ),
        ]
        analysis = RaidAnalysis(
            metadata=RaidMetadata(report_id="r", title="T", owner="O", start_time=1_700_000_000_000),
            composition=RaidComposition(),
            dps=dps,
        )
        md = render_raid_analysis(analysis)
        assert "## Ranged DPS Summary" in md
        assert "Frostbolt" in md

    def test_no_section_when_empty(self):
        analysis = RaidAnalysis(
            metadata=RaidMetadata(report_id="r", title="T", owner="O", start_time=1_700_000_000_000),
            composition=RaidComposition(),
        )
        md = render_raid_analysis(analysis)
        assert "DPS Summary" not in md


class TestConsumables:
    def test_consumable_section(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        assert "## Consumable Usage" in md
        assert "Super Mana Potion" in md

    def test_no_section_when_empty(self):
        analysis = RaidAnalysis(
            metadata=RaidMetadata(report_id="r", title="T", owner="O", start_time=1_700_000_000_000),
            composition=RaidComposition(),
        )
        md = render_raid_analysis(analysis)
        assert "Consumable Usage" not in md

    def test_multiple_players(self):
        consumables = [
            ConsumableUsage(player_name="Alice", player_role="healer", report_id="r",
                            consumable_name="Super Mana Potion", count=5),
            ConsumableUsage(player_name="Bob", player_role="melee", report_id="r",
                            consumable_name="Haste Potion", count=2),
            ConsumableUsage(player_name="Alice", player_role="healer", report_id="r",
                            consumable_name="Dark Rune", count=3),
        ]
        analysis = RaidAnalysis(
            metadata=RaidMetadata(report_id="r", title="T", owner="O", start_time=1_700_000_000_000),
            composition=RaidComposition(),
            consumables=consumables,
        )
        md = render_raid_analysis(analysis)
        assert "Alice" in md
        assert "Bob" in md
        assert "Haste Potion" in md
        assert "Dark Rune" in md

    def test_zero_count_excluded(self):
        consumables = [
            ConsumableUsage(player_name="Alice", player_role="healer", report_id="r",
                            consumable_name="Super Mana Potion", count=0),
        ]
        analysis = RaidAnalysis(
            metadata=RaidMetadata(report_id="r", title="T", owner="O", start_time=1_700_000_000_000),
            composition=RaidComposition(),
            consumables=consumables,
        )
        md = render_raid_analysis(analysis)
        assert "Consumable Usage" not in md


class TestExportFile:
    def test_writes_file(self, sample_raid_analysis, tmp_path):
        out = str(tmp_path / "report.md")
        result = export_raid_analysis(sample_raid_analysis, output_path=out)
        assert result == out
        assert os.path.exists(out)
        content = open(out, encoding="utf-8").read()
        assert "# Karazhan Clear" in content

    def test_auto_path(self, sample_raid_analysis, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = export_raid_analysis(sample_raid_analysis)
        assert "Karazhan_Clear" in result
        assert os.path.exists(result)

    def test_creates_directory(self, sample_raid_analysis, tmp_path):
        out = str(tmp_path / "subdir" / "report.md")
        export_raid_analysis(sample_raid_analysis, output_path=out)
        assert os.path.exists(out)


class TestEmptyAnalysis:
    def test_no_crash(self):
        analysis = RaidAnalysis(
            metadata=RaidMetadata(
                report_id="empty", title="Empty", owner="Nobody",
                start_time=1_700_000_000_000,
            ),
            composition=RaidComposition(),
        )
        md = render_raid_analysis(analysis)
        assert "# Empty" in md

    def test_markdown_is_valid_tables(self, sample_raid_analysis):
        md = render_raid_analysis(sample_raid_analysis)
        for line in md.splitlines():
            if line.startswith("|"):
                assert line.endswith("|"), f"Table row not terminated: {line}"
