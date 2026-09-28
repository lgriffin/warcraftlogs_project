"""The storage contract (REQ-CORE-STORE-001): every RaidRepository backend passes this module unchanged.

Each test takes the ``repo`` fixture, which runs it once on the SQLite backend (``PerformanceDB``) and once on
the Postgres backend. The Postgres half needs a server: set ``WCL_STORE_TEST_DATABASE_URL`` (for example
``postgresql://postgres@localhost:5432/postgres``) and install ``.[postgres]``; otherwise it is
skipped with the reason shown. Each run works in its own throwaway Postgres schema (``pg_engine`` in
``tests/conftest.py``).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from typing import Any

import pytest
from wcl_store import RaidRepository, StorageError
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client.models import (
    AuraBand,
    AuraUptime,
    BossEvent,
    CancelledCastCorrelation,
    CancelledCastDetail,
    CancelledCastSummary,
    ConsumableUsage,
    DPSPerformance,
    EncounterPerformance,
    EncounterSummary,
    HealerPerformance,
    InterruptUsage,
    NextCastInfo,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    RaidMetadata,
    SpellUsage,
    TankPerformance,
)

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]

KARA = "KaraKaraKaraKara"
GRUUL = "GruulGruulGruulG"
REF = "RefRefRefRefRefR"
DATE_RE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
DAY = 86_400_000
T0 = 1_700_000_000_000


# ── Backends ──


@contextmanager
def _open(backend: str, request: pytest.FixtureRequest, tmp_path) -> Iterator[RaidRepository]:
    if backend == "sqlite":
        with PerformanceDB(str(tmp_path / f"contract-{uuid.uuid4().hex[:8]}.db")) as db:
            yield db
    else:
        engine = request.getfixturevalue("pg_empty_engine")  # skips first when Postgres or the extra is missing
        from wcl_store.postgres import PostgresRaidRepository

        with PostgresRaidRepository(engine) as repo:
            yield repo


@pytest.fixture(params=BACKENDS)
def repo(request, tmp_path) -> Iterator[RaidRepository]:
    with _open(request.param, request, tmp_path) as backend:
        yield backend


# ── Test data ──


def _analysis(
    code: str = KARA,
    *,
    start: int = T0,
    title: str = "Karazhan",
    zone: str | None = "Karazhan",
    healer: str = "Holy",
    dps_role: str = "melee",
    overrides_applied: dict[str, str] | None = None,
) -> RaidAnalysis:
    """A raid with a row of every kind the store keeps."""
    fight = EncounterSummary(
        encounter_id=652,
        name="Attumen",
        start_time=10_000,
        end_time=70_000,
        duration_ms=60_000,
        players=[
            EncounterPerformance("Stab", "Rogue", 3, "melee", 90_000, 0, 5_000, 88.5),
            EncounterPerformance(healer, "Priest", 1, "healer", 1_000, 50_000, 2_000, 97.0),
            EncounterPerformance("Tanky", "Warrior", 2, "tank", 20_000, 0, 70_000, 99.0),
        ],
        boss_events=[BossEvent(15_000, "cast", "Shadow Cleave", 29832, "Attumen")],
    )
    second = replace(
        fight, encounter_id=653, name="Moroes", start_time=100_000, end_time=160_000, players=[], boss_events=[]
    )
    return RaidAnalysis(
        metadata=RaidMetadata(code, title, "Guildie", start, start + 3_600_000, zone),
        composition=RaidComposition(
            tanks=[PlayerIdentity("Tanky", "Warrior", 2, "tank")],
            healers=[PlayerIdentity(healer, "Priest", 1, "healer")],
            melee=[PlayerIdentity("Stab", "Rogue", 3, dps_role)] if dps_role == "melee" else [],
            ranged=[PlayerIdentity("Stab", "Rogue", 3, dps_role)] if dps_role != "melee" else [],
        ),
        healers=[
            HealerPerformance(
                healer,
                "Priest",
                1,
                total_healing=500_000,
                total_overhealing=100_000,
                spells=[
                    SpellUsage(2060, "Greater Heal", 50, 300_000),
                    SpellUsage(139, "Renew", 80, 200_000),
                ],
                fear_ward_casts=4,
                active_time_percent=91.25,
            )
        ],
        tanks=[
            TankPerformance(
                "Tanky",
                "Warrior",
                2,
                total_damage_taken=800_000,
                total_mitigated=600_000,
                damage_taken_breakdown=[SpellUsage(1, "Melee", 200)],
                abilities_used=[SpellUsage(6572, "Revenge", 45), SpellUsage(23922, "Shield Slam", 30)],
                active_time_percent=99.5,
            )
        ],
        dps=[
            DPSPerformance(
                "Stab",
                "Rogue",
                3,
                role=dps_role,
                total_damage=400_000,
                abilities=[SpellUsage(26862, "Sinister Strike", 120, 150_000)],
                active_time_percent=88.0,
            )
        ],
        consumables=[
            ConsumableUsage(healer, "healer", code, "Super Mana Potion", 3, [60_000, 180_000, 300_000]),
            ConsumableUsage("Stab", "melee", code, "Haste Potion", 1, []),
        ],
        interrupts=[InterruptUsage("Stab", "Rogue", 3, 38768, "Kick", 2, [20_000, 40_000])],
        cancelled_casts=[
            CancelledCastSummary(
                healer,
                "Priest",
                1,
                total_casts=130,
                cancelled_casts=6,
                cancel_rate=4.6,
                spell_details=[
                    CancelledCastDetail(139, "Renew", 80, 1, 1.25, [30_000]),
                    CancelledCastDetail(
                        2060,
                        "Greater Heal",
                        50,
                        5,
                        10.0,
                        [12_000, 14_000],
                        correlations=[
                            CancelledCastCorrelation(
                                12_000, [BossEvent(12_500, "cast", "Shadow Cleave", 29832, "Attumen", 500)]
                            )
                        ],
                        next_casts=[NextCastInfo(139, "Renew", 12_100), None],
                    ),
                ],
            )
        ],
        aura_uptimes=[AuraUptime(27150, "Sunder Armor", "Attumen", 10_000, 70_000, 83.3, [AuraBand(10_000, 60_000)])],
        totem_uptimes=[AuraUptime(25528, "Strength of Earth", "Moroes", 100_000, 160_000, 50.0, [])],
        encounters=[fight, second],
        role_overrides_applied=overrides_applied or {},
    )


# ── Raids ──


def test_backend_implements_the_protocol(repo):
    assert isinstance(repo, RaidRepository)


def test_import_marks_the_raid_stored(repo):
    assert not repo.is_raid_imported(KARA)
    assert repo.get_raid_source(KARA) is None
    repo.import_raid(_analysis())
    repo.import_raid(_analysis(REF, start=T0 + DAY), source="reference")

    assert repo.is_raid_imported(KARA)
    assert repo.get_raid_source(KARA) == "guild"
    assert repo.get_raid_source(REF) == "reference"
    codes = repo.get_imported_report_codes()
    assert set(codes) == {KARA, REF}
    assert all(DATE_RE.match(v) for v in codes.values())


def test_raid_list_is_guild_raids_newest_first(repo):
    repo.import_raid(_analysis(KARA, start=T0))
    repo.import_raid(_analysis(GRUUL, start=T0 + DAY, title="Gruul"))
    repo.import_raid(_analysis(REF, start=T0 + 2 * DAY), source="reference")

    rows = repo.get_raid_list()
    assert [r["report_id"] for r in rows] == [GRUUL, KARA]
    assert set(rows[0]) == {"report_id", "title", "owner", "raid_date", "imported_at"}
    assert rows[0]["title"] == "Gruul" and rows[0]["owner"] == "Guildie"
    assert DATE_RE.match(rows[0]["raid_date"]) and DATE_RE.match(rows[0]["imported_at"])
    assert [r["report_id"] for r in repo.get_raid_list(limit=1)] == [GRUUL]


def test_count_raids_counts_each_source(repo):
    assert repo.count_raids() == 0
    repo.import_raid(_analysis(KARA, start=T0))
    repo.import_raid(_analysis(GRUUL, start=T0 + DAY, title="Gruul"))
    repo.import_raid(_analysis(REF, start=T0 + 2 * DAY), source="reference")
    repo.import_raid(_analysis(KARA, start=T0))  # storing again adds no raid

    assert repo.count_raids() == 2
    assert repo.count_raids("guild") == 2
    assert repo.count_raids("reference") == 1


def test_raid_analysis_round_trips(repo):
    repo.import_raid(_analysis())
    got = repo.get_raid_analysis(KARA)
    assert got is not None

    assert (got.metadata.report_id, got.metadata.title, got.metadata.owner) == (KARA, "Karazhan", "Guildie")
    assert (got.metadata.start_time, got.metadata.end_time) == (T0, T0 + 3_600_000)
    assert {(p.name, p.role) for p in got.composition.all_players} == {
        ("Tanky", "tank"),
        ("Holy", "healer"),
        ("Stab", "melee"),
    }

    (h,) = got.healers
    assert (h.name, h.player_class, h.source_id) == ("Holy", "Priest", 0)
    assert (h.total_healing, h.total_overhealing, h.fear_ward_casts, h.active_time_percent) == (
        500_000,
        100_000,
        4,
        91.25,
    )
    assert [(s.spell_id, s.spell_name, s.casts, s.total_amount) for s in h.spells] == [
        (2060, "Greater Heal", 50, 300_000),
        (139, "Renew", 80, 200_000),
    ]

    (tank,) = got.tanks
    assert (tank.total_damage_taken, tank.total_mitigated, tank.active_time_percent) == (800_000, 600_000, 99.5)
    assert [(s.spell_name, s.casts) for s in tank.damage_taken_breakdown] == [("Melee", 200)]
    assert [(s.spell_name, s.casts) for s in tank.abilities_used] == [("Revenge", 45), ("Shield Slam", 30)]

    (d,) = got.dps
    assert (d.role, d.total_damage, d.active_time_percent) == ("melee", 400_000, 88.0)
    assert [(a.spell_name, a.casts, a.total_amount) for a in d.abilities] == [("Sinister Strike", 120, 150_000)]

    assert sorted(
        (c.player_name, c.player_role, c.consumable_name, c.count, c.timestamps) for c in got.consumables
    ) == [
        ("Holy", "healer", "Super Mana Potion", 3, [60_000, 180_000, 300_000]),
        ("Stab", "melee", "Haste Potion", 1, []),
    ]
    assert all(c.report_id == KARA for c in got.consumables)
    assert [(i.player_name, i.spell_name, i.count, i.timestamps) for i in got.interrupts] == [
        ("Stab", "Kick", 2, [20_000, 40_000])
    ]

    (cc,) = got.cancelled_casts
    assert (cc.player_name, cc.total_casts, cc.cancelled_casts, cc.cancel_rate) == ("Holy", 130, 6, 4.6)
    gh, renew = cc.spell_details  # most-cancelled first
    assert (gh.spell_name, gh.cancelled_casts, gh.timestamps) == ("Greater Heal", 5, [12_000, 14_000])
    assert gh.next_casts == [NextCastInfo(139, "Renew", 12_100), None]
    assert gh.correlations == [
        CancelledCastCorrelation(12_000, [BossEvent(12_500, "cast", "Shadow Cleave", 29832, "Attumen", 500)])
    ]
    assert (renew.spell_name, renew.correlations, renew.next_casts) == ("Renew", [], [])

    assert got.aura_uptimes == [
        AuraUptime(27150, "Sunder Armor", "Attumen", 10_000, 70_000, 83.3, [AuraBand(10_000, 60_000)])
    ]
    assert got.totem_uptimes == [AuraUptime(25528, "Strength of Earth", "Moroes", 100_000, 160_000, 50.0, [])]

    attumen, moroes = got.encounters
    assert (attumen.encounter_id, attumen.name, attumen.duration_ms) == (652, "Attumen", 60_000)
    assert [p.name for p in attumen.players] == ["Stab", "Tanky", "Holy"]  # most damage first
    assert attumen.players[0] == EncounterPerformance("Stab", "Rogue", 0, "melee", 90_000, 0, 5_000, 88.5)
    assert attumen.boss_events == [BossEvent(15_000, "cast", "Shadow Cleave", 29832, "Attumen")]
    assert (moroes.name, moroes.players, moroes.boss_events) == ("Moroes", [], [])


def test_stored_analysis_is_stable_when_stored_again(repo):
    repo.import_raid(_analysis())
    first = repo.get_raid_analysis(KARA)
    assert first is not None
    repo.replace_raid_analysis(first)
    assert asdict(repo.get_raid_analysis(KARA)) == asdict(first)


def test_unknown_raid_reads_as_empty(repo):
    assert repo.get_raid_analysis(KARA) is None
    assert repo.get_raid_roster(KARA) == []
    repo.delete_raid(KARA)  # no error


def test_import_again_merges_and_keeps_the_source(repo):
    repo.import_raid(_analysis(), source="reference")
    repo.import_raid(_analysis(title="Karazhan (full clear)", zone=None, healer="Disc"))

    assert repo.get_raid_source(KARA) == "reference"
    got = repo.get_raid_analysis(KARA)
    assert got is not None and got.metadata.title == "Karazhan (full clear)"
    assert [h.name for h in got.healers] == ["Disc"]  # role rows are replaced
    # Consumables merge by player, so the old healer's potions are still there.
    assert {c.player_name for c in got.consumables} == {"Holy", "Disc", "Stab"}


def test_replace_swaps_rows_and_keeps_the_source(repo):
    repo.import_raid(_analysis(), source="reference")
    repo.replace_raid_analysis(_analysis(dps_role="ranged", healer="Disc"))

    assert repo.get_raid_source(KARA) == "reference"
    assert {(r["name"], r["role"]) for r in repo.get_raid_roster(KARA)} == {
        ("Disc", "healer"),
        ("Stab", "ranged"),
        ("Tanky", "tank"),
    }
    got = repo.get_raid_analysis(KARA)
    assert got is not None
    assert {c.player_name for c in got.consumables} == {"Disc", "Stab"}  # nothing left of the old healer


def test_failed_replace_raises_storage_error_and_keeps_the_old_data(repo):
    repo.import_raid(_analysis())
    before = asdict(repo.get_raid_analysis(KARA))
    broken = _analysis(healer="Disc")
    broken.dps[0].role = "healer"  # not a dps role: the store's check constraint rejects it

    with pytest.raises(StorageError):
        repo.replace_raid_analysis(broken)
    assert asdict(repo.get_raid_analysis(KARA)) == before


def test_failed_import_stores_nothing(repo):
    broken = _analysis()
    broken.dps[0].role = "healer"

    with pytest.raises(StorageError):
        repo.import_raid(broken)
    assert not repo.is_raid_imported(KARA)
    assert repo.get_character_history("Holy") is None
    # The connection is still usable afterwards.
    repo.import_raid(_analysis())
    assert repo.is_raid_imported(KARA)


def test_delete_removes_one_raid(repo):
    repo.import_raid(_analysis(KARA, start=T0))
    repo.import_raid(_analysis(GRUUL, start=T0 + DAY))
    repo.delete_raid(KARA)

    assert not repo.is_raid_imported(KARA)
    assert repo.get_raid_analysis(KARA) is None
    assert [r["report_id"] for r in repo.get_reports_for_character("Holy")] == [GRUUL]
    assert repo.get_raid_analysis(GRUUL) is not None


def test_roster_by_role_then_name(repo):
    analysis = _analysis()
    analysis.dps.append(DPSPerformance("alpha", "Mage", 9, role="ranged", total_damage=1))
    analysis.dps.append(DPSPerformance("Zed", "Hunter", 10, role="ranged", total_damage=1))
    repo.import_raid(analysis)

    # Text sorts by byte value on every backend, so "Zed" comes before "alpha".
    assert repo.get_raid_roster(KARA) == [
        {"name": "Holy", "player_class": "Priest", "role": "healer"},
        {"name": "Stab", "player_class": "Rogue", "role": "melee"},
        {"name": "Zed", "player_class": "Hunter", "role": "ranged"},
        {"name": "alpha", "player_class": "Mage", "role": "ranged"},
        {"name": "Tanky", "player_class": "Warrior", "role": "tank"},
    ]


# ── Characters ──


def test_character_history(repo):
    repo.import_raid(_analysis(KARA, start=T0))
    second = _analysis(GRUUL, start=T0 + DAY)
    second.healers[0].total_healing = 700_000
    repo.import_raid(second)
    repo.import_raid(_analysis(REF, start=T0 + 2 * DAY), source="reference")

    h = repo.get_character_history("holy")  # any case
    assert h is not None
    assert (h.name, h.player_class, h.total_raids) == ("Holy", "Priest", 2)
    assert h.avg_healing == 600_000.0
    assert (h.avg_damage, h.avg_mitigation_percent) == (None, None)
    assert h.total_consumables_used == 6
    assert h.avg_active_time == 91.2  # round(91.25, 1)
    assert h.first_seen is not None and h.last_seen is not None and h.first_seen < h.last_seen

    ref = repo.get_character_history("Holy", source="reference")
    assert ref is not None and ref.total_raids == 1
    assert repo.get_character_history("Nobody") is None


def test_reports_for_character_cover_every_source_newest_first(repo):
    repo.import_raid(_analysis(KARA, start=T0))
    repo.import_raid(_analysis(REF, start=T0 + DAY), source="reference")

    rows = repo.get_reports_for_character("STAB")
    assert [r["report_id"] for r in rows] == [REF, KARA]
    assert rows[0] == {
        "report_id": REF,
        "title": "Karazhan",
        "owner": "Guildie",
        "zone": "Karazhan",
        "start_time": T0 + DAY,
        "end_time": T0 + DAY + 3_600_000,
        "source": "reference",
    }
    assert repo.get_reports_for_character("Nobody") == []


def test_character_raid_roles(repo):
    repo.import_raid(_analysis(GRUUL, start=T0 + DAY, dps_role="ranged"))
    repo.import_raid(_analysis(KARA, start=T0))
    repo.import_raid(_analysis(REF, start=T0 + 2 * DAY), source="reference")

    rows = repo.get_character_raid_roles("stab")
    assert [(r["report_id"], r["role"], r["damage"]) for r in rows] == [
        (KARA, "melee", 400_000),
        (GRUUL, "ranged", 400_000),
    ]
    assert set(rows[0]) == {
        "raid_id",
        "report_id",
        "title",
        "raid_date",
        "zone",
        "role",
        "healing",
        "overheal_percent",
        "damage",
        "damage_taken",
        "mitigation_percent",
    }
    assert (rows[0]["healing"], rows[0]["damage_taken"], rows[0]["mitigation_percent"]) == (None, None, None)

    (healer,) = repo.get_character_raid_roles("Holy", sources=("reference",))
    assert (healer["report_id"], healer["role"], healer["healing"], healer["overheal_percent"]) == (
        REF,
        "healer",
        500_000,
        16.7,  # HealerPerformance works it out from healing and overhealing
    )
    (tank,) = [r for r in repo.get_character_raid_roles("Tanky", ("guild", "reference")) if r["report_id"] == KARA]
    assert (tank["role"], tank["damage_taken"], tank["mitigation_percent"], tank["damage"]) == (
        "tank",
        800_000,
        42.86,  # worked out from damage taken and mitigated
        None,
    )


def test_character_spell_casts(repo):
    repo.import_raid(_analysis())
    raid_id = repo.get_character_raid_roles("Tanky")[0]["raid_id"]

    def casts(name: str, sources: tuple[str, ...] = ("guild",)) -> list[tuple]:
        return sorted(
            (r["raid_id"], r["role"], r["spell_id"], r["spell_name"], r["casts"])
            for r in repo.get_character_spell_casts(name, sources)
        )

    assert casts("tanky") == [(raid_id, "tank", 6572, "Revenge", 45), (raid_id, "tank", 23922, "Shield Slam", 30)]
    assert casts("Holy") == [(raid_id, "healer", 139, "Renew", 80), (raid_id, "healer", 2060, "Greater Heal", 50)]
    assert casts("Stab") == [(raid_id, "melee", 26862, "Sinister Strike", 120)]
    assert casts("Stab", ("reference",)) == []


def test_character_consumable_counts(repo):
    repo.import_raid(_analysis())
    raid_id = repo.get_character_raid_roles("Holy")[0]["raid_id"]
    assert repo.get_character_consumable_counts("HOLY") == [
        {"raid_id": raid_id, "consumable_name": "Super Mana Potion", "count": 3}
    ]
    assert repo.get_character_consumable_counts("Holy", ("reference",)) == []


# ── Guild totals ──


def test_raid_attendance_counts_raids_per_character(repo):
    repo.import_raid(_analysis(KARA, start=T0))
    repo.import_raid(_analysis(GRUUL, start=T0 + DAY, healer="Disc"))
    repo.import_raid(_analysis(REF, start=T0 + 2 * DAY), source="reference")

    assert repo.get_raid_attendance() == [
        {"name": "Disc", "player_class": "Priest", "raids": 1},
        {"name": "Holy", "player_class": "Priest", "raids": 1},
        {"name": "Stab", "player_class": "Rogue", "raids": 2},
        {"name": "Tanky", "player_class": "Warrior", "raids": 2},
    ]
    both = {r["name"]: r["raids"] for r in repo.get_raid_attendance(("guild", "reference"))}
    assert both == {"Disc": 1, "Holy": 2, "Stab": 3, "Tanky": 3}
    assert repo.get_raid_attendance(("nowhere",)) == []


def test_consumable_totals_sum_across_raids(repo):
    repo.import_raid(_analysis(KARA, start=T0))
    repo.import_raid(_analysis(GRUUL, start=T0 + DAY))
    repo.import_raid(_analysis(REF, start=T0 + 2 * DAY), source="reference")
    unused = _analysis("UnusedUnusedUnus", start=T0 + 3 * DAY)
    unused.consumables = [ConsumableUsage("Stab", "melee", "UnusedUnusedUnus", "Drums of Battle", 0, [])]
    repo.import_raid(unused)

    assert repo.get_consumable_totals() == [
        {"name": "Holy", "consumable_name": "Super Mana Potion", "count": 6, "raids": 2},
        {"name": "Stab", "consumable_name": "Haste Potion", "count": 2, "raids": 2},
    ]
    both = repo.get_consumable_totals(("guild", "reference"))
    assert [(r["name"], r["count"], r["raids"]) for r in both] == [("Holy", 9, 3), ("Stab", 3, 3)]


# ── Player pages ──


def test_player_page_is_created_once_whatever_the_case(repo):
    page = repo.get_or_create_player_page("Holy", "spineshatter", "eu")
    assert isinstance(page, int)
    assert repo.get_or_create_player_page("holy", "Spineshatter", "EU") == page
    assert repo.get_or_create_player_page("Holy", "firemaw", "eu") != page


def test_find_player_pages(repo):
    b = repo.get_or_create_player_page("bob", "firemaw", "eu")
    a = repo.get_or_create_player_page("Alice", "spineshatter", "eu")
    repo.set_player_page_log(a, KARA, "added")
    repo.set_player_page_log(a, GRUUL, "dismissed")

    pages = repo.find_player_pages()
    assert [(p["id"], p["name"], p["log_count"]) for p in pages] == [(a, "Alice", 1), (b, "bob", 0)]
    assert set(pages[0]) == {"id", "name", "server", "region", "created_at", "log_count"}
    assert DATE_RE.match(pages[0]["created_at"])
    assert [p["id"] for p in repo.find_player_pages("BOB")] == [b]


def test_player_page_logs(repo):
    repo.import_raid(_analysis(GRUUL))
    page = repo.get_or_create_player_page("Holy", "spineshatter", "eu")
    repo.set_player_page_log(page, KARA, "added", title="Kara", zone="Karazhan", owner="Guildie", start_time=T0)
    repo.set_player_page_log(page, GRUUL, "added", title="Gruul", start_time=T0 + DAY)
    repo.set_player_page_log(page, REF, "dismissed", start_time=T0 - DAY)

    logs = repo.get_player_page_logs(page)
    assert [(r["report_id"], r["status"], r["imported"]) for r in logs] == [
        (GRUUL, "added", True),
        (KARA, "added", False),
        (REF, "dismissed", False),
    ]
    assert set(logs[0]) == {"report_id", "status", "title", "zone", "owner", "start_time", "updated_at", "imported"}
    assert logs[0]["imported"] is True and DATE_RE.match(logs[0]["updated_at"])
    assert [r["report_id"] for r in repo.get_player_page_logs(page, status="dismissed")] == [REF]

    # Dismissing with no metadata keeps what was stored.
    repo.set_player_page_log(page, KARA, "dismissed")
    (kara,) = [r for r in repo.get_player_page_logs(page) if r["report_id"] == KARA]
    assert (kara["status"], kara["title"], kara["zone"], kara["owner"], kara["start_time"]) == (
        "dismissed",
        "Kara",
        "Karazhan",
        "Guildie",
        T0,
    )

    assert repo.remove_player_page_log(page, KARA) is True
    assert repo.remove_player_page_log(page, KARA) is False
    assert KARA not in {r["report_id"] for r in repo.get_player_page_logs(page)}


# ── Role overrides ──


def test_role_overrides(repo):
    repo.set_role_override("Holy", "dps")
    repo.set_role_override("holy", "tank")  # same character: replaces
    repo.set_role_override("Holy", "healer", KARA)
    repo.set_role_override("Abe", "melee")

    rows = repo.get_role_overrides()
    assert [(r["character_name"], r["report_id"], r["role"]) for r in rows] == [
        ("Abe", "", "melee"),
        ("Holy", "", "tank"),
        ("Holy", KARA, "healer"),
    ]
    assert set(rows[0]) == {"character_name", "report_id", "role", "updated_at"}
    assert DATE_RE.match(rows[0]["updated_at"])
    assert [r["report_id"] for r in repo.get_role_overrides("HOLY")] == ["", KARA]

    assert repo.get_role_overrides_for_report(KARA) == {"Abe": "melee", "Holy": "healer"}
    assert repo.get_role_overrides_for_report(GRUUL) == {"Abe": "melee", "Holy": "tank"}

    assert repo.clear_role_override("HOLY", KARA) is True
    assert repo.clear_role_override("Holy", KARA) is False
    assert repo.get_role_overrides_for_report(KARA) == {"Abe": "melee", "Holy": "tank"}


def test_names_fold_ascii_case_only(repo):
    """SQLite's NOCASE folds A-Z only, so both backends keep Ä and ä apart while matching H and h."""
    upper = repo.get_or_create_player_page("\u00c4sa", "firemaw", "eu")
    lower = repo.get_or_create_player_page("\u00e4sa", "firemaw", "eu")
    assert upper != lower
    assert repo.get_or_create_player_page("\u00c4SA", "FIREMAW", "EU") == upper
    assert [p["id"] for p in repo.find_player_pages("\u00e4SA")] == [lower]

    repo.set_role_override("\u00c4sa", "tank")
    repo.set_role_override("\u00e4sa", "healer")
    assert [r["role"] for r in repo.get_role_overrides("\u00c4SA")] == ["tank"]
    assert repo.get_role_overrides_for_report(KARA) == {"\u00c4sa": "tank", "\u00e4sa": "healer"}


