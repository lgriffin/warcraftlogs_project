"""Step definitions for consumables analysis feature."""

from pytest_bdd import given, parsers, scenarios, then

from warcraftlogs_client.models import ConsumableUsage

scenarios("consumables.feature")


@given("a raid analysis with consumable usage", target_fixture="consume_ctx")
def analysis_with_consumables(build_analysis):
    a = build_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name="Player1",
            player_role="dps",
            report_id="test_report",
            consumable_name="Haste Potion",
            count=2,
            timestamps=[60_000, 180_000],
        )
    ]
    return {"analysis": a}


@given(
    parsers.parse('a raid analysis where "{player}" used "{item}"'),
    target_fixture="consume_ctx",
)
def analysis_with_named_consumable(build_analysis, player, item):
    a = build_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name=player,
            player_role="healer",
            report_id="test_report",
            consumable_name=item,
            count=1,
            timestamps=[60_000],
        )
    ]
    return {"analysis": a}


@given(
    parsers.parse('a raid analysis where "{player}" used {count:d} "{item}"'),
    target_fixture="consume_ctx",
)
def analysis_with_counted_consumable(build_analysis, player, count, item):
    a = build_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name=player,
            player_role="healer",
            report_id="test_report",
            consumable_name=item,
            count=count,
            timestamps=[i * 60_000 for i in range(1, count + 1)],
        )
    ]
    return {"analysis": a}


@given(
    parsers.parse('a raid analysis where "{player}" used potions at timestamps {t1:d} and {t2:d}'),
    target_fixture="consume_ctx",
)
def analysis_with_timestamps(build_analysis, player, t1, t2):
    a = build_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name=player,
            player_role="healer",
            report_id="test_report",
            consumable_name="Super Mana Potion",
            count=2,
            timestamps=[t1, t2],
        )
    ]
    return {"analysis": a}


@given(
    parsers.parse('a raid analysis with consumables for "{p1}" and "{p2}"'),
    target_fixture="consume_ctx",
)
def analysis_with_two_players(build_analysis, p1, p2):
    a = build_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name=p1,
            player_role="dps",
            report_id="test_report",
            consumable_name="Haste Potion",
            count=1,
            timestamps=[60_000],
        ),
        ConsumableUsage(
            player_name=p2,
            player_role="healer",
            report_id="test_report",
            consumable_name="Super Mana Potion",
            count=1,
            timestamps=[120_000],
        ),
    ]
    return {"analysis": a}


@then("the consumables list should not be empty")
def check_not_empty(consume_ctx):
    assert len(consume_ctx["analysis"].consumables) > 0


@then(parsers.parse('the consumable record should have player "{player}"'))
def check_player(consume_ctx, player):
    assert consume_ctx["analysis"].consumables[0].player_name == player


@then(parsers.parse('the consumable record should have name "{name}"'))
def check_name(consume_ctx, name):
    assert consume_ctx["analysis"].consumables[0].consumable_name == name


@then(parsers.parse("the consumable count should be {count:d}"))
def check_count(consume_ctx, count):
    assert consume_ctx["analysis"].consumables[0].count == count


@then(parsers.parse("the consumable should have {count:d} timestamps"))
def check_timestamps(consume_ctx, count):
    assert len(consume_ctx["analysis"].consumables[0].timestamps) == count


@then(parsers.parse("there should be {count:d} consumable records"))
def check_record_count(consume_ctx, count):
    assert len(consume_ctx["analysis"].consumables) == count
