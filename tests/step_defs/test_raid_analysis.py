"""Step definitions for raid analysis feature."""

from unittest.mock import MagicMock

from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.analysis import (
    _classify_hybrid_role,
    _identify_composition,
    _identify_healers,
    _identify_tanks,
    analyze_raid,
)
from warcraftlogs_client.models import RaidMetadata

scenarios("raid_analysis.feature")


@given(
    parsers.parse('a master actor "{name}" of class "{cls}" with id {sid:d}'),
    target_fixture="actor_setup",
)
def actor_setup(name, cls, sid):
    client = MagicMock()
    client.get_damage_taken_data.return_value = []
    client.get_healing_data.return_value = []
    client.get_damage_done_data.return_value = []
    actor = {"name": name, "id": sid, "type": "Player", "subType": cls}
    return {"client": client, "actors": [actor], "name": name, "class": cls, "id": sid}


@given(parsers.parse('"{name}" took {taken:d} damage and mitigated {mitigated:d}'))
def set_damage_taken(actor_setup, name, taken, mitigated):
    events = [{"type": "damage", "amount": taken, "mitigated": mitigated}]
    actor_setup["client"].get_damage_taken_data.return_value = events


@given(parsers.parse('"{name}" did {total:d} total healing'))
def set_healing(actor_setup, name, total):
    events = [{"type": "heal", "amount": total}]
    actor_setup["client"].get_healing_data.return_value = events


@given(parsers.parse('"{name}" deals {melee:d} melee damage and {spell:d} spell damage'))
def set_damage_profile(actor_setup, name, melee, spell):
    events = [
        {"type": "damage", "amount": melee, "abilityGameID": 1},
        {"type": "damage", "amount": spell, "abilityGameID": 9999},
    ]
    actor_setup["client"].get_damage_done_data.return_value = events


@given(
    parsers.parse('a mock client with report data for "{report_id}"'),
    target_fixture="actor_setup",
)
def mock_full_client(report_id):
    client = MagicMock()
    metadata = RaidMetadata(
        report_id=report_id,
        title="Test Raid",
        owner="Owner",
        start_time=1_700_000_000_000,
        end_time=1_700_003_600_000,
    )
    client.get_report_metadata.return_value = metadata
    client.get_master_data.return_value = []
    client.get_healing_data.return_value = []
    client.get_damage_taken_data.return_value = []
    client.get_damage_done_data.return_value = []
    client.get_cast_events_paginated.return_value = []
    client.get_buffs_table.return_value = {"data": {"auras": []}}
    client.get_fights.return_value = []
    return {"client": client, "report_id": report_id}


@when(
    parsers.parse("tanks are identified with min_taken {min_taken:d} and min_mitigation {min_mit:d}"),
    target_fixture="result",
)
def identify_tanks_step(actor_setup, min_taken, min_mit):
    tanks = _identify_tanks(
        actor_setup["client"],
        "test_report",
        actor_setup["actors"],
        min_taken,
        min_mit,
    )
    return {"tanks": tanks}


@when(
    parsers.parse("healers are identified with threshold {threshold:d}"),
    target_fixture="result",
)
def identify_healers_step(actor_setup, threshold):
    healers = _identify_healers(
        actor_setup["client"],
        "test_report",
        actor_setup["actors"],
        threshold,
    )
    return {"healers": healers}


@when("the composition is identified", target_fixture="result")
def identify_composition_step(actor_setup):
    actor_setup["client"].get_healing_data.return_value = []
    actor_setup["client"].get_damage_taken_data.return_value = []
    composition = _identify_composition(
        actor_setup["client"],
        "test_report",
        actor_setup["actors"],
        healer_threshold=999_999_999,
        tank_min_taken=999_999_999,
        tank_min_mitigation=999,
    )
    return {"composition": composition}


@when("the hybrid role is classified", target_fixture="result")
def classify_hybrid_step(actor_setup):
    role = _classify_hybrid_role(
        actor_setup["client"],
        "test_report",
        actor_setup["id"],
        actor_setup["class"],
    )
    return {"role": role}


@when(
    parsers.parse('the full raid analysis is run for "{report_id}"'),
    target_fixture="result",
)
def run_full_analysis(actor_setup, report_id):
    analysis = analyze_raid(actor_setup["client"], report_id)
    return {"analysis": analysis}


@then(parsers.parse('"{name}" should be identified as a tank'))
def check_tank_found(result, name):
    assert any(t.name == name for t in result["tanks"])


@then("no tanks should be identified")
def check_no_tanks(result):
    assert len(result["tanks"]) == 0


@then(parsers.parse('"{name}" should be identified as a healer'))
def check_healer_found(result, name):
    assert any(h.name == name for h in result["healers"])


@then("no healers should be identified")
def check_no_healers(result):
    assert len(result["healers"]) == 0


@then(parsers.parse('"{name}" should be classified as "{role}"'))
def check_classification(result, name, role):
    comp = result["composition"]
    if role == "melee":
        assert any(p.name == name for p in comp.melee)
    elif role == "ranged":
        assert any(p.name == name for p in comp.ranged)


@then(parsers.parse('the role should be "{role}"'))
def check_role(result, role):
    assert result["role"] == role


@then(parsers.parse('the result should contain metadata with report id "{report_id}"'))
def check_metadata(result, report_id):
    assert result["analysis"].metadata.report_id == report_id


@then("the result should have a composition")
def check_has_composition(result):
    assert result["analysis"].composition is not None
