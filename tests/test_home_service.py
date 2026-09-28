"""The home page service: widget catalogue, saved layout and widget payloads.

Payloads are built from ``RaidRepository`` only, so every test runs on SQLite and on Postgres (the Toads Hub's
backend); the Postgres half is skipped without ``WCL_STORE_TEST_DATABASE_URL``, as in ``test_store_contract.py``.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime

import pytest
from wcl_app import AppContext, BadgeRules, HomeLayout, HomeService, JsonLayoutStore
from wcl_app.home import CATALOGUE, MemoryLayoutStore, compact
from wcl_store import StorageError
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client.models import (
    ConsumableUsage,
    DPSPerformance,
    EncounterSummary,
    InterruptUsage,
    PlayerIdentity,
)

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
KARA = "KaraKaraKaraKara"
GRUUL = "GruulGruulGruulG"
NOW = datetime(2026, 9, 27, 12, 0)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    """A storage factory, as ``AppContext.repository`` or a headless host passes it."""
    if request.param == "sqlite":
        path = str(tmp_path / f"home-{uuid.uuid4().hex[:8]}.db")
        return lambda: PerformanceDB(path)
    engine = request.getfixturevalue("pg_empty_engine")
    from wcl_store.postgres import PostgresRaidRepository

    return lambda: PostgresRaidRepository(engine)


@pytest.fixture
def service(storage):
    return HomeService(storage, now=lambda: NOW)


@pytest.fixture
def two_raids(storage, build_analysis):
    """Karazhan on Mon 14 Sep and Gruul on Mon 21 Sep 2026; Gruul is the last raid."""
    kara_start = datetime(2026, 9, 14, 20, 0)
    kara = build_analysis(
        report_id=KARA,
        title="Karazhan",
        start_time=_ms(kara_start),
        end_time=_ms(kara_start) + 3_600_000,
    )
    gruul_start = datetime(2026, 9, 21, 20, 0)
    gruul = build_analysis(
        report_id=GRUUL,
        title="Gruul's Lair",
        start_time=_ms(gruul_start),
        end_time=_ms(gruul_start) + 5_430_000,
        tank_name="TankPaladin",
        tank_class="Paladin",
        dps_name="FrostMage",
        dps_class="Mage",
        dps_role="ranged",
        dps_damage=900_000,
        healer_healing=1_200_000,
        healer_overhealing=300_000,
        consumables=[
            ConsumableUsage("HolyPriest", "healer", GRUUL, "Super Mana Potion", 3),
            ConsumableUsage("FrostMage", "ranged", GRUUL, "Flask of Supreme Power", 1),
            ConsumableUsage("FrostMage", "ranged", GRUUL, "Destruction Potion", 1),
        ],
        encounters=[
            EncounterSummary(1, "Gruul the Dragonkiller", _ms(gruul_start) + 900_000, 0, 245_000),
            EncounterSummary(2, "High King Maulgar", _ms(gruul_start) + 60_000, 0, 180_000),
        ],
    )
    gruul.dps.append(DPSPerformance("StabbyRogue", "Rogue", 3, "melee", total_damage=300_000))
    gruul.composition.melee.append(PlayerIdentity("StabbyRogue", "Rogue", 3, "melee"))
    gruul.interrupts = [
        InterruptUsage("StabbyRogue", "Rogue", 3, 1766, "Kick", 4),
        InterruptUsage("FrostMage", "Mage", 4, 2139, "Counterspell", 2),
        InterruptUsage("StabbyRogue", "Rogue", 3, 408, "Kidney Shot", 1),
    ]
    with storage() as repo:
        repo.import_raid(kara)
        repo.import_raid(gruul)
        repo.get_or_create_player_page("FrostMage", "Pyrewood Village", "eu")


def _widget(service, widget_id):
    return service.widget(widget_id)


def _tiles(widget):
    return {t.label: t for t in widget.tiles}


# ── Catalogue and layout ──


def test_catalogue_ids_are_unique_and_every_widget_builds_on_an_empty_database(service):
    ids = [s.id for s in CATALOGUE]
    assert len(ids) == len(set(ids))
    page = service.page(HomeLayout.of(ids))
    assert [w.id for w in page.widgets] == ids
    assert all(not w.error for w in page.widgets)
    assert _widget(service, "last_raid").empty
    assert _widget(service, "tracked_players").empty
    assert _widget(service, "badges").empty == "No raids stored yet."


def test_default_layout_is_the_default_widgets_in_catalogue_order(service):
    assert service.layout() == HomeLayout.default()
    assert HomeLayout.default().widgets == tuple(s.id for s in CATALOGUE if s.default)
    assert "quick_actions" in HomeLayout.default().widgets
    assert set(HomeLayout.default().hidden()) == {s.id for s in CATALOGUE if not s.default}


def test_saved_layout_keeps_order_and_drops_unknown_ids_and_repeats(storage):
    store = MemoryLayoutStore()
    service = HomeService(storage, store)
    layout = service.save_layout(["attendance", "nope", "last_raid", "attendance"])
    assert layout.widgets == ("attendance", "last_raid")
    assert service.layout() == layout
    assert [w.id for w in service.page().widgets] == ["attendance", "last_raid"]
    assert service.reset_layout() == HomeLayout.default()
    assert store.layout is None and service.layout() == HomeLayout.default()


def test_an_empty_layout_is_a_valid_choice(storage):
    service = HomeService(storage, MemoryLayoutStore())
    service.save_layout([])
    assert service.layout().widgets == ()
    assert service.page().widgets == []


@pytest.mark.parametrize("stored", [None, [], "x", {"widgets": "attendance"}, {"version": 1}])
def test_malformed_stored_layout_falls_back_to_the_default(stored):
    assert HomeLayout.from_dict(stored) == HomeLayout.default()


def test_json_layout_store_round_trips_and_forgets(tmp_path):
    path = tmp_path / "nested" / "home_layout.json"
    store = JsonLayoutStore(path)
    assert store.load() is None
    store.save(HomeLayout.of(["recent_raids", "quick_actions"]))
    assert json.loads(path.read_text()) == {"version": 1, "widgets": ["recent_raids", "quick_actions"]}
    assert store.load() == HomeLayout(("recent_raids", "quick_actions"))
    store.save(None)
    assert not path.exists() and store.load() is None


def test_json_layout_store_treats_a_corrupt_file_as_unsaved(tmp_path):
    path = tmp_path / "home_layout.json"
    path.write_text("{not json")
    assert JsonLayoutStore(path).load() is None


def test_from_context_reads_the_context_storage(tmp_path, build_analysis):
    ctx = AppContext(config={}, db_path=str(tmp_path / "ctx.db"))
    with ctx.repository() as repo:
        repo.import_raid(build_analysis(report_id=KARA))
    items = HomeService.from_context(ctx).widget("recent_raids").items
    assert [i.link.params for i in items] == [{"report_id": KARA}]


# ── Widget data ──


@pytest.mark.usefixtures("two_raids")
class TestWidgets:
    def test_guild_snapshot(self, service):
        tiles = _tiles(_widget(service, "guild_snapshot"))
        assert tiles["Raids stored"].value == 2
        assert tiles["Active raiders"].value == 5  # HolyPriest, TankWarrior, StabbyRogue, TankPaladin, FrostMage
        assert tiles["Raids in 30 days"].value == 2
        assert tiles["Last raid"].value == "2026-09-21" and tiles["Last raid"].display == "Sep 21"
        assert tiles["Days since last raid"].value == 6

    def test_last_raid(self, service):
        w = _widget(service, "last_raid")
        assert w.subtitle == "Gruul's Lair"
        assert w.link.kind == "raid" and w.link.params == {"report_id": GRUUL}
        tiles = _tiles(w)
        assert tiles["Date"].display == "Mon 21 Sep 2026"
        assert tiles["Duration"].display == "1h 30m"
        assert tiles["Bosses killed"].value == 2
        assert tiles["Raid size"].value == 4
        assert tiles["Total damage"].value == 1_200_000 and tiles["Total damage"].display == "1.2M"
        assert tiles["Total healing"].value == 1_200_000

    def test_recent_raids_are_newest_first_and_link_to_the_raid(self, service):
        items = _widget(service, "recent_raids").items
        assert [i.label for i in items] == ["Gruul's Lair", "Karazhan"]
        assert items[0].detail == "Mon 21 Sep 2026"
        assert items[1].link.params == {"report_id": KARA}

    def test_raid_activity_counts_raids_per_week_ending_this_week(self, service):
        bars = _widget(service, "raid_activity").bars
        assert len(bars) == 8
        assert bars[-1].label == "21 Sep" and bars[-1].value == 1  # the week of Mon 21 Sep holds NOW
        assert bars[-2].label == "14 Sep" and bars[-2].value == 1
        assert sum(b.value for b in bars) == 2

    def test_top_damage_ranks_the_last_raid_with_share(self, service):
        w = _widget(service, "top_damage")
        assert [c.key for c in w.columns] == ["rank", "name", "class", "damage", "share"]
        assert [r.values["name"] for r in w.rows] == ["FrostMage", "StabbyRogue"]
        assert w.rows[0].values["share"] == 75.0 and w.rows[0].cells["share"] == "75.0%"
        assert w.rows[0].cells["damage"] == "900.0K"
        assert w.rows[0].link.kind == "character" and w.rows[0].link.params == {"name": "FrostMage"}

    def test_top_healing(self, service):
        row = _widget(service, "top_healing").rows[0]
        assert row.values["name"] == "HolyPriest" and row.values["healing"] == 1_200_000
        assert row.cells["overheal"] == "20.0%"

    def test_attendance_over_the_recent_raids(self, service):
        w = _widget(service, "attendance")
        assert w.subtitle == "Last 2 raids"
        by_name = {r.values["name"]: r for r in w.rows}
        assert by_name["HolyPriest"].cells["raids"] == "2/2" and by_name["HolyPriest"].values["attendance"] == 100
        assert by_name["FrostMage"].values["raids"] == 1 and by_name["FrostMage"].cells["attendance"] == "50%"
        assert [r.values["name"] for r in w.rows][:2] == ["HolyPriest", "StabbyRogue"]

    def test_boss_kills_in_kill_order(self, service):
        w = _widget(service, "boss_kills")
        assert [r.values["boss"] for r in w.rows] == ["High King Maulgar", "Gruul the Dragonkiller"]
        assert w.rows[1].cells["duration"] == "4m 05s"

    def test_class_mix(self, service):
        bars = _widget(service, "class_mix").bars
        assert sorted((b.label, b.value) for b in bars) == [("Mage", 1), ("Paladin", 1), ("Priest", 1), ("Rogue", 1)]

    def test_interrupts_sum_every_spell(self, service):
        rows = _widget(service, "interrupts").rows
        assert [(r.values["name"], r.values["interrupts"]) for r in rows] == [("StabbyRogue", 5), ("FrostMage", 2)]

    def test_consumables(self, service):
        rows = _widget(service, "consumables").rows
        assert [(r.values["name"], r.values["used"]) for r in rows] == [("HolyPriest", 3), ("FrostMage", 2)]
        assert rows[0].cells["role"] == "Healer"

    def test_badges_of_the_last_raids_roster(self, storage):
        rules = BadgeRules.from_config(
            {"badges": {"thresholds": {"attendance": [2], "mana_potions": [3, 10], "combat_potions": [1]}}}
        )
        w = HomeService(storage, now=lambda: NOW, badge_rules=rules).widget("badges")
        assert w.subtitle == "Gruul's Lair"
        # TankPaladin came once and used nothing; TankWarrior was not in the last raid.
        assert [(h.name, h.player_class, [b.id for b in h.badges]) for h in w.holders] == [
            ("HolyPriest", "Priest", ["attendance", "mana_potions"]),
            ("FrostMage", "Mage", ["combat_potions"]),
            ("StabbyRogue", "Rogue", ["attendance"]),
        ]
        assert w.holders[0].link.params == {"name": "HolyPriest"}
        mana = w.holders[0].badges[1]
        assert (mana.quality, mana.value, mana.next_at) == ("uncommon", 3, 10)

    def test_badges_with_nobody_qualifying(self, service):
        w = _widget(service, "badges")
        assert w.holders == [] and w.empty == "Nobody in the last raid has a badge yet."

    def test_badge_thresholds_come_from_the_context_config(self, tmp_path, build_analysis):
        ctx = AppContext(config={"badges": {"thresholds": {"attendance": [1]}}}, db_path=str(tmp_path / "ctx.db"))
        with ctx.repository() as repo:
            repo.import_raid(build_analysis(report_id=KARA))
        holders = HomeService.from_context(ctx).widget("badges").holders
        assert [h.name for h in holders] == ["HolyPriest", "StabbyRogue", "TankWarrior"]

    def test_tracked_players_link_to_the_player_page(self, service):
        row = _widget(service, "tracked_players").rows[0]
        assert row.cells["region"] == "EU"
        assert row.link.kind == "player_page"
        assert row.link.params == {"name": "FrostMage", "server": "Pyrewood Village", "region": "eu"}

    def test_page_serialises_to_the_documented_json(self, service):
        data = json.loads(json.dumps(service.page(HomeLayout.of(s.id for s in CATALOGUE)).to_dict()))
        assert data["version"] == 1 and data["generated_at"] == "2026-09-27 12:00:00"
        kind_fields = {"stats": {"tiles"}, "table": {"columns", "rows"}, "list": {"items"}, "bars": {"bars"}}
        kind_fields["actions"] = {"actions"}
        kind_fields["badges"] = {"holders"}
        common = {"id", "title", "kind", "size", "subtitle", "link", "empty", "error"}
        for w in data["widgets"]:
            assert set(w) == common | kind_fields[w["kind"]], w["id"]
        badges = next(w for w in data["widgets"] if w["id"] == "badges")
        assert badges["holders"] == [] and badges["empty"]
        top = next(w for w in data["widgets"] if w["id"] == "top_damage")
        assert top["rows"][0]["link"] == {"kind": "character", "params": {"name": "FrostMage"}}


# ── Failures ──


def test_unavailable_storage_marks_every_widget_instead_of_raising():
    def broken():
        raise StorageError("database is locked")

    page = HomeService(broken, now=lambda: NOW).page(HomeLayout.of(["guild_snapshot", "recent_raids"]))
    assert [w.id for w in page.widgets] == ["guild_snapshot", "recent_raids"]
    assert all("database is locked" in w.error for w in page.widgets)


def test_one_failing_widget_does_not_blank_the_others(tmp_path):
    class FlakyPages(PerformanceDB):
        def find_player_pages(self, name=None):
            raise StorageError("player pages unavailable")

    path = str(tmp_path / "flaky.db")

    @contextmanager
    def storage():
        with FlakyPages(path) as db:
            yield db

    page = HomeService(storage).page(HomeLayout.of(["tracked_players", "quick_actions"]))
    assert page.widgets[0].error == "player pages unavailable"
    assert not page.widgets[1].error and page.widgets[1].actions


def test_undecodable_stored_data_marks_only_that_widget(tmp_path, build_analysis):
    class BadAnalysis(PerformanceDB):
        def get_raid_analysis(self, report_id):
            raise ValueError("Expecting value: line 1 column 1")

    path = str(tmp_path / "bad.db")
    with PerformanceDB(path) as db:
        db.import_raid(build_analysis(report_id=KARA))

    page = HomeService(lambda: BadAnalysis(path)).page(HomeLayout.of(["last_raid", "recent_raids"]))
    assert "Expecting value" in page.widgets[0].error
    assert not page.widgets[1].error and page.widgets[1].items


def test_future_dated_raids_are_not_counted_as_recent(storage, build_analysis):
    ahead = datetime(2026, 10, 3, 20, 0)  # after NOW, e.g. an uploader with a wrong clock
    with storage() as repo:
        repo.import_raid(build_analysis(report_id=KARA, start_time=_ms(ahead), end_time=_ms(ahead) + 60_000))
    tiles = _tiles(HomeService(storage, now=lambda: NOW).widget("guild_snapshot"))
    assert tiles["Raids stored"].value == 1
    assert tiles["Raids in 30 days"].value == 0


def test_raids_stored_counts_every_guild_raid_not_just_the_ones_read(storage, build_analysis, monkeypatch):
    monkeypatch.setattr("wcl_app.home._RECENT_RAIDS_READ", 1)
    with storage() as repo:
        repo.import_raid(build_analysis(report_id=KARA, start_time=_ms(datetime(2026, 9, 14, 20))))
        repo.import_raid(build_analysis(report_id=GRUUL, start_time=_ms(datetime(2026, 9, 21, 20))))
        repo.import_raid(build_analysis(report_id="RefRefRefRefRefR"), source="reference")
    tiles = _tiles(HomeService(storage, now=lambda: NOW).widget("guild_snapshot"))
    assert tiles["Raids stored"].value == 2


def test_unknown_widget_id_raises_key_error(service):
    with pytest.raises(KeyError):
        service.widget("nope")


@pytest.mark.parametrize(
    ("n", "text"), [(0, "0"), (950, "950"), (4_500, "4.5K"), (12_345_678, "12.3M"), (2_000_000_000, "2.0B")]
)
def test_compact_numbers(n, text):
    assert compact(n) == text
