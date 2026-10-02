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


# ── Flask Bearer ──

FLASKED_RULE = next(r for r in DEFAULT_RULES if r.id == "flasked")


class TestFlaskBearer:
    def test_counts_raids_prepared_with_the_attendance_thresholds(self):
        badge = FLASKED_RULE.award(PlayerStats("Holy", raids=20, flasked_raids=16))
        assert (badge.id, badge.name, badge.icon, badge.glyph, FLASKED_RULE.unit) == (
            "flasked",
            "Flask Bearer",
            "flask",
            "⚗️",
            "raids",
        )
        assert (badge.value, badge.tier, badge.tier_name, badge.display) == (16, 2, "Rare", "16 raids")
        assert FLASKED_RULE.thresholds == (5, 15, 40, 100)

    def test_consumable_counts_do_not_count_towards_it(self):
        stats = PlayerStats("Holy", raids=9, consumables={"Flask of Blinding Light": 9})
        assert FLASKED_RULE.award(stats).value == 0  # only flasked_raids counts

    def test_well_stocked_leaves_flasks_and_elixirs_out(self):
        well_stocked = next(r for r in DEFAULT_RULES if r.id == "well_stocked")
        stats = PlayerStats(
            "Holy", consumables={"Flask of Blinding Light": 9, "ELIXIR OF HEALING POWER": 4, "Super Mana Potion": 3}
        )
        assert well_stocked.award(stats).value == 3

    def test_it_can_be_disabled_like_any_badge(self):
        rules = BadgeRules.from_config({"badges": {"disabled": ["flasked"], "thresholds": {}}})
        assert "flasked" not in {r.id for r in rules.rules}


@pytest.fixture
def flask_raids(storage, build_analysis):
    """Six guild raids. HolyPriest: an elixir pair in four, one elixir alone in the fifth, a flask in the sixth.
    StabbyRogue: a flask in two. A reference raid where HolyPriest flasks does not count."""

    def usage(name, role, code, *items):
        return [ConsumableUsage(name, role, code, item, 1, [0]) for item in items]

    with storage() as repo:
        for n in range(6):
            code = f"FlaskRaid{n:07d}"
            if n < 4:
                holy = usage("HolyPriest", "healer", code, "Elixir of Healing Power", "Elixir of Major Mageblood")
            elif n == 4:
                holy = usage("HolyPriest", "healer", code, "Elixir of Healing Power")
            else:
                holy = usage("HolyPriest", "healer", code, "Flask of Mighty Restoration", "Super Mana Potion")
            stab = usage("StabbyRogue", "melee", code, "Flask of Relentless Assault") if n < 2 else []
            repo.import_raid(build_analysis(report_id=code, start_time=T0 + n * DAY, consumables=holy + stab))
        ref = "FlaskReference00"
        repo.import_raid(
            build_analysis(
                report_id=ref,
                start_time=T0 + 9 * DAY,
                consumables=usage("HolyPriest", "healer", ref, "Flask of Mighty Restoration"),
            ),
            source="reference",
        )


@pytest.mark.usefixtures("flask_raids")
class TestFlaskBearerService:
    def test_a_flask_or_an_elixir_pair_counts_a_raid_once(self, storage):
        with storage() as repo:
            holy = character_stats(repo, "HolyPriest")
            everyone = guild_stats(repo)
        assert holy.flasked_raids == 5  # four pairs and a flask; the lone elixir does not count
        assert everyone["holypriest"].flasked_raids == 5
        assert everyone["stabbyrogue"].flasked_raids == 2
        assert everyone["tankwarrior"].flasked_raids == 0

    def test_badge_for_character_and_guild(self, storage):
        holy = _by_id(BadgeService(storage).for_character("HolyPriest"))["flasked"]
        assert (holy.value, holy.tier, holy.quality) == (5, 1, "uncommon")
        guild = {p.name: _by_id(p)["flasked"].value for p in BadgeService(storage).for_guild()}
        assert guild["HolyPriest"] == 5 and guild["StabbyRogue"] == 2

    def test_other_sources_can_be_counted(self, storage):
        holy = _by_id(BadgeService(storage, sources=("guild", "reference")).for_character("HolyPriest"))
        assert holy["flasked"].value == 6


def test_flask_names_stored_in_any_case_count_for_character_and_guild(storage, build_analysis):
    """Stored names are matched ignoring case, the way ``preparation`` classifies them."""
    with storage() as repo:
        for n, items in enumerate(
            (["FLASK OF MIGHTY RESTORATION"], ["elixir of healing power", "Elixir Of Major Mageblood"])
        ):
            code = f"CaseRaid{n:08d}"
            consumables = [ConsumableUsage("HolyPriest", "healer", code, item, 1) for item in items]
            repo.import_raid(build_analysis(report_id=code, start_time=T0 + n * DAY, consumables=consumables))
        assert character_stats(repo, "HolyPriest").flasked_raids == 2
        assert guild_stats(repo)["holypriest"].flasked_raids == 2
