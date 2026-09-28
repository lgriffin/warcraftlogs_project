"""Toads badges: tiers and thresholds, config overrides, and the service over both storage backends.

The service reads only ``RaidRepository`` methods, so its tests run on SQLite and on Postgres; the Postgres half is
skipped without ``WCL_STORE_TEST_DATABASE_URL``, as in ``test_store_contract.py``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest
from wcl_app import AppContext, BadgeRules, BadgeService
from wcl_app.badges import CONSUMABLES, DEFAULT_RULES, RAIDS, BadgeRule, PlayerStats, character_stats, guild_stats
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client.models import ConsumableUsage

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
DAY = 86_400_000
T0 = 1_700_000_000_000

MANA = BadgeRule(
    "mana",
    "Mana Guzzler",
    "Mana potions",
    "mana_potion",
    "🧪",
    "potions",
    (10, 50),
    items=frozenset({"super mana potion"}),
)


def _stats(raids: int = 0, **consumables: int) -> PlayerStats:
    return PlayerStats("Holy", "Priest", raids, {k.replace("_", " "): v for k, v in consumables.items()})


# ── Rules ──


class TestAward:
    def test_below_the_first_tier_is_not_earned(self):
        badge = MANA.award(_stats(Super_Mana_Potion=7))
        assert (badge.tier, badge.quality, badge.tier_name, badge.earned) == (0, "", "", False)
        assert (badge.next_at, badge.next_tier, badge.progress, badge.stacks) == (10, "Uncommon", 0.7, 0)

    def test_tiers_are_named_after_item_quality(self):
        badge = MANA.award(_stats(Super_Mana_Potion=12))
        assert (badge.tier, badge.quality, badge.tier_name) == (1, "uncommon", "Uncommon")
        assert (badge.next_at, badge.next_tier, badge.progress) == (50, "Rare", 0.05)

    def test_top_tier_is_complete_and_stacks_count_the_first_tier(self):
        badge = MANA.award(_stats(Super_Mana_Potion=200))
        assert (badge.tier, badge.quality, badge.next_at, badge.next_tier, badge.progress) == (2, "rare", None, "", 1.0)
        assert badge.stacks == 20  # 200 potions against a first tier of 10
        assert badge.display == "200 potions"

    def test_consumable_names_match_any_case_and_other_items_are_ignored(self):
        stats = PlayerStats("Holy", consumables={"SUPER MANA POTION": 4, "Super Mana Potion": 6, "Haste Potion": 9})
        assert MANA.award(stats).value == 10

    def test_one_is_singular(self):
        assert MANA.award(_stats(Super_Mana_Potion=1)).display == "1 potion"

    def test_attendance_counts_raids_and_an_empty_family_counts_everything(self):
        raids = BadgeRule("raids", "Loyal", "Raids", "attendance", "🐸", "raids", (5,), RAIDS)
        every = BadgeRule("all", "Stocked", "Consumables", "consumables", "🎒", "consumables", (5,), CONSUMABLES)
        stats = _stats(6, Haste_Potion=2, Dark_Rune=3)
        assert (raids.award(stats).tier, every.award(stats).value) == (1, 5)

    def test_player_badges_rank_by_tiers_and_list_the_earned(self):
        player = BadgeRules((MANA, replace(MANA, id="mana2", thresholds=(1, 2, 3)))).award(_stats(Super_Mana_Potion=12))
        assert [b.id for b in player.earned] == ["mana", "mana2"]
        assert player.score == 1 + 3
        data = json.loads(json.dumps(player.to_dict()))
        assert data["score"] == 4 and data["badges"][0]["quality"] == "uncommon"

    def test_default_rules_are_unique_ascending_and_at_most_four_tiers(self):
        ids = [r.id for r in DEFAULT_RULES]
        assert len(ids) == len(set(ids))
        for rule in DEFAULT_RULES:
            assert 1 <= len(rule.thresholds) <= 4
            assert list(rule.thresholds) == sorted(set(rule.thresholds))

    def test_catalogue_json(self):
        data = json.loads(json.dumps(BadgeRules().to_dict()))
        assert data["version"] == 1
        attendance = data["badges"][0]
        assert attendance["id"] == "attendance"
        assert attendance["tiers"][0] == {"tier": 1, "quality": "uncommon", "name": "Uncommon", "at": 5}
        assert attendance["tiers"][-1]["quality"] == "legendary"


class TestConfig:
    def test_no_section_means_the_defaults(self):
        assert BadgeRules.from_config({}) == BadgeRules()
        assert BadgeRules.from_config({"badges": "nope"}) == BadgeRules()

    def test_thresholds_and_disabled_badges_apply(self):
        rules = BadgeRules.from_config(
            {"badges": {"thresholds": {"attendance": [1, 2], "drums": [3]}, "disabled": ["explosives", 7]}}
        )
        by_id = {r.id: r for r in rules.rules}
        assert by_id["attendance"].thresholds == (1, 2)
        assert by_id["drums"].thresholds == (3,)
        assert "explosives" not in by_id
        assert len(rules.rules) == len(DEFAULT_RULES) - 1

    @pytest.mark.parametrize(
        "bad", [[], [5, 5], [10, 5], [0, 5], [1, 2, 3, 4, 5], [True], ["5"], "5", 5, {"a": 1}, None]
    )
    def test_malformed_thresholds_keep_the_default(self, bad, caplog):
        rules = BadgeRules.from_config({"badges": {"thresholds": {"attendance": bad}, "disabled": "attendance"}})
        assert rules.rules[0] == DEFAULT_RULES[0]
        assert "Ignoring badge thresholds for attendance" in caplog.text

    def test_malformed_sections_are_ignored(self):
        assert BadgeRules.from_config({"badges": {"thresholds": ["x"], "disabled": None}}) == BadgeRules()


# ── Service ──


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    if request.param == "sqlite":
        path = str(tmp_path / f"badges-{uuid.uuid4().hex[:8]}.db")
        return lambda: PerformanceDB(path)
    engine = request.getfixturevalue("pg_empty_engine")
    from wcl_store.postgres import PostgresRaidRepository

    return lambda: PostgresRaidRepository(engine)


@pytest.fixture
def raids(storage, build_analysis):
    """Six guild raids and one reference raid. HolyPriest drinks 4 mana potions a raid, StabbyRogue drums in two."""
    with storage() as repo:
        for n in range(6):
            code = f"GuildRaid{n:07d}"
            consumables = [ConsumableUsage("HolyPriest", "healer", code, "Super Mana Potion", 4)]
            if n < 2:
                consumables.append(ConsumableUsage("StabbyRogue", "melee", code, "Drums of Battle", 6))
            repo.import_raid(build_analysis(report_id=code, start_time=T0 + n * DAY, consumables=consumables))
        ref = "ReferenceRaid000"
        repo.import_raid(
            build_analysis(
                report_id=ref,
                start_time=T0 + 9 * DAY,
                consumables=[ConsumableUsage("HolyPriest", "healer", ref, "Super Mana Potion", 50)],
            ),
            source="reference",
        )


def _by_id(player):
    return {b.id: b for b in player.badges}


@pytest.mark.usefixtures("raids")
class TestService:
    def test_character_badges(self, storage):
        holy = _by_id(BadgeService(storage).for_character("holypriest"))
        assert (holy["attendance"].value, holy["attendance"].tier) == (6, 1)
        assert (holy["mana_potions"].value, holy["mana_potions"].tier) == (24, 1)  # the reference raid is left out
        assert holy["well_stocked"].value == 24
        assert not holy["drums"].earned

    def test_guild_badges_rank_by_tiers_then_name(self, storage):
        players = BadgeService(storage).for_guild()
        assert [p.name for p in players] == ["HolyPriest", "StabbyRogue", "TankWarrior"]
        stab = _by_id(players[1])
        assert (stab.get("drums").value, stab["drums"].tier, stab["attendance"].tier) == (12, 1, 1)
        assert players[0].player_class == "Priest"

    def test_guild_badges_for_some_names(self, storage):
        assert [p.name for p in BadgeService(storage).for_guild(["STABBYROGUE"])] == ["StabbyRogue"]

    def test_character_and_guild_counts_agree(self, storage):
        with storage() as repo:
            one = character_stats(repo, "HolyPriest")
            everyone = guild_stats(repo)
        assert (one.raids, one.consumables) == (everyone["holypriest"].raids, everyone["holypriest"].consumables)

    def test_other_sources_can_be_counted(self, storage):
        holy = _by_id(BadgeService(storage, sources=("guild", "reference")).for_character("HolyPriest"))
        assert (holy["mana_potions"].value, holy["attendance"].value) == (74, 7)

    def test_unknown_character_has_no_badges(self, storage):
        nobody = BadgeService(storage).for_character("Nobody")
        assert nobody.earned == [] and nobody.score == 0


def test_from_context_reads_thresholds_from_config(tmp_path, build_analysis):
    ctx = AppContext(config={"badges": {"thresholds": {"attendance": [1]}}}, db_path=str(tmp_path / "ctx.db"))
    with ctx.repository() as repo:
        repo.import_raid(build_analysis(report_id="OneRaidOneRaidOn"))
    service = BadgeService.from_context(ctx)
    assert service.catalogue()[0].thresholds == (1,)
    assert _by_id(service.for_character("TankWarrior"))["attendance"].tier_name == "Uncommon"
