"""Step definitions for database persistence feature."""

from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.database import PerformanceDB
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

scenarios("database.feature")


def _make_analysis(report_id, healer_name="HolyPriest", tank_name="TankWarrior", dps_name="StabbyRogue"):
    metadata = RaidMetadata(
        report_id=report_id,
        title="Test Raid",
        owner="Owner",
        start_time=1_700_000_000_000,
        end_time=1_700_003_600_000,
    )
    composition = RaidComposition(
        tanks=[PlayerIdentity(name=tank_name, player_class="Warrior", source_id=2, role="tank")],
        healers=[PlayerIdentity(name=healer_name, player_class="Priest", source_id=1, role="healer")],
        melee=[PlayerIdentity(name=dps_name, player_class="Rogue", source_id=3, role="melee")],
        ranged=[],
    )
    return RaidAnalysis(
        metadata=metadata,
        composition=composition,
        healers=[
            HealerPerformance(
                name=healer_name,
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
                name=tank_name,
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
                name=dps_name,
                player_class="Rogue",
                source_id=3,
                role="melee",
                total_damage=400_000,
                abilities=[],
            )
        ],
        consumables=[],
    )


@given("a fresh test database", target_fixture="db_ctx")
def fresh_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = PerformanceDB(db_path)
    database.initialize()
    return {"db": database}


@given(
    parsers.parse('a raid analysis for report "{report_id}"'),
    target_fixture="analysis_ctx",
)
def analysis_for_report(report_id):
    return {"analysis": _make_analysis(report_id), "report_id": report_id}


@given(
    parsers.parse('a raid analysis with healer "{name}" of class "{cls}"'),
    target_fixture="analysis_ctx",
)
def analysis_with_healer(name, cls):
    return {"analysis": _make_analysis("test_report", healer_name=name), "report_id": "test_report"}


@given(
    parsers.parse('a raid analysis with tank "{name}" of class "{cls}"'),
    target_fixture="analysis_ctx",
)
def analysis_with_tank(name, cls):
    return {"analysis": _make_analysis("test_report", tank_name=name), "report_id": "test_report"}


@given(
    parsers.parse('a raid analysis with DPS "{name}" of class "{cls}"'),
    target_fixture="analysis_ctx",
)
def analysis_with_dps(name, cls):
    return {"analysis": _make_analysis("test_report", dps_name=name), "report_id": "test_report"}


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
