"""Reference comparison as a service: import with the user login, label, list, delete and compare.

Every test runs on SQLite and on Postgres (the Toads Hub's backend); the Postgres half is skipped without
``WCL_STORE_TEST_DATABASE_URL``, as in ``test_store_contract.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from wcl_app import AppContext, ReferenceAuthRequired, ReferenceRequestError, ReferenceService
from wcl_app.reference import (
    MAX_LABEL_LENGTH,
    compare_raids,
    delta_percent,
    duration,
    match_encounters,
    shared_encounter_window,
)
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client.models import ConsumableUsage, EncounterPerformance, EncounterSummary

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
OURS = "OursOursOursOurs"
THEIRS = "TheirsTheirsThei"
OTHER = "OtherOtherOtherO"
START = int(datetime(2026, 9, 21, 20, 0).timestamp() * 1000)


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    if request.param == "sqlite":
        path = str(tmp_path / f"ref-{uuid.uuid4().hex[:8]}.db")
        return lambda: PerformanceDB(path)
    engine = request.getfixturevalue("pg_empty_engine")
    from wcl_store.postgres import PostgresRaidRepository

    return lambda: PostgresRaidRepository(engine)


def _ctx(storage, signed_in: bool = True) -> AppContext:
    user = MagicMock(name="user client")
    return AppContext.headless(MagicMock(name="guild client"), storage, user_client=lambda: user if signed_in else None)


def _enc(eid: int, name: str, start: int, length: int, damage: int, healing: int) -> EncounterSummary:
    return EncounterSummary(
        eid,
        name,
        START + start,
        START + start + length,
        length,
        players=[EncounterPerformance("Stab", "Rogue", 3, "melee", damage, healing, 0, 90.0)],
    )


@pytest.fixture
def ours(build_analysis):
    """Our Gruul run: Maulgar then Gruul, plus Magtheridon the reference never killed."""
    return build_analysis(
        report_id=OURS,
        title="Toads Gruul",
        start_time=START,
        end_time=START + 3_000_000,
        healer_healing=1_000_000,
        healer_overhealing=250_000,
        dps_damage=600_000,
        consumables=[
            ConsumableUsage("HolyPriest", "healer", OURS, "Super Mana Potion", 2, [START + 70_000, START + 2_500_000]),
        ],
        encounters=[
            _enc(1, "High King Maulgar", 60_000, 200_000, 500_000, 400_000),
            _enc(2, "Gruul the Dragonkiller", 600_000, 300_000, 700_000, 500_000),
            _enc(3, "Magtheridon", 2_400_000, 400_000, 900_000, 800_000),
        ],
    )


@pytest.fixture
def theirs(build_analysis):
    return build_analysis(
        report_id=THEIRS,
        title="World first Gruul",
        start_time=START,
        end_time=START + 2_000_000,
        healer_healing=800_000,
        healer_overhealing=100_000,
        dps_damage=800_000,
        consumables=[ConsumableUsage("HolyPriest", "healer", THEIRS, "Super Mana Potion", 1, [START + 70_000])],
        encounters=[
            _enc(1, "High King Maulgar", 60_000, 150_000, 550_000, 350_000),
            _enc(2, "Gruul the Dragonkiller", 400_000, 240_000, 750_000, 450_000),
        ],
    )


@pytest.fixture
def stored(storage, ours, theirs):
    with storage() as db:
        db.import_raid(ours)
        db.import_raid(theirs, source="reference")
        db.set_raid_label(THEIRS, "World first")


# ── Import ──


def test_import_uses_the_user_login_and_stores_a_labelled_reference(storage, theirs):
    ctx = _ctx(storage)
    with patch("wcl_app.raids.analyze_raid", return_value=theirs) as analyze:
        ReferenceService(ctx).import_reference(
            f"https://fresh.warcraftlogs.com/reports/{THEIRS}#fight=1", label="  World   first "
        )

    assert analyze.call_args.args[0] is ctx.user_client()
    assert analyze.call_args.args[1] == THEIRS
    [ref] = ReferenceService(ctx).references()
    assert (ref.report_id, ref.title, ref.label, ref.raid_size) == (THEIRS, "World first Gruul", "World first", 3)
    assert ReferenceService(ctx).guild_raids() == []


def test_import_without_the_login_asks_for_it(storage):
    service = ReferenceService(_ctx(storage, signed_in=False))
    assert not service.signed_in()
    with pytest.raises(ReferenceAuthRequired):
        service.import_reference(THEIRS)
    assert service.references() == []


def test_import_refuses_a_stored_report_bad_codes_and_long_labels(storage, stored):
    service = ReferenceService(_ctx(storage))
    with patch("wcl_app.raids.analyze_raid") as analyze:
        with pytest.raises(ReferenceRequestError, match="already stored as a guild raid"):
            service.import_reference(OURS)
        with pytest.raises(ReferenceRequestError, match="already stored as a reference raid"):
            service.import_reference(THEIRS)
        with pytest.raises(ReferenceRequestError, match="Not a Warcraft Logs report"):
            service.import_reference("not a report")
        with pytest.raises(ReferenceRequestError, match="at most"):
            service.import_reference(OTHER, label="x" * (MAX_LABEL_LENGTH + 1))
    analyze.assert_not_called()


# ── Label, list, delete ──


def test_label_and_delete_touch_references_only(storage, stored):
    service = ReferenceService(_ctx(storage))
    service.set_label(THEIRS, "")
    assert service.references()[0].label is None
    assert [r.report_id for r in service.guild_raids()] == [OURS]

    with pytest.raises(ReferenceRequestError, match="guild raid, not a reference"):
        service.delete_reference(OURS)
    with pytest.raises(ReferenceRequestError, match="guild raid, not a reference"):
        service.set_label(OURS, "nope")
    with pytest.raises(ReferenceRequestError, match="not stored"):
        service.delete_reference(OTHER)

    service.delete_reference(THEIRS)
    assert service.references() == []
    assert [r.report_id for r in service.guild_raids()] == [OURS]


def test_stored_raid_rows_serialise(storage, stored):
    row = ReferenceService(_ctx(storage)).references()[0].to_dict()
    assert row["report_id"] == THEIRS and row["label"] == "World first"
    json.dumps(row)


# ── Compare ──


def test_compare_reads_both_raids_from_storage(storage, stored):
    comparison = ReferenceService(_ctx(storage)).compare(OURS, THEIRS)

    assert comparison.guild.report_id == OURS and comparison.reference.report_id == THEIRS
    assert comparison.guild.raid_date == "2026-09-21 20:00:00"
    assert (comparison.guild.duration_ms, comparison.reference.duration_ms) == (3_000_000, 2_000_000)

    overview = {m.key: m for m in comparison.overview}
    assert overview["total_healing"].guild == 1_000_000 and overview["total_healing"].reference == 800_000
    assert overview["total_healing"].delta_percent == 25.0 and overview["total_healing"].better is True
    assert overview["duration"].delta_percent == 50.0 and overview["duration"].better is False
    assert overview["duration"].guild_display == "50:00"
    assert overview["overheal"].guild == 20.0 and overview["overheal"].reference == 11.1
    assert overview["overheal"].better is False
    assert overview["total_damage"].guild_display == "600.0k"

    # Magtheridon is ours only, so consumables and encounters are cut to Maulgar..Gruul.
    assert comparison.scope.scoped and comparison.scope.shared_encounters == 2
    assert comparison.scope.guild_extra_encounters == ["Magtheridon"]
    [potion] = comparison.consumables
    assert (potion.name, potion.guild_uses, potion.reference_uses) == ("Super Mana Potion", 1, 1)
    assert [e.name for e in comparison.encounters] == ["High King Maulgar", "Gruul the Dragonkiller"]
    assert comparison.encounters[1].duration_delta_percent == 25.0

    healer = next(c for c in comparison.classes if c.role == "healer")
    assert (healer.player_class, healer.metric, healer.guild_average, healer.delta_percent) == (
        "Priest",
        "healing",
        1_000_000,
        25.0,
    )
    json.dumps(comparison.to_dict())


def test_compare_refuses_the_wrong_kind_of_raid(storage, stored):
    service = ReferenceService(_ctx(storage))
    with pytest.raises(ReferenceRequestError, match="reference raid, not a guild raid"):
        service.compare(THEIRS, THEIRS)
    with pytest.raises(ReferenceRequestError, match="guild raid, not a reference raid"):
        service.compare(OURS, OURS)
    with pytest.raises(ReferenceRequestError, match="not stored"):
        service.compare(OURS, OTHER)


# ── Pure helpers ──


def test_compare_without_extra_bosses_is_not_scoped(theirs):
    comparison = compare_raids(theirs, theirs)
    assert not comparison.scope.scoped and comparison.scope.guild_extra_encounters == []
    assert all(m.delta_percent in (0.0, None) and m.better is None for m in comparison.overview)


def test_compare_without_encounters(build_analysis):
    a, b = build_analysis(report_id=OURS), build_analysis(report_id=THEIRS, healer_healing=0, healer_overhealing=0)
    comparison = compare_raids(a, b)
    assert comparison.scope.shared_encounters == 0 and comparison.encounters == []
    assert shared_encounter_window(a, b) is None
    overview = {m.key: m for m in comparison.overview}
    assert overview["total_healing"].delta_percent is None and overview["overheal"].reference is None
    assert overview["overheal"].reference_display == "—"


def test_encounters_match_by_id_then_by_name(ours, theirs):
    theirs.encounters[1].encounter_id = 99  # same boss, different id
    rows = match_encounters(ours, theirs)
    assert [r["name"] for r in rows] == ["High King Maulgar", "Gruul the Dragonkiller"]


def test_nothing_shared_is_not_scoped(ours, theirs):
    theirs.encounters = [_enc(7, "Prince Malchezaar", 0, 100_000, 1, 1)]
    window = shared_encounter_window(ours, theirs)
    assert window is not None and window["shared_count"] == 0 and window["window_start"] is None
    assert not compare_raids(ours, theirs).scope.scoped


@pytest.mark.parametrize(
    ("guild", "ref", "expected"), [(110, 100, 10.0), (90, 100, -10.0), (1, 0, None), (None, 5, None), (5, None, None)]
)
def test_delta_percent(guild, ref, expected):
    assert delta_percent(guild, ref) == expected


def test_duration_formats_hours():
    assert duration(3_725_000) == "1:02:05"
    assert duration(65_000) == "1:05"
