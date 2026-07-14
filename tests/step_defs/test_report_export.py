"""Step definitions for markdown report export feature."""

from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.models import HealerPerformance, SpellUsage
from warcraftlogs_client.renderers.markdown import export_raid_analysis, render_raid_analysis

scenarios("report_export.feature")


@given(
    parsers.parse('a completed raid analysis for "{title}"'),
    target_fixture="export_ctx",
)
def analysis_for_title(build_analysis, title):
    return {"analysis": build_analysis(title=title)}


@given(
    parsers.parse('a completed raid analysis owned by "{owner}"'),
    target_fixture="export_ctx",
)
def analysis_for_owner(build_analysis, owner):
    return {"analysis": build_analysis(owner=owner)}


@given("a completed raid analysis with tanks, healers, and DPS", target_fixture="export_ctx")
def analysis_with_roles(build_analysis):
    return {"analysis": build_analysis()}


@given(
    parsers.parse('a completed raid analysis with a healer named "{name}"'),
    target_fixture="export_ctx",
)
def analysis_with_healer(build_analysis, name):
    return {"analysis": build_analysis(healer_name=name)}


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
