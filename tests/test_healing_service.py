"""Week-on-week healing (``wcl_app.healing``): the numbers, the charts built from them, and the service over storage.

The service tests run on SQLite and on Postgres; the Postgres half is skipped without
``WCL_STORE_TEST_DATABASE_URL``, as in ``test_store_contract.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from wcl_app import AppContext, HealingService
from wcl_app.charts import MAX_SERIES
from wcl_app.healing import MAX_WEEKS, MIN_WEEKS, week_start, weekly_healing
from wcl_store import StorageError
from wcl_store.sqlite import PerformanceDB

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
TODAY = date(2026, 9, 27)  # a Sunday; its week starts Mon 21 Sep


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _raids(*raids):
    """(report_id, "YYYY-MM-DD", {healer: healing}) -> ``get_healing_by_raid`` rows; overheal is a quarter."""
    return [
        {
            "report_id": report_id,
            "raid_date": f"{day} 20:00:00",
            "name": name,
            "player_class": "Priest",
            "healing": amount,
            "overhealing": amount // 4,
        }
        for report_id, day, healing in raids
        for name, amount in healing.items()
    ]


def test_weeks_run_monday_to_sunday():
    assert week_start(date(2026, 9, 21)) == date(2026, 9, 21)
    assert week_start(TODAY) == date(2026, 9, 21)


def test_every_week_in_the_window_is_listed_oldest_first_raided_or_not():
    result = weekly_healing([], TODAY, weeks=4)
    assert [w.start for w in result.weeks] == [
        date(2026, 8, 31),
        date(2026, 9, 7),
        date(2026, 9, 14),
        date(2026, 9, 21),
    ]
    assert result.raids == 0 and not result.healers


@pytest.mark.parametrize(("asked", "weeks"), [(0, MIN_WEEKS), (1, MIN_WEEKS), (8, 8), (500, MAX_WEEKS)])
def test_the_window_is_clamped(asked, weeks):
    assert len(weekly_healing([], TODAY, weeks=asked).weeks) == weeks


def test_numbers_are_per_raid_so_a_two_raid_week_compares_fairly():
    rows = _raids(
        ("KaraA", "2026-09-08", {"Holy": 400_000, "Resto": 200_000}),
        ("KaraB", "2026-09-10", {"Holy": 600_000}),
        ("Gruul", "2026-09-22", {"Holy": 900_000, "Resto": 300_000}),
    )
    result = weekly_healing(rows, TODAY, weeks=3)
    first, skipped, last = result.weeks
    assert (first.raids, first.healing, first.per_raid, first.healers) == (2, 1_200_000, 600_000, 2)
    # Three healers healed across the two raids (Holy twice, Resto once): 1.2M over 3 is 400K per character.
    assert (first.appearances, first.per_character) == (3, 400_000)
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
        "healing_per_character": 400_000,
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


def test_rows_outside_the_window_or_undated_are_left_out():
    rows = _raids(("Old", "2026-01-05", {"Holy": 1}), ("Kara", "2026-09-22", {"Holy": 10}))
    rows += _raids(("Ahead", "2026-10-05", {"Holy": 7}))  # next week: an uploader with a wrong clock
    rows.append({**rows[0], "report_id": "Bad", "raid_date": "nope"})
    result = weekly_healing(rows, TODAY, weeks=2)
    assert result.raids == 1 and result.weeks[-1].healing == 10


def test_a_healer_is_matched_across_raids_ignoring_case():
    rows = _raids(("A", "2026-09-15", {"Holy": 100}), ("B", "2026-09-22", {"HOLY": 300}))
    result = weekly_healing(rows, TODAY, weeks=2)
    assert len(result.healers) == 1 and result.healers[0].per_raid() == [100, 300]


class TestCharts:
    def test_raid_chart(self):
        rows = _raids(("A", "2026-09-15", {"Holy": 1_000_000}), ("B", "2026-09-22", {"Holy": 1_100_000}))
        chart = weekly_healing(rows, TODAY, weeks=4).raid_chart()
        assert chart.kind == "bar" and chart.id == "healing_weekly"
        assert chart.categories == ["31 Aug", "7 Sep", "14 Sep", "21 Sep"]
        assert chart.series[0].values == [None, None, 1_000_000, 1_100_000]
        assert chart.series[0].display == ["-", "-", "1.0M", "1.1M"]
        assert chart.series[0].emphasis
        assert chart.y_max == 2_000_000
        assert chart.notes == [
            "Per raid 1.1M: up, 10.0% above its 4-week average of 1.0M.",
            "Per character 1.1M: up, 10.0% above its 4-week average of 1.0M.",
            "Week of 21 Sep: +10.0% on the week before it raided.",
            "Overheal that week: 20.0%.",
        ]
        assert [(r.key, r.label, r.value, r.display) for r in chart.references] == [
            ("baseline", "4-week average", 1_000_000, "1.0M")
        ]

    def test_raid_chart_with_one_raided_week_has_no_change_note(self):
        rows = _raids(("A", "2026-09-22", {"Holy": 100}))
        assert weekly_healing(rows, TODAY, weeks=2).raid_chart().notes == ["Overheal that week: 20.0%."]

    def test_empty_charts_say_why(self):
        result = weekly_healing([], TODAY, weeks=6)
        assert result.raid_chart().empty == "No guild raids in the last 6 weeks."
        assert result.healer_chart().empty == "No healers in guild raids in the last 6 weeks."
        assert result.healer_chart().series == []

    def test_healer_chart_draws_only_the_top_healers_and_says_so(self):
        healing = {f"Healer{i:02d}": 1_000 * (i + 1) for i in range(MAX_SERIES + 3)}
        rows = _raids(("A", "2026-09-22", healing))
        chart = weekly_healing(rows, TODAY, weeks=2).healer_chart()
        assert chart.kind == "line"
        assert len(chart.series) == MAX_SERIES
        average, first = chart.series[:2]
        assert (average.key, average.name, average.emphasis) == ("guild_average", "Average per character", True)
        assert first.name == "Healer10" and first.key == "healer10" and not first.emphasis
        assert chart.notes == [
            f"Showing the {MAX_SERIES - 1} healers with the most healing per raid; 4 more not drawn."
        ]

    def test_healer_chart_leads_with_the_average_per_character(self):
        rows = _raids(("A", "2026-09-15", {"Holy": 300, "Resto": 100}), ("B", "2026-09-22", {"Holy": 600}))
        chart = weekly_healing(rows, TODAY, weeks=2).healer_chart()
        assert [(s.name, s.values) for s in chart.series] == [
            ("Average per character", [200, 600]),
            ("Holy", [300, 600]),
            ("Resto", [100, None]),
        ]

    def test_healer_chart_measures_the_average_per_character_on_its_own(self):
        rows = _raids(("A", "2026-09-15", {"Holy": 300, "Resto": 100}), ("B", "2026-09-22", {"Holy": 600}))
        chart = weekly_healing(rows, TODAY, weeks=2).healer_chart()
        assert [(r.key, r.label, r.value) for r in chart.references] == [("character_baseline", "4-week average", 200)]
        assert chart.notes == ["Per character 600: up, 200.0% above its 4-week average of 200."]

    def test_a_healer_named_average_does_not_clash_with_the_guild_line(self):
        rows = _raids(("A", "2026-09-22", {"Average": 300, "Holy": 100}))
        chart = weekly_healing(rows, TODAY, weeks=2).healer_chart()
        assert [s.key for s in chart.series] == ["guild_average", "average", "holy"]

    @pytest.mark.parametrize("top", [0, -1])
    def test_no_room_for_lines_draws_nothing_and_counts_no_healers(self, top):
        rows = _raids(("A", "2026-09-22", {"Holy": 3, "Resto": 2}))
        chart = weekly_healing(rows, TODAY, weeks=2).healer_chart(top=top)
        assert chart.series == [] and chart.references == [] and chart.empty == "No lines to draw."
        assert chart.notes == ["Showing the 0 healers with the most healing per raid; 2 more not drawn."]

    def test_top_limit_is_honoured(self):
        rows = _raids(("A", "2026-09-22", {"Holy": 3, "Resto": 2, "Disc": 1}))
        chart = weekly_healing(rows, TODAY, weeks=2).healer_chart(top=3)
        assert [s.name for s in chart.series] == ["Average per character", "Holy", "Resto"]


class TestStandard:
    def _weekly(self, per_week):
        """One raid a week ending this week, healing per week as given, oldest first."""
        mondays = [date(2026, 9, 21) - timedelta(weeks=n) for n in range(len(per_week) - 1, -1, -1)]
        raids = [
            (f"R{i}", str(m + timedelta(days=1)), {"Holy": v})
            for i, (m, v) in enumerate(zip(mondays, per_week, strict=True))
            if v
        ]
        rows = _raids(*raids)
        return weekly_healing(rows, TODAY, weeks=len(per_week))

    def test_nothing_raided_has_no_standard(self):
        result = weekly_healing([], TODAY, weeks=3)
        assert result.standard() is None and result.to_dict()["standard"] is None

    def test_a_first_raid_is_new_with_no_baseline(self):
        standard = self._weekly([0, 1_000]).standard()
        assert standard.baseline is None and standard.trend == "new" and standard.notes() == []

    def test_baseline_averages_the_raided_weeks_before_the_latest_only(self):
        # Six raided weeks and one skipped: the baseline is the 4 raided weeks before the latest (200..500).
        standard = self._weekly([100, 200, 300, 0, 400, 500, 350]).standard()
        assert standard.week == date(2026, 9, 21)
        assert standard.baseline == 350
        assert standard.trend == "steady" and standard.vs_baseline_percent == 0.0

    @pytest.mark.parametrize(("latest", "trend"), [(1_030, "up"), (1_020, "steady"), (980, "steady"), (970, "down")])
    def test_trend_is_steady_within_two_percent(self, latest, trend):
        assert self._weekly([1_000, latest]).standard().trend == trend

    def test_the_standard_is_the_guilds_own_average_per_raid_and_per_character(self):
        # Two healers in every raid but the last, where one heals alone: per raid falls 10% on the four weeks
        # before it, while the average per character rises 80%.
        mondays = [date(2026, 9, 21) - timedelta(weeks=n) for n in range(4, -1, -1)]
        raids = [(f"R{i}", str(m + timedelta(days=1)), {"Holy": 600, "Resto": 400}) for i, m in enumerate(mondays[:-1])]
        raids.append(("Last", str(mondays[-1] + timedelta(days=1)), {"Holy": 900}))
        result = weekly_healing(_raids(*raids), TODAY, weeks=5)
        standard = result.standard()
        assert (standard.trend, standard.character_trend) == ("down", "up")
        assert standard.notes() == [
            "Per raid 900: down, 10.0% below its 4-week average of 1.0K.",
            "Per character 900: up, 80.0% above its 4-week average of 500.",
        ]
        assert result.to_dict()["standard"] == {
            "week": "2026-09-21",
            "healing_per_raid": 900,
            "baseline": 1_000,
            "vs_baseline_percent": -10.0,
            "trend": "down",
            "healing_per_character": 900,
            "character_baseline": 500,
            "character_vs_baseline_percent": 80.0,
            "character_trend": "up",
            "raided_weeks": 5,
        }

    def test_the_raid_chart_has_no_target_line(self):
        chart = self._weekly([1_000, 1_100]).raid_chart()
        assert [r.key for r in chart.references] == ["baseline"]


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
    assert result.standard().healing_per_character == 800_000
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
