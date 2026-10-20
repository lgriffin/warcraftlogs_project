"""Character pages (wcl_app.character_pages): one character's raids, lineage, bests and charts as a JSON payload,
built from storage alone, on both storage backends."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pytest
from wcl_app import CharacterPage, CharacterPageService
from wcl_app.character_pages import CHARACTER_PAGE_VERSION, MAX_RAIDS
from wcl_app.charts import Chart
from wcl_store import RaidScope, StorageError
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client.models import DPSPerformance, HealerPerformance, PlayerIdentity

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    if request.param == "sqlite":
        path = str(tmp_path / f"characters-{uuid.uuid4().hex[:8]}.db")
        return lambda: PerformanceDB(path)
    engine = request.getfixturevalue("pg_empty_engine")
    from wcl_store.postgres import PostgresRaidRepository

    return lambda: PostgresRaidRepository(engine)


def _raid(build_analysis, report_id: str, start: datetime, healing: int, *, mage_damage: int = 600_000):
    """HolyPriest heals ``healing`` beside a second healer on 300k; StabbyRogue (melee) and BoomMage (ranged)."""
    s = _ms(start)
    analysis = build_analysis(report_id=report_id, start_time=s, end_time=s + 7_200_000, healer_healing=healing)
    analysis.healers.append(HealerPerformance("ShamanHeals", "Shaman", 5, total_healing=300_000))
    analysis.composition.healers.append(PlayerIdentity("ShamanHeals", "Shaman", 5, "healer"))
    analysis.dps.append(DPSPerformance("BoomMage", "Mage", 4, "ranged", total_damage=mage_damage))
    analysis.composition.ranged.append(PlayerIdentity("BoomMage", "Mage", 4, "ranged"))
    return analysis


@pytest.fixture
def pages(storage, build_analysis):
    """HolyPriest healed 500k on 14 Oct (a Wednesday) and 700k on 18 Oct (a Sunday)."""
    with storage() as repo:
        repo.import_raid(_raid(build_analysis, "WednesdayRaidAAA", datetime(2026, 10, 14, 20, 0), 500_000))
        repo.import_raid(_raid(build_analysis, "SundayRaidBBBBBB", datetime(2026, 10, 18, 20, 0), 700_000))
    return CharacterPageService(storage)


def test_a_page_lists_the_raids_newest_first_against_the_raid_median(pages):
    page = pages.page("holypriest")
    assert isinstance(page, CharacterPage)
    assert (page.name, page.player_class, page.raids, page.role_counts) == ("HolyPriest", "Priest", 2, {"healer": 2})
    sunday, wednesday = page.recent
    assert (sunday.report_id, sunday.weekday, sunday.role, sunday.metric) == (
        "SundayRaidBBBBBB",
        6,
        "healer",
        "Healing",
    )
    assert (sunday.value, sunday.display, sunday.median, sunday.rank, sunday.of) == (700_000, "700.0K", 500_000, 1, 2)
    assert (wednesday.weekday, wednesday.value, wednesday.median, wednesday.rank) == (2, 500_000, 400_000, 1)
    assert sunday.percent is not None


def test_a_page_carries_lineage_bests_and_a_chart_per_role(pages):
    page = pages.page("HolyPriest")
    assert page is not None
    healing = next(m for m in page.metrics if m["name"] == "Healing")
    assert (healing["min"], healing["max"], healing["raids"]) == (500_000, 700_000, 2)
    assert [c["name"] for c in page.casts] == ["Greater Heal"]
    assert [(b.metric, b.value, b.report_id) for b in page.bests] == [("Healing", 700_000, "SundayRaidBBBBBB")]
    (chart,) = page.charts
    assert chart.id == "character_healer" and chart.categories == ["14/10", "18/10"]
    assert [s.values for s in chart.series] == [[500_000, 700_000], [400_000, 500_000]]


def test_the_payload_is_json_and_its_charts_read_back(pages):
    out = pages.page("BoomMage").to_dict()
    text = json.dumps(out)
    assert out["version"] == CHARACTER_PAGE_VERSION
    assert out["recent"][0]["role"] == "ranged" and out["recent"][0]["rank"] == 1
    assert Chart.from_dict(json.loads(text)["charts"][0]).id == "character_ranged"


def test_a_tank_has_a_median_but_no_rank_and_no_best(pages):
    page = pages.page("TankWarrior")
    assert page is not None
    raid = page.recent[0]
    assert (raid.role, raid.metric, raid.median, raid.rank, raid.of) == ("tank", "Damage taken", 800_000, 0, 0)
    assert page.bests == []


def test_no_page_for_a_character_with_no_raid_or_outside_the_scope(storage, pages):
    assert pages.page("Nobody") is None
    assert CharacterPageService(storage, scope=RaidScope(weekdays=(6,))).page("HolyPriest").raids == 1
    assert CharacterPageService(storage, scope=RaidScope(weekdays=(0,))).page("HolyPriest") is None


class _Counting:
    """A storage factory that counts raid analysis reads and fails the first ``failures`` of them."""

    def __init__(self, storage, failures: int = 0):
        self.storage, self.failures, self.reads = storage, failures, 0

    def __call__(self):
        outer = self
        repo = self.storage()

        class Repo:
            def __enter__(self):
                self.db = repo.__enter__()
                return self

            def __exit__(self, *exc):
                return repo.__exit__(*exc)

            def __getattr__(self, name):
                return getattr(self.db, name)

            def get_raid_analysis(self, report_id):
                outer.reads += 1
                if outer.failures:
                    outer.failures -= 1
                    raise StorageError("down")
                return self.db.get_raid_analysis(report_id)

        return Repo()


def test_each_raid_is_read_once_for_a_roster(storage, build_analysis):
    with storage() as repo:
        repo.import_raid(_raid(build_analysis, "OnlyRaidCCCCCCCC", datetime(2026, 10, 14, 20, 0), 500_000))
    counting = _Counting(storage)
    pages = CharacterPageService(counting).pages(["HolyPriest", "BoomMage", "StabbyRogue", "Nobody"])
    assert [p.name if p else None for p in pages] == ["HolyPriest", "BoomMage", "StabbyRogue", None]
    assert counting.reads == 1


def test_a_reanalysed_raid_shows_its_new_median(storage, build_analysis):
    start = datetime(2026, 10, 14, 20, 0)
    with storage() as repo:
        repo.import_raid(_raid(build_analysis, "OnlyRaidCCCCCCCC", start, 500_000))
    service = CharacterPageService(storage)
    assert service.page("HolyPriest").recent[0].median == 400_000
    with storage() as repo:
        repo.import_raid(_raid(build_analysis, "OnlyRaidCCCCCCCC", start, 900_000))
    assert service.page("HolyPriest").recent[0].median == 600_000


def test_a_failed_analysis_read_is_tried_again(storage, build_analysis):
    with storage() as repo:
        repo.import_raid(_raid(build_analysis, "OnlyRaidCCCCCCCC", datetime(2026, 10, 14, 20, 0), 500_000))
    service = CharacterPageService(_Counting(storage, failures=1))
    assert service.page("HolyPriest").recent[0].median is None
    assert service.page("HolyPriest").recent[0].median == 400_000


def test_pages_read_guild_raids_whatever_sources_the_scope_names(pages, storage):
    scoped = CharacterPageService(storage, scope=RaidScope(sources=("reference",)))
    page = scoped.page("HolyPriest")
    assert page is not None and page.raids == len(page.recent) == 2


def test_recent_raids_are_capped(storage, build_analysis):
    with storage() as repo:
        for i in range(MAX_RAIDS + 2):
            start = datetime(2026, 1, 1, 20, 0).replace(day=1 + i % 28, month=1 + i // 28)
            repo.import_raid(_raid(build_analysis, f"Raid{i:012d}", start, 400_000 + i))
    page = CharacterPageService(storage).page("HolyPriest")
    assert page is not None and page.raids == MAX_RAIDS + 2 and len(page.recent) == MAX_RAIDS
    assert page.recent[0].value == 400_000 + MAX_RAIDS + 1
    assert len(page.charts[0].categories) == 20
