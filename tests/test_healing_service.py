"""Week-on-week healing (``wcl_app.healing``): the numbers, the charts built from them, and the service over storage.

The service tests run on SQLite and on Postgres; the Postgres half is skipped without
``WCL_STORE_TEST_DATABASE_URL``, as in ``test_store_contract.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from wcl_app import AppContext, HealingService
from wcl_app.charts import MAX_SERIES
from wcl_app.healing import MAX_WEEKS, MIN_WEEKS, week_start, weekly_healing
from wcl_store import StorageError
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client.models import HealerPerformance

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
TODAY = date(2026, 9, 27)  # a Sunday; its week starts Mon 21 Sep


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _raids(build_analysis, *raids):
    """(report_id, "YYYY-MM-DD", {healer: healing}) -> the raid rows and a loader for them."""
    rows, analyses = [], {}
    for report_id, day, healing in raids:
        a = build_analysis(report_id=report_id)
        a.healers = [
            HealerPerformance(name, "Priest", i, total_healing=amount, total_overhealing=amount // 4)
            for i, (name, amount) in enumerate(healing.items())
        ]
        analyses[report_id] = a
        rows.append({"report_id": report_id, "raid_date": f"{day} 20:00:00"})
    return rows, analyses.get


def test_weeks_run_monday_to_sunday():
    assert week_start(date(2026, 9, 21)) == date(2026, 9, 21)
    assert week_start(TODAY) == date(2026, 9, 21)


def test_every_week_in_the_window_is_listed_oldest_first_raided_or_not():
    result = weekly_healing([], lambda _: None, TODAY, weeks=4)
    assert [w.start for w in result.weeks] == [
        date(2026, 8, 31),
        date(2026, 9, 7),
        date(2026, 9, 14),
        date(2026, 9, 21),
    ]
    assert result.raids == 0 and not result.healers


@pytest.mark.parametrize(("asked", "weeks"), [(0, MIN_WEEKS), (1, MIN_WEEKS), (8, 8), (500, MAX_WEEKS)])
def test_the_window_is_clamped(asked, weeks):
    assert len(weekly_healing([], lambda _: None, TODAY, weeks=asked).weeks) == weeks


def test_numbers_are_per_raid_so_a_two_raid_week_compares_fairly(build_analysis):
    rows, load = _raids(
        build_analysis,
        ("KaraA", "2026-09-08", {"Holy": 400_000, "Resto": 200_000}),
        ("KaraB", "2026-09-10", {"Holy": 600_000}),
        ("Gruul", "2026-09-22", {"Holy": 900_000, "Resto": 300_000}),
    )
    result = weekly_healing(rows, load, TODAY, weeks=3)
    first, skipped, last = result.weeks
    assert (first.raids, first.healing, first.per_raid, first.healers) == (2, 1_200_000, 600_000, 2)
    assert first.change_percent is None
    assert first.overheal_percent == 20.0  # overheal is a quarter of healing: 25 / 125
    assert skipped.raids == 0 and skipped.per_raid is None and skipped.overheal_percent is None
    assert last.change_percent == 100.0  # 1.2M per raid against 600K, skipping the week without a raid
    holy, resto = result.healers
    assert holy.name == "Holy" and holy.per_raid() == [500_000, None, 900_000]
    assert resto.per_raid() == [200_000, None, 300_000]
    assert result.to_dict()["weeks"][0] == {
        "week": "2026-09-07",
        "raids": 2,
        "healing": 1_200_000,
        "healing_per_raid": 600_000,
        "overheal_percent": 20.0,
        "healers": 2,
        "change_percent": None,
    }
    assert result.to_dict()["healers"][1] == {
        "name": "Resto",
        "player_class": "Priest",
        "healing": 500_000,
        "healing_per_raid": [200_000, None, 300_000],
    }


def test_raids_outside_the_window_or_without_an_analysis_are_left_out(build_analysis):
    rows, load = _raids(build_analysis, ("Old", "2026-01-05", {"Holy": 1}), ("Kara", "2026-09-22", {"Holy": 10}))
    rows += [{"report_id": "Gone", "raid_date": "2026-09-23 20:00:00"}, {"report_id": "Bad", "raid_date": "nope"}]
    loaded = []

    def tracking_load(report_id):
        loaded.append(report_id)
        return load(report_id)

    result = weekly_healing(rows, tracking_load, TODAY, weeks=2)
    assert loaded == ["Kara", "Gone"]
    assert result.raids == 1


def test_a_healer_is_matched_across_raids_ignoring_case(build_analysis):
    rows, load = _raids(build_analysis, ("A", "2026-09-15", {"Holy": 100}), ("B", "2026-09-22", {"HOLY": 300}))
    result = weekly_healing(rows, load, TODAY, weeks=2)
    assert len(result.healers) == 1 and result.healers[0].per_raid() == [100, 300]


class TestCharts:
    def test_raid_chart(self, build_analysis):
        rows, load = _raids(
            build_analysis, ("A", "2026-09-15", {"Holy": 1_000_000}), ("B", "2026-09-22", {"Holy": 1_100_000})
        )
        chart = weekly_healing(rows, load, TODAY, weeks=4).raid_chart()
        assert chart.kind == "bar" and chart.id == "healing_weekly"
        assert chart.categories == ["31 Aug", "7 Sep", "14 Sep", "21 Sep"]
        assert chart.series[0].values == [None, None, 1_000_000, 1_100_000]
        assert chart.series[0].display == ["-", "-", "1.0M", "1.1M"]
        assert chart.series[0].emphasis
        assert chart.y_max == 2_000_000
        assert chart.notes == ["Week of 21 Sep: +10.0% on the week before it raided.", "Overheal that week: 20.0%."]

    def test_raid_chart_with_one_raided_week_has_no_change_note(self, build_analysis):
        rows, load = _raids(build_analysis, ("A", "2026-09-22", {"Holy": 100}))
        assert weekly_healing(rows, load, TODAY, weeks=2).raid_chart().notes == ["Overheal that week: 20.0%."]

    def test_empty_charts_say_why(self):
        result = weekly_healing([], lambda _: None, TODAY, weeks=6)
        assert result.raid_chart().empty == "No guild raids in the last 6 weeks."
        assert result.healer_chart().empty == "No healers in guild raids in the last 6 weeks."
        assert result.healer_chart().series == []

    def test_healer_chart_draws_only_the_top_healers_and_says_so(self, build_analysis):
        healing = {f"Healer{i:02d}": 1_000 * (i + 1) for i in range(MAX_SERIES + 3)}
        rows, load = _raids(build_analysis, ("A", "2026-09-22", healing))
        chart = weekly_healing(rows, load, TODAY, weeks=2).healer_chart()
        assert chart.kind == "line"
        assert len(chart.series) == MAX_SERIES
        assert chart.series[0].name == "Healer10" and chart.series[0].key == "healer10"
        assert chart.notes == [f"Showing the {MAX_SERIES} healers with the most healing per raid; 3 more not drawn."]

    def test_top_limit_is_honoured(self, build_analysis):
        rows, load = _raids(build_analysis, ("A", "2026-09-22", {"Holy": 3, "Resto": 2, "Disc": 1}))
        chart = weekly_healing(rows, load, TODAY, weeks=2).healer_chart(top=2)
        assert [s.name for s in chart.series] == ["Holy", "Resto"]


# ── Service over storage ──


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    if request.param == "sqlite":
        path = str(tmp_path / f"healing-{uuid.uuid4().hex[:8]}.db")
        return lambda: PerformanceDB(path)
    engine = request.getfixturevalue("pg_empty_engine")
    from wcl_store.postgres import PostgresRaidRepository

    return lambda: PostgresRaidRepository(engine)


def test_service_reads_guild_raids_only(storage, build_analysis):
    with storage() as repo:
        start = datetime(2026, 9, 22, 20, 0)
        repo.import_raid(build_analysis(report_id="GuildGuildGuildG", start_time=_ms(start), healer_healing=800_000))
        repo.import_raid(
            build_analysis(report_id="RefRefRefRefRefR", start_time=_ms(start), healer_healing=9_000_000),
            source="reference",
        )
    service = HealingService(storage, now=lambda: datetime(2026, 9, 27, 12, 0))
    result = service.weekly(weeks=3)
    assert [w.raids for w in result.weeks] == [0, 0, 1]
    assert result.weeks[-1].healing == 800_000


def test_service_from_context_uses_the_context_storage(tmp_path, build_analysis):
    db = str(tmp_path / "ctx.db")
    with PerformanceDB(db) as repo:
        repo.import_raid(build_analysis(report_id="GuildGuildGuildG", start_time=_ms(datetime.now())))
    result = HealingService.from_context(AppContext(config={}, db_path=db)).weekly()
    assert result.raids == 1


def test_service_raises_storage_errors():
    def broken():
        raise StorageError("database is locked")

    with pytest.raises(StorageError):
        HealingService(broken).weekly()
