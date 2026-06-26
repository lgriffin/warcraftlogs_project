"""Step definitions for markdown report export feature."""

from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.models import (
    DPSPerformance,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)
from warcraftlogs_client.renderers.markdown import export_raid_analysis, render_raid_analysis

scenarios("report_export.feature")


def _make_analysis(title="Test Raid", owner="TestGuild"):
    metadata = RaidMetadata(
        report_id="abc123",
        title=title,
        owner=owner,
        start_time=1_700_000_000_000,
        end_time=1_700_003_600_000,
    )
    composition = RaidComposition(
        tanks=[PlayerIdentity(name="TankWarrior", player_class="Warrior", source_id=2, role="tank")],
        healers=[PlayerIdentity(name="HolyPriest", player_class="Priest", source_id=1, role="healer")],
        melee=[PlayerIdentity(name="StabbyRogue", player_class="Rogue", source_id=3, role="melee")],
        ranged=[],
    )
    return RaidAnalysis(
        metadata=metadata,
        composition=composition,
        healers=[
            HealerPerformance(
                name="HolyPriest",
                player_class="Priest",
                source_id=1,
                total_healing=500_000,
                total_overhealing=100_000,
                spells=[SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=50, total_amount=300_000)],
                dispels=[],
                resources=[],
                fear_ward_casts=0,
            )
        ],
        tanks=[
            TankPerformance(
                name="TankWarrior",
                player_class="Warrior",
                source_id=2,
                total_damage_taken=800_000,
                total_mitigated=600_000,
                damage_taken_breakdown=[],
                abilities_used=[],
            )
        ],
        dps=[
            DPSPerformance(
                name="StabbyRogue",
                player_class="Rogue",
                source_id=3,
                role="melee",
                total_damage=400_000,
                abilities=[],
            )
        ],
        consumables=[],
    )


@given(
    parsers.parse('a completed raid analysis for "{title}"'),
    target_fixture="export_ctx",
)
def analysis_for_title(title):
    return {"analysis": _make_analysis(title=title)}


@given(
    parsers.parse('a completed raid analysis owned by "{owner}"'),
    target_fixture="export_ctx",
)
def analysis_for_owner(owner):
    return {"analysis": _make_analysis(owner=owner)}


@given("a completed raid analysis with tanks, healers, and DPS", target_fixture="export_ctx")
def analysis_with_roles():
    return {"analysis": _make_analysis()}


@given(
    parsers.parse('a completed raid analysis with a healer named "{name}"'),
    target_fixture="export_ctx",
)
def analysis_with_healer(name):
    a = _make_analysis()
    a.healers[0] = HealerPerformance(
        name=name,
        player_class="Priest",
        source_id=1,
        total_healing=500_000,
        total_overhealing=100_000,
        spells=[SpellUsage(spell_id=2060, spell_name="Greater Heal", casts=50, total_amount=300_000)],
        dispels=[],
        resources=[],
        fear_ward_casts=0,
    )
    return {"analysis": a}


@when("the analysis is rendered to markdown", target_fixture="render_result")
def render_markdown(export_ctx, monkeypatch):
    monkeypatch.setattr("warcraftlogs_client.config.load_config", lambda config_file=None: {"wcl_api_url": ""})
    md = render_raid_analysis(export_ctx["analysis"])
    return {"markdown": md}


@when("the analysis is exported to a file", target_fixture="render_result")
def export_to_file(export_ctx, tmp_path, monkeypatch):
    monkeypatch.setattr("warcraftlogs_client.config.load_config", lambda config_file=None: {"wcl_api_url": ""})
    out = str(tmp_path / "report.md")
    export_raid_analysis(export_ctx["analysis"], output_path=out)
    return {"path": out}


@then(parsers.parse('the markdown should start with "{prefix}"'))
def check_starts_with(render_result, prefix):
    assert render_result["markdown"].startswith(prefix)


@then(parsers.parse('the markdown should contain "{text}"'))
def check_contains(render_result, text):
    assert text in render_result["markdown"]


@then("the file should exist")
def check_file_exists(render_result):
    import os

    assert os.path.exists(render_result["path"])


@then(parsers.parse('the file should contain "{text}"'))
def check_file_contains(render_result, text):
    with open(render_result["path"]) as f:
        content = f.read()
    assert text in content