def test_role_override_raids_follow_the_stored_analysis(repo):
    repo.import_raid(_analysis(KARA, overrides_applied={"Stab": "ranged"}))
    repo.import_raid(_analysis(GRUUL, start=T0 + DAY))
    assert repo.get_role_override_raids("stab") == {KARA}
    assert repo.get_role_override_raids("Holy") == set()

    repo.replace_raid_analysis(_analysis(KARA))
    assert repo.get_role_override_raids("Stab") == set()


# ── Both backends side by side ──


def _snapshot(repo: RaidRepository) -> dict[str, Any]:
    """Every read method's output after a fixed history of writes, minus wall-clock times and row ids."""
    repo.import_raid(_analysis(KARA, start=T0, overrides_applied={"Stab": "ranged"}))
    repo.import_raid(_analysis(GRUUL, start=T0 + DAY, dps_role="ranged", healer="Disc"))
    repo.import_raid(_analysis(REF, start=T0 + 2 * DAY), source="reference")
    repo.replace_raid_analysis(_analysis(GRUUL, start=T0 + DAY, healer="Holy"))
    repo.delete_raid(REF)
    page = repo.get_or_create_player_page("Holy", "spineshatter", "eu")
    repo.set_player_page_log(page, KARA, "added", title="Kara", start_time=T0)
    repo.set_player_page_log(page, REF, "dismissed")
    repo.set_role_override("Stab", "dps")
    repo.set_role_override("Holy", "healer", GRUUL)

    clock = {"imported_at", "created_at", "updated_at", "raid_id", "id"}

    def rows(items: list[dict]) -> list[dict]:
        return [{k: v for k, v in r.items() if k not in clock} for r in items]

    def unordered(items: list[dict]) -> list[dict]:
        return sorted(rows(items), key=repr)

    return {
        "imported": sorted(repo.get_imported_report_codes()),
        "raids": rows(repo.get_raid_list()),
        "analysis": [asdict(repo.get_raid_analysis(c)) for c in (KARA, GRUUL)],
        "roster": repo.get_raid_roster(GRUUL),
        "sources": [repo.get_raid_source(c) for c in (KARA, GRUUL, REF)],
        "history": {n: asdict(repo.get_character_history(n)) for n in ("Holy", "Stab", "Tanky", "Disc")},
        "reports": rows(repo.get_reports_for_character("Holy")),
        "roles": rows(repo.get_character_raid_roles("Stab", ("guild", "reference"))),
        "casts": unordered(repo.get_character_spell_casts("Holy")),
        "consumables": unordered(repo.get_character_consumable_counts("Disc")),
        "attendance": repo.get_raid_attendance(("guild", "reference")),
        "consumable_totals": repo.get_consumable_totals(("guild", "reference")),
        "pages": rows(repo.find_player_pages()),
        "page_logs": rows(repo.get_player_page_logs(page)),
        "overrides": rows(repo.get_role_overrides()),
        "for_report": repo.get_role_overrides_for_report(GRUUL),
        "override_raids": sorted(repo.get_role_override_raids("Stab")),
    }


@pytest.mark.postgres
def test_both_backends_return_the_same_results(request, tmp_path):
    with _open("postgres", request, tmp_path) as pg, _open("sqlite", request, tmp_path) as lite:
        assert _snapshot(pg) == _snapshot(lite)
