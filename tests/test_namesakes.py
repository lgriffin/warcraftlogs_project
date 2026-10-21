"""Namesakes: two characters who shared a name (a classic priest, then the TBC shaman who took the name) stay apart.

Storage keys characters by name, so each raid records the class played in it. The character page and the lineage
cover only the raids of the newest raid's class, and ``RaidService.backfill_classes`` reads the classes of raids
stored before they were recorded from each report's player list.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
import requests
from wcl_app import CharacterPageService, character_lineage
from wcl_core.testing import FakeWarcraftLogs
from wcl_store.sqlite import PerformanceDB

from warcraftlogs_client import cli
from warcraftlogs_client.models import SpellUsage
from warcraftlogs_client.services import AppContext, RaidService

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]
CLASSIC, TBC, LEGACY = "ClassicPriestAAAA", "TbcShamanBBBBBBB", "LegacyRaidCCCCCC"


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    if request.param == "sqlite":
        path = str(tmp_path / f"namesakes-{uuid.uuid4().hex[:8]}.db")
        return lambda: PerformanceDB(path)
    engine = request.getfixturevalue("pg_empty_engine")
    from wcl_store.postgres import PostgresRaidRepository

    return lambda: PostgresRaidRepository(engine)


def _hadur(build_analysis, code: str, start: datetime, player_class: str, spell: str, healing: int):
    """A raid with Hadur healing as ``player_class``, casting only ``spell``."""
    ms = int(start.timestamp() * 1000)
    analysis = build_analysis(
        report_id=code,
        start_time=ms,
        end_time=ms + 7_200_000,
        healer_name="Hadur",
        healer_class=player_class,
        healer_healing=healing,
    )
    analysis.healers[0].spells = [SpellUsage(1, spell, 40, healing)]
    return analysis


@pytest.fixture
def namesakes(storage, build_analysis):
    with storage() as repo:
        repo.import_raid(_hadur(build_analysis, CLASSIC, datetime(2026, 9, 2, 20, 0), "Priest", "Flash Heal", 900_000))
        repo.import_raid(_hadur(build_analysis, TBC, datetime(2026, 10, 14, 20, 0), "Shaman", "Chain Heal", 500_000))
    return storage


def test_the_page_is_the_newest_class_alone(namesakes):
    page = CharacterPageService(namesakes).page("hadur")
    assert page is not None
    assert (page.player_class, page.raids, [r.report_id for r in page.recent]) == ("Shaman", 1, [TBC])
    assert [c["name"] for c in page.casts] == ["Chain Heal"]
    assert [(b.value, b.report_id) for b in page.bests] == [(500_000, TBC)]
    healing = next(m for m in page.metrics if m["name"] == "Healing")
    assert (healing["min"], healing["max"]) == (500_000, 500_000)


def test_an_older_raid_imported_later_does_not_change_the_class(namesakes, build_analysis):
    with namesakes() as repo:
        repo.import_raid(_hadur(build_analysis, LEGACY, datetime(2026, 8, 5, 20, 0), "Priest", "Renew", 700_000))
    page = CharacterPageService(namesakes).page("Hadur")
    assert page is not None and (page.player_class, page.raids) == ("Shaman", 1)


def test_the_lineage_can_be_read_for_the_earlier_class(namesakes):
    with namesakes() as repo:
        shaman = character_lineage(repo, "Hadur")
        priest = character_lineage(repo, "Hadur", player_class="Priest")
        nobody = character_lineage(repo, "Hadur", player_class="Mage")
    assert shaman is not None and priest is not None
    assert (shaman.player_class, shaman.raids, [c.name for c in shaman.casts]) == ("Shaman", 1, ["Chain Heal"])
    assert (priest.player_class, priest.raids, [c.name for c in priest.casts]) == ("Priest", 1, ["Flash Heal"])
    assert nobody is None


def _legacy(namesakes, build_analysis):
    """A raid stored before classes were kept: Hadur's class is not recorded."""
    with namesakes() as repo:
        repo.import_raid(_hadur(build_analysis, LEGACY, datetime(2026, 8, 5, 20, 0), "Unknown", "Renew", 700_000))


def test_a_raid_without_a_class_counts_until_it_is_backfilled(namesakes, build_analysis):
    _legacy(namesakes, build_analysis)
    page = CharacterPageService(namesakes).page("Hadur")
    assert page is not None and page.player_class == "Shaman"
    assert sorted(r.report_id for r in page.recent) == [LEGACY, TBC]

    wcl = FakeWarcraftLogs().answer(
        "subType",
        lambda _query, variables: {
            "reportData": {
                "report": {
                    "masterData": {
                        "actors": [
                            {"id": 1, "name": "Hadur", "type": "Player", "subType": "Priest"},
                            {"id": 2, "name": "TankWarrior", "type": "Player", "subType": "Warrior"},
                            {"id": 3, "name": "StabbyRogue", "type": "Player", "subType": "Rogue"},
                            {"id": 9, "name": "Wolf", "type": "Pet", "subType": "Pet"},
                        ]
                    }
                }
            }
        },
    )
    with wcl.install():
        ctx = AppContext.headless(wcl.client(), namesakes)
        lines: list[str] = []
        assert RaidService(ctx).backfill_classes(progress=lines.append) == 1
        assert RaidService(ctx).backfill_classes() == 0
    assert [q.variables["code"] for q in wcl.queries] == [LEGACY]
    assert lines == [f"Reading classes for {LEGACY} (1/1)..."]

    page = CharacterPageService(namesakes).page("Hadur")
    assert page is not None and [r.report_id for r in page.recent] == [TBC]


def test_a_report_that_cannot_be_read_is_tried_again(namesakes, build_analysis):
    _legacy(namesakes, build_analysis)
    wcl = FakeWarcraftLogs().answer("subType", requests.ConnectionError("down"))
    with wcl.install():
        service = RaidService(AppContext.headless(wcl.client(), namesakes))
        assert service.backfill_classes() == 0
    with namesakes() as repo:
        assert [r["report_id"] for r in repo.get_raids_without_classes()] == [LEGACY]


@pytest.mark.parametrize(
    ("outcome", "code", "said"),
    [
        (3, 0, "Recorded the players' classes in 3 raid(s)."),
        (requests.ConnectionError("down"), 1, "Could not read classes: down"),
    ],
)
def test_the_cli_backfills_classes(monkeypatch, capsys, outcome, code, said):
    contexts = []

    class Service:
        def __init__(self, ctx):
            contexts.append(ctx)

        def backfill_classes(self, progress=None):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr("warcraftlogs_client.services.RaidService", Service)
    monkeypatch.setattr(AppContext, "desktop", classmethod(lambda cls: "ctx"))
    assert cli.run_player_command(cli.create_parser().parse_args(["player", "classes"])) == code
    assert contexts == ["ctx"]
    assert said in capsys.readouterr().out
