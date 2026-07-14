"""Step definitions for database persistence feature."""

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("database.feature")


@given(
    parsers.parse('a raid analysis with healer "{name}" of class "{cls}"'),
    target_fixture="analysis_ctx",
)
def analysis_with_healer(build_analysis, name, cls):
    return {"analysis": build_analysis(healer_name=name, healer_class=cls), "report_id": "test_report"}


@given(
    parsers.parse('a raid analysis with tank "{name}" of class "{cls}"'),
    target_fixture="analysis_ctx",
)
def analysis_with_tank(build_analysis, name, cls):
    return {"analysis": build_analysis(tank_name=name, tank_class=cls), "report_id": "test_report"}


@given(
    parsers.parse('a raid analysis with DPS "{name}" of class "{cls}"'),
    target_fixture="analysis_ctx",
)
def analysis_with_dps(build_analysis, name, cls):
    return {"analysis": build_analysis(dps_name=name, dps_class=cls), "report_id": "test_report"}


@given("the analysis has been imported")
def pre_import(db_ctx, analysis_ctx):
    db_ctx["db"].import_raid(analysis_ctx["analysis"])


@when("the analysis is imported to the database")
def import_analysis(db_ctx, analysis_ctx):
    db_ctx["db"].import_raid(analysis_ctx["analysis"])


@when("the analysis is imported twice")
def import_twice(db_ctx, analysis_ctx):
    db_ctx["db"].import_raid(analysis_ctx["analysis"])
    db_ctx["db"].import_raid(analysis_ctx["analysis"])


@when(parsers.parse('the raid "{report_id}" is deleted'))
def delete_raid(db_ctx, report_id):
    db_ctx["db"].delete_raid(report_id)


@when(
    parsers.parse('character history is queried for "{name}"'),
    target_fixture="history_result",
)
def query_history(db_ctx, name):
    return {"history": db_ctx["db"].get_character_history(name)}


@then(parsers.parse('the raid "{report_id}" should be marked as imported'))
def check_imported(db_ctx, report_id):
    raids = db_ctx["db"].get_raid_list()
    assert any(r["report_id"] == report_id for r in raids)


@then(parsers.parse('the raid "{report_id}" should not be marked as imported'))
def check_not_imported(db_ctx, report_id):
    raids = db_ctx["db"].get_raid_list()
    assert not any(r["report_id"] == report_id for r in raids)


@then(parsers.parse('there should be exactly {count:d} raid record for "{report_id}"'))
def check_raid_count(db_ctx, count, report_id):
    raids = db_ctx["db"].get_raid_list()
    matching = [r for r in raids if r["report_id"] == report_id]
    assert len(matching) == count


@then(parsers.parse('character "{name}" should have healing data'))
def check_healer_data(db_ctx, name):
    history = db_ctx["db"].get_character_history(name)
    assert history is not None
    assert history.avg_healing > 0


@then(parsers.parse('character "{name}" should have mitigation data'))
def check_tank_data(db_ctx, name):
    history = db_ctx["db"].get_character_history(name)
    assert history is not None
    assert history.avg_mitigation_percent is not None


@then(parsers.parse('character "{name}" should have damage data'))
def check_dps_data(db_ctx, name):
    history = db_ctx["db"].get_character_history(name)
    assert history is not None
    assert history.avg_damage > 0


@then("the character history should be empty")
def check_no_history(history_result):
    assert history_result["history"] is None
