"""Step definitions for consumables analysis feature."""

from pytest_bdd import given, parsers, scenarios, then

from warcraftlogs_client.models import (
    ConsumableUsage,
    HealerPerformance,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    TankPerformance,
)

scenarios("consumables.feature")


def _base_analysis():
    metadata = RaidMetadata(
        report_id="r1",
        title="Test Raid",
        owner="Owner",
        start_time=1_700_000_000_000,
        end_time=1_700_003_600_000,
    )
    composition = RaidComposition(
        tanks=[PlayerIdentity(name="Tank", player_class="Warrior", source_id=2, role="tank")],
        healers=[PlayerIdentity(name="Healer", player_class="Priest", source_id=1, role="healer")],
        melee=[],
        ranged=[],
    )
    return RaidAnalysis(
        metadata=metadata,
        composition=composition,
        healers=[
            HealerPerformance(
                name="Healer",
                player_class="Priest",
                source_id=1,
                total_healing=100_000,
                total_overhealing=10_000,
                spells=[],
                dispels=[],
                resources=[],
                fear_ward_casts=0,
            )
        ],
        tanks=[
            TankPerformance(
                name="Tank",
                player_class="Warrior",
                source_id=2,
                total_damage_taken=200_000,
                total_mitigated=100_000,
                damage_taken_breakdown=[],
                abilities_used=[],
            )
        ],
        dps=[],
        consumables=[],
    )


@given("a raid analysis with consumable usage", target_fixture="consume_ctx")
def analysis_with_consumables():
    a = _base_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name="Player1",
            player_role="dps",
            report_id="r1",
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
def analysis_with_named_consumable(player, item):
    a = _base_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name=player,
            player_role="healer",
            report_id="r1",
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
def analysis_with_counted_consumable(player, count, item):
    a = _base_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name=player,
            player_role="healer",
            report_id="r1",
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
def analysis_with_timestamps(player, t1, t2):
    a = _base_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name=player,
            player_role="healer",
            report_id="r1",
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
def analysis_with_two_players(p1, p2):
    a = _base_analysis()
    a.consumables = [
        ConsumableUsage(
            player_name=p1,
            player_role="dps",
            report_id="r1",
            consumable_name="Haste Potion",
            count=1,
            timestamps=[60_000],
        ),
        ConsumableUsage(
            player_name=p2,
            player_role="healer",
            report_id="r1",
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
