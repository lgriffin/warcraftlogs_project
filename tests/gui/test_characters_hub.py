"""The character list, history and compare views read under the raid profile and re-read on a switch (PROF-07)."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget
from wcl_app.profiles import Profile

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.gui import characters_hub
from warcraftlogs_client.gui.character_history_widget import CharacterHistoryWidget
from warcraftlogs_client.gui.compare_view import CompareView
from warcraftlogs_client.services import AppContext, CharacterService

CLASSIC, TBC = "ClassicRaid00000", "TbcRaid000000000"
TBC_ONLY = Profile("tbc", "TBC", expansions=("The Burning Crusade",))
NOWHERE = Profile("z", "Z", zones=("Nowhere",))


class _StubView(QWidget):
    """Stands in for the character and player page views, which the hub only routes signals from."""

    status_message = Signal(str)
    analyze_report = Signal(str)
    view_character_history = Signal(str)
    open_report = Signal(str)


@pytest.fixture
def ctx(tmp_path, build_analysis):
    path = str(tmp_path / "characters.db")
    with PerformanceDB(path) as db:
        for n, (code, expansion) in enumerate(((CLASSIC, "Classic"), (TBC, "The Burning Crusade"))):
            db.import_raid(build_analysis(report_id=code, start_time=1_700_000_000_000 + n * 604_800_000))
            db.set_raid_era(code, "fresh", expansion)
    return AppContext(config={}, db_path=path)


def _row(hub, name: str) -> str:
    return next(hub._list.item(i).text() for i in range(hub._list.count()) if name in hub._list.item(i).text())


@pytest.mark.gui
class TestCharactersFollowTheProfile:
    def test_the_history_widget_reads_the_active_profile(self, qtbot, ctx):
        ctx.use_profile(TBC_ONLY)
        widget = CharacterHistoryWidget("HolyPriest", characters=CharacterService(ctx))
        qtbot.addWidget(widget)
        assert widget.summary_labels["Raids Tracked"].text() == "1"
        assert {r["report_id"] for r in widget._all_healer_trend} == {TBC}

    def test_a_character_outside_the_profile_has_no_history(self, qtbot, ctx):
        ctx.use_profile(NOWHERE)
        widget = CharacterHistoryWidget("HolyPriest", characters=CharacterService(ctx))
        qtbot.addWidget(widget)
        assert widget._title_label.text() == "HolyPriest — No history found"

    def test_compare_refresh_rereads_and_drops_characters_outside_the_profile(self, qtbot, ctx):
        view = CompareView(characters=CharacterService(ctx))
        qtbot.addWidget(view)
        view._refresh_character_list()
        view._load_and_add("HolyPriest")
        assert view._char_stats["HolyPriest"]["total_raids"] == 2
        ctx.use_profile(TBC_ONLY)
        view.refresh()
        assert view._selected == ["HolyPriest"] and view._char_stats["HolyPriest"]["total_raids"] == 1
        ctx.use_profile(NOWHERE)
        view.refresh()
        assert view._selected == [] and view._all_characters == []

    def test_hub_refresh_rereads_the_list_and_the_open_history(self, qtbot, ctx, monkeypatch):
        monkeypatch.setattr(characters_hub, "CharacterView", _StubView)
        monkeypatch.setattr(characters_hub, "PlayerPageView", _StubView)
        hub = characters_hub.CharactersHub(characters=CharacterService(ctx))
        qtbot.addWidget(hub)
        hub._load_characters()
        assert "(2 raids)" in _row(hub, "HolyPriest")
        hub._show_character_history("HolyPriest")
        hub._show_compare()
        ctx.use_profile(TBC_ONLY)
        hub.refresh()
        assert "(1 raids)" in _row(hub, "HolyPriest")
        assert hub._current_history.summary_labels["Raids Tracked"].text() == "1"
        assert hub._right_stack.currentIndex() == 3  # the compare page stays in front
