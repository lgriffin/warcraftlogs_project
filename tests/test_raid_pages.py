"""The raid pages service (wcl_app.raid_pages): the desktop app's raid browser and raid analysis as JSON payloads,
built from storage alone, on both storage backends."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime

import pytest
from wcl_app import AppContext, RaidPage, RaidPageService, RaidSummary
from wcl_app.raid_pages import (
    RAID_PAGE_VERSION,
    EncounterPlayer,
    boss_history,
    build_page,
    classify_consumable_usage,
    compute_engineering_stats,
    summary_of,
    weekday_of,
)
from wcl_store import RaidScope, StorageError
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client.models import (
    AuraUptime,
    CancelledCastDetail,
    CancelledCastSummary,
    ConsumableUsage,
    DPSPerformance,
    EncounterPerformance,
    EncounterSummary,
    InterruptUsage,
    PlayerIdentity,
    SpellUsage,
)

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
WED = "WednesdayRaidAAA"
SUN = "SundayRaidBBBBBB"


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    if request.param == "sqlite":
        path = str(tmp_path / f"pages-{uuid.uuid4().hex[:8]}.db")
        return lambda: PerformanceDB(path)
    engine = request.getfixturevalue("pg_empty_engine")
    from wcl_store.postgres import PostgresRaidRepository

    return lambda: PostgresRaidRepository(engine)


def _raid(build_analysis, report_id: str, start: datetime, boss_damage: int):
    s = _ms(start)
    analysis = build_analysis(
        report_id=report_id,
        title="Serpentshrine Cavern",
        start_time=s,
        end_time=s + 7_200_000,
        consumables=[
            ConsumableUsage("StabbyRogue", "melee", report_id, "Haste Potion", 2, [s + 100_000, s + 1_000_000]),
            ConsumableUsage("HolyPriest", "healer", report_id, "Super Mana Potion", 1, [s + 120_000]),
        ],
        encounters=[
            EncounterSummary(
                623,
                "Hydross the Unstable",
                s + 90_000,
                s + 390_000,
                300_000,
                players=[
                    EncounterPerformance("StabbyRogue", "Rogue", 3, "melee", total_damage=boss_damage),
                    EncounterPerformance("HolyPriest", "Priest", 1, "healer", total_healing=200_000),
                ],
            )
        ],
    )
    analysis.dps.append(
        DPSPerformance(
            "BoomMage",
            "Mage",
            4,
            "ranged",
            total_damage=500_000,
            abilities=[SpellUsage(1, "Goblin Sapper Charge", casts=2, total_amount=6000)],
        )
    )
    analysis.dps[0].abilities = [SpellUsage(1, "Goblin Sapper Charge", casts=1, total_amount=2000)]
    analysis.composition.ranged.append(PlayerIdentity("BoomMage", "Mage", 4, "ranged"))
    analysis.interrupts = [InterruptUsage("StabbyRogue", "Rogue", 3, 1766, "Kick", 5)]
    analysis.cancelled_casts = [
        CancelledCastSummary(
            "HolyPriest", "Priest", 1, 40, 4, 10.0, [CancelledCastDetail(2060, "Greater Heal", 40, 4, 10.0)]
        )
    ]
    analysis.aura_uptimes = [AuraUptime(1, "Sunder Armor", "Hydross the Unstable", s, s + 1, 91.26)]
    return analysis


@pytest.fixture
def raids(storage, build_analysis):
    """A Wednesday raid (14 Oct 2026) and a Sunday raid (18 Oct 2026)."""
    with storage() as repo:
        repo.import_raid(_raid(build_analysis, WED, datetime(2026, 10, 14, 20, 0), 100_000))
        repo.import_raid(_raid(build_analysis, SUN, datetime(2026, 10, 18, 20, 0), 300_000))
    return RaidPageService(storage)


def test_index_lists_guild_raids_newest_first_with_their_weekday(raids):
    rows = raids.index()
    assert all(isinstance(r, RaidSummary) for r in rows)
    assert [(r.report_id, r.weekday, r.size) for r in rows] == [(SUN, 6, 4), (WED, 2, 4)]
    assert rows[0].raid_date.startswith("2026-10-18")
    assert rows[0].url.endswith(f"/reports/{SUN}")
    json.dumps([r.to_dict() for r in rows])


def test_page_has_every_section_of_the_desktop_raid_view(raids):
    page = raids.page(WED, raids.index()[1])
    assert page is not None
    out = page.to_dict()
    json.dumps(out)
    assert out["version"] == RAID_PAGE_VERSION
    assert out["summary"]["weekday"] == 2
    assert out["duration_ms"] == 7_200_000
    assert [p["name"] for p in out["composition"]["ranged"]] == ["BoomMage"]
    assert out["healers"][0] | {} == {
        "name": "HolyPriest",
        "player_class": "Priest",
        "healing": 500_000,
        "overhealing": 100_000,
        "overheal_percent": 16.7,
        "dispels": 0,
        "active_percent": 0.0,
    }
    assert out["tanks"][0]["mitigation_percent"] == pytest.approx(42.86)
    assert [d["name"] for d in out["melee"]] == ["StabbyRogue"]
    assert [d["name"] for d in out["ranged"]] == ["BoomMage"]
    assert out["consumable_names"] == ["Haste Potion", "Super Mana Potion"]
    assert {r["name"]: r["counts"] for r in out["consumables"]}["StabbyRogue"] == {"Haste Potion": 2}
    assert out["boss_vs_trash"][0] == {"name": "Haste Potion", "boss": 1, "trash": 1}
    assert out["interrupts"] == [{"name": "StabbyRogue", "player_class": "Rogue", "spell_name": "Kick", "count": 5}]
    assert out["cancelled_casts"][0]["spells"][0]["spell_name"] == "Greater Heal"
    assert out["engineering"][0]["name"] == "Goblin Sapper Charge"
    hydross = out["encounters"][0]
    assert (hydross["name"], hydross["duration_ms"], hydross["damage"], hydross["healing"]) == (
        "Hydross the Unstable",
        300_000,
        100_000,
        200_000,
    )
    assert [p["name"] for p in hydross["players"]] == ["StabbyRogue", "HolyPriest"]


def test_page_without_a_summary_builds_one_from_the_analysis(raids):
    page = raids.page(SUN)
    assert isinstance(page, RaidPage)
    assert (page.summary.report_id, page.summary.weekday, page.summary.size) == (SUN, 6, 4)


def test_page_of_an_unknown_or_unreadable_raid_is_none(raids, storage):
    assert raids.page("NotStoredAtAll1") is None

    class Broken:
        def __enter__(self):
            raise StorageError("down")

        def __exit__(self, *exc):
            return False

    assert RaidPageService(Broken).page(WED) is None


def test_boss_history_keeps_each_weekday_apart(raids):
    pages = [raids.page(r.report_id, r) for r in raids.index()]
    history = boss_history(p for p in pages if p)
    assert [b.name for b in history] == ["Hydross the Unstable"]
    assert history[0].kills == 2
    days = history[0].to_dict()["days"]
    assert sorted(days) == ["2", "6"]
    assert days["2"]["kills"] == 1 and days["2"]["damage"] == 100_000
    rogue = next(p for p in days["6"]["players"] if p["name"] == "StabbyRogue")
    assert (rogue["kills"], rogue["damage"]) == (1, 300_000)


def test_from_context_reads_the_context_storage(tmp_path, build_analysis):
    path = str(tmp_path / "ctx.db")
    with PerformanceDB(path) as repo:
        repo.import_raid(_raid(build_analysis, WED, datetime(2026, 10, 14, 20, 0), 1))
    ctx = AppContext(config={}, db_path=path)
    assert [r.report_id for r in RaidPageService.from_context(ctx).index()] == [WED]


def test_helpers(build_analysis):
    analysis = _raid(build_analysis, WED, datetime(2026, 10, 14, 20, 0), 1)
    assert classify_consumable_usage(analysis)["Super Mana Potion"] == {"boss": 1, "trash": 0}
    eng = compute_engineering_stats(analysis)["Goblin Sapper Charge"]
    assert (eng["total_casts"], eng["users"], eng["min_avg"], eng["median_avg"], eng["max_avg"]) == (
        3,
        2,
        2000,
        2500,
        3000,
    )
    assert weekday_of("2026-10-19 21:00:00") == 0
    assert weekday_of("not a date") is None
    assert weekday_of(None) is None
    assert boss_history([]) == []
    page = build_page(analysis, summary_of(analysis))
    assert page.debuff_uptimes == [
        {"spell_name": "Sunder Armor", "fight_name": "Hydross the Unstable", "uptime_percent": 91.3}
    ]
    assert page.totem_uptimes == []


def test_reference_reports_are_not_guild_pages(storage, build_analysis):
    ref = "ReferenceRaidCCC"
    with storage() as repo:
        repo.import_raid(_raid(build_analysis, ref, datetime(2026, 10, 15, 20, 0), 1), source="reference")
    service = RaidPageService(storage)
    assert service.index() == []
    assert service.page(ref) is None


def test_the_scope_narrows_the_list(raids, storage):
    since_sunday = RaidScope(since="2026-10-18 00:00:00")
    assert [r.report_id for r in RaidPageService(storage, scope=since_sunday).index()] == [SUN]
    assert [r.report_id for r in RaidPageService(storage, scope=lambda: None).index()] == [SUN, WED]


def test_boss_history_keeps_a_respec_apart(raids):
    page = raids.page(WED)
    assert page is not None
    encounter = page.encounters[0]
    player = encounter.players[0]
    healer = EncounterPlayer(player.name, player.player_class, "healer", 0, 50, 0, 90.0)
    respec = replace(page, encounters=[replace(encounter, players=[healer])])
    rows = boss_history([page, respec])[0].to_dict()["days"]["2"]["players"]
    mine = [(p["name"], p["role"], p["kills"]) for p in rows if p["name"] == player.name]
    assert sorted(mine) == sorted([(player.name, player.role, 1), (player.name, "healer", 1)])
