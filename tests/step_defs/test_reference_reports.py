"""Step definitions for reference report comparison feature."""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.models import (
    EncounterPerformance,
    EncounterSummary,
)

scenarios("reference_reports.feature")


@pytest.fixture
def ref_analyses():
    """Mutable dict to accumulate multiple analyses across Given steps."""
    return {}


@given(
    parsers.parse('a raid analysis for report "{report_id}" with healer "{name}"'),
)
def analysis_with_named_healer(build_analysis, report_id, name, ref_analyses):
    ref_analyses[report_id] = build_analysis(report_id=report_id, healer_name=name)


@given(
    parsers.parse('a raid analysis for report "{report_id}" with healing {healing:d}'),
)
def analysis_with_healing(build_analysis, report_id, healing, ref_analyses):
    ref_analyses[report_id] = build_analysis(report_id=report_id, healer_healing=healing)


@given(
    parsers.parse('a raid analysis for report "{report_id}" with encounter "{enc_name}" id {enc_id:d}'),
)
def analysis_with_encounter(build_analysis, report_id, enc_name, enc_id, ref_analyses):
    encounter = EncounterSummary(
        encounter_id=enc_id,
        name=enc_name,
        start_time=12000,
        end_time=180000,
        duration_ms=168000,
        players=[
            EncounterPerformance(
                name="StabbyRogue",
                player_class="Rogue",
                source_id=3,
                role="melee",
                total_damage=150_000,
                total_healing=0,
                total_damage_taken=20_000,
            ),
        ],
    )
    ref_analyses[report_id] = build_analysis(report_id=report_id, encounters=[encounter])


@given(parsers.parse('the analysis is imported as "{source}"'))
def given_import_as_source(db_ctx, analysis_ctx, source):
    db_ctx["db"].import_raid(analysis_ctx["analysis"], source=source)


@when(parsers.parse('the analysis is imported as "{source}"'))
def when_import_as_source(db_ctx, analysis_ctx, source):
    db_ctx["db"].import_raid(analysis_ctx["analysis"], source=source)


@when("the analysis is imported without specifying source")
def import_default_source(db_ctx, analysis_ctx):
    db_ctx["db"].import_raid(analysis_ctx["analysis"])


@when(parsers.parse('"{report_id}" is imported as "{source}"'))
def import_named_as_source(db_ctx, ref_analyses, report_id, source):
    db_ctx["db"].import_raid(ref_analyses[report_id], source=source)


@when(parsers.parse('the label "{label}" is set on "{report_id}"'))
def set_label(db_ctx, label, report_id):
    db_ctx["db"].update_raid_label(report_id, label)


@then(parsers.parse("the guild raid list should have {count:d} entries"))
def check_guild_count(db_ctx, count):
    raids = db_ctx["db"].get_raid_list()
    assert len(raids) == count


@then(parsers.parse("the guild raid list should have {count:d} entry"))
def check_guild_count_singular(db_ctx, count):
    raids = db_ctx["db"].get_raid_list()
    assert len(raids) == count


@then(parsers.parse("the reference raid list should have {count:d} entry"))
def check_ref_count(db_ctx, count):
    raids = db_ctx["db"].get_reference_raids()
    assert len(raids) == count


@then(parsers.parse('character "{name}" should not appear in guild characters'))
def check_char_not_in_guild(db_ctx, name):
    chars = db_ctx["db"].get_all_characters()
    assert not any(c.name == name for c in chars)


@then(parsers.parse('character "{name}" should appear in guild characters'))
def check_char_in_guild(db_ctx, name):
    chars = db_ctx["db"].get_all_characters()
    assert any(c.name == name for c in chars)


@then(parsers.parse('the guild raid count for "{name}" should be {count:d}'))
def check_guild_raid_count(db_ctx, name, count):
    history = db_ctx["db"].get_character_history(name, source="guild")
    assert history is not None
    assert history.total_raids == count


@then("the guild average healing should differ from the reference average healing")
def check_aggregates_differ(db_ctx):
    guild_agg = db_ctx["db"].get_comparison_aggregates(source="guild")
    ref_agg = db_ctx["db"].get_comparison_aggregates(source="reference")
    assert guild_agg["avg_healing"] != ref_agg["avg_healing"]


@then(parsers.parse("there should be {count:d} common encounter"))
def check_common_encounters(db_ctx, count):
    common = db_ctx["db"].get_common_encounters()
    assert len(common) == count


@then(parsers.parse('the source for "{report_id}" should be "{source}"'))
def check_source(db_ctx, report_id, source):
    actual = db_ctx["db"].get_raid_source(report_id)
    assert actual == source


@then(parsers.parse('the label for "{report_id}" should be "{label}"'))
def check_label(db_ctx, report_id, label):
    raids = db_ctx["db"].get_reference_raids()
    matching = [r for r in raids if r["report_id"] == report_id]
    assert len(matching) == 1
    assert matching[0]["label"] == label
