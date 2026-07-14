"""Step definitions for encounter analysis feature."""

from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.analysis import _analyze_encounters
from warcraftlogs_client.models import (
    EncounterPerformance,
    EncounterSummary,
    PlayerIdentity,
    RaidComposition,
)

scenarios("encounter_analysis.feature")


def _default_composition():
    return RaidComposition(
        tanks=[PlayerIdentity(name="TankWarrior", player_class="Warrior", source_id=2, role="tank")],
        healers=[PlayerIdentity(name="HolyPriest", player_class="Priest", source_id=1, role="healer")],
        melee=[PlayerIdentity(name="StabbyRogue", player_class="Rogue", source_id=3, role="melee")],
        ranged=[],
    )


@given(parsers.parse('the client returns fights with {count:d} boss kill named "{name}"'))
def setup_boss_kill(wcl_client, count, name):
    fights = [
        {"id": i + 1, "name": name, "startTime": i * 60000, "endTime": (i + 1) * 60000, "kill": True, "encounterID": 658 + i}
        for i in range(count)
    ]
    wcl_client.get_fights.return_value = fights
    wcl_client.get_encounter_table.return_value = []


@given(parsers.parse("the client returns fights with {bosses:d} boss kill and {trash:d} trash fights"))
def setup_boss_and_trash(wcl_client, bosses, trash):
    fights = []
    for i in range(bosses):
        fights.append({"id": i + 1, "name": f"Boss{i+1}", "startTime": i * 60000, "endTime": (i + 1) * 60000, "kill": True, "encounterID": 100 + i})
    for i in range(trash):
        fights.append({"id": bosses + i + 1, "name": "Trash", "startTime": (bosses + i) * 60000, "endTime": (bosses + i + 1) * 60000, "kill": True, "encounterID": 0})
    wcl_client.get_fights.return_value = fights
    wcl_client.get_encounter_table.return_value = []


@given(parsers.parse("the client returns fights with {bosses:d} boss kill and {wipes:d} wipe"))
def setup_boss_and_wipe(wcl_client, bosses, wipes):
    fights = []
    for i in range(bosses):
        fights.append({"id": i + 1, "name": f"Boss{i+1}", "startTime": i * 60000, "endTime": (i + 1) * 60000, "kill": True, "encounterID": 100 + i})
    for i in range(wipes):
        fights.append({"id": bosses + i + 1, "name": "WipeBoss", "startTime": (bosses + i) * 60000, "endTime": (bosses + i + 1) * 60000, "kill": False, "encounterID": 200 + i})
    wcl_client.get_fights.return_value = fights
    wcl_client.get_encounter_table.return_value = []


@given(
    parsers.parse('the client returns a boss fight with "{dps}" dealing {dmg:d} damage and "{healer}" doing {heal:d} healing')
)
def setup_boss_with_data(wcl_client, dps, dmg, healer, heal):
    wcl_client.get_fights.return_value = [
        {"id": 1, "name": "Boss", "startTime": 0, "endTime": 60000, "kill": True, "encounterID": 100},
    ]

    def fake_table(report_id, start, end, data_type):
        if data_type == "DamageDone":
            return [{"name": dps, "type": "Player", "total": dmg}]
        elif data_type == "Healing":
            return [{"name": healer, "type": "Player", "total": heal}]
        return []

    wcl_client.get_encounter_table.side_effect = fake_table


@given("the client returns a boss fight with a player and a pet")
def setup_boss_with_pet(wcl_client):
    wcl_client.get_fights.return_value = [
        {"id": 1, "name": "Boss", "startTime": 0, "endTime": 60000, "kill": True, "encounterID": 100},
    ]
    wcl_client.get_encounter_table.side_effect = lambda *args: (
        [
            {"name": "StabbyRogue", "type": "Player", "total": 100000},
            {"name": "Wolf", "type": "Pet", "total": 20000},
        ]
        if args[3] == "DamageDone"
        else []
    )


@given("the client returns 2 boss fights where the first errors")
def setup_boss_with_error(wcl_client):
    wcl_client.get_fights.return_value = [
        {"id": 1, "name": "Boss1", "startTime": 0, "endTime": 30000, "kill": True, "encounterID": 100},
        {"id": 2, "name": "Boss2", "startTime": 40000, "endTime": 80000, "kill": True, "encounterID": 200},
    ]
    call_count = [0]

    def fail_first(*args):
        call_count[0] += 1
        if call_count[0] <= 1:
            raise KeyError("API error")
        return [{"name": "StabbyRogue", "type": "Player", "total": 50000}]

    wcl_client.get_encounter_table.side_effect = fail_first


@given(
    parsers.parse('a raid analysis with an encounter named "{name}"'),
    target_fixture="enc_analysis_ctx",
)
def analysis_with_encounter(build_analysis, name):
    encounter = EncounterSummary(
        encounter_id=658,
        name=name,
        start_time=12000,
        end_time=180000,
        duration_ms=168000,
        players=[
            EncounterPerformance(
                name="StabbyRogue", player_class="Rogue", source_id=3, role="melee",
                total_damage=150_000, total_healing=0, total_damage_taken=20_000,
            ),
        ],
    )
    analysis = build_analysis(encounters=[encounter])
    return {"analysis": analysis}


@given("the encounter analysis has been imported")
def pre_import_encounters(db_ctx, enc_analysis_ctx):
    db_ctx["db"].import_raid(enc_analysis_ctx["analysis"])


@when(
    parsers.parse('encounters are analyzed for report "{report_id}"'),
    target_fixture="encounter_result",
)
def analyze_encounters(wcl_client, report_id):
    comp = _default_composition()
    result = _analyze_encounters(wcl_client, report_id, comp)
    return {"encounters": result}


@when("the encounter analysis is imported to the database")
def import_encounters(db_ctx, enc_analysis_ctx):
    db_ctx["db"].import_raid(enc_analysis_ctx["analysis"])


@when(parsers.parse('the raid "{report_id}" is deleted from the database'))
def delete_raid_enc(db_ctx, report_id):
    db_ctx["db"].delete_raid(report_id)


@then(parsers.parse("there should be {count:d} encounter summary"))
def check_encounter_count(encounter_result, count):
    assert len(encounter_result["encounters"]) == count


@then(parsers.parse('the encounter should be named "{name}"'))
def check_encounter_name(encounter_result, name):
    assert encounter_result["encounters"][0].name == name


@then(parsers.parse('player "{name}" should have {dmg:d} total damage'))
def check_player_damage(encounter_result, name, dmg):
    enc = encounter_result["encounters"][0]
    by_name = {p.name: p for p in enc.players}
    assert by_name[name].total_damage == dmg


@then(parsers.parse('player "{name}" should have {heal:d} total healing'))
def check_player_healing(encounter_result, name, heal):
    enc = encounter_result["encounters"][0]
    by_name = {p.name: p for p in enc.players}
    assert by_name[name].total_healing == heal


@then(parsers.parse("there should be {count:d} player in the encounter"))
def check_player_count(encounter_result, count):
    assert len(encounter_result["encounters"][0].players) == count


@then(parsers.parse('the database should contain encounter "{name}"'))
def check_db_encounter(db_ctx, name):
    loaded = db_ctx["db"].get_raid_analysis("test_report")
    assert loaded is not None
    assert any(e.name == name for e in loaded.encounters)


@then("the database should have no encounter records")
def check_no_encounters(db_ctx):
    conn = db_ctx["db"]._get_conn()
    assert conn.execute("SELECT COUNT(*) FROM encounters").fetchone()[0] == 0
