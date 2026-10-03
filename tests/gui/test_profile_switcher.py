"""The top bar's raid profile switcher (PROF-09)."""

import pytest

pytest.importorskip("PySide6")

from wcl_app.profiles import JsonProfileStore, ProfileService

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.gui.profile_switcher import ALL_RAIDS, NO_COUNT, ProfileSwitcher, count_text
from warcraftlogs_client.services import AppContext

CLASSIC, TBC = "ClassicRaid00000", "TbcRaid000000000"


@pytest.fixture
def service(tmp_path, build_analysis):
    path = str(tmp_path / "switch.db")
    with PerformanceDB(path) as db:
        for code, expansion in ((CLASSIC, "Classic"), (TBC, "The Burning Crusade")):
            db.import_raid(build_analysis(report_id=code))
            db.set_raid_era(code, "fresh", expansion)
    profiles = ProfileService(JsonProfileStore(tmp_path / "profiles.json"), AppContext(config={}, db_path=path))
    profiles.create("TBC", expansions=("The Burning Crusade",))
    return profiles


def _switcher(qtbot, service):
    switcher = ProfileSwitcher(service)
    qtbot.addWidget(switcher)
    _settle(qtbot, switcher)
    return switcher


def _settle(qtbot, switcher):
    """Wait until every count has landed and its worker has finished, so teardown never meets a running thread."""
    qtbot.waitUntil(lambda: switcher.count_label.text() not in ("", "counting...") and not switcher._workers)


def test_count_text():
    assert (count_text(0), count_text(1), count_text(2), count_text(None)) == ("0 raids", "1 raid", "2 raids", NO_COUNT)


@pytest.mark.gui
class TestProfileSwitcher:
    def test_lists_all_raids_and_each_profile(self, qtbot, service):
        switcher = _switcher(qtbot, service)
        assert [switcher.combo.itemText(i) for i in range(switcher.combo.count())] == [ALL_RAIDS, "TBC"]
        assert switcher.combo.currentText() == ALL_RAIDS
        assert switcher.count_label.text() == "2 raids"

    def test_switching_activates_the_profile_then_recounts(self, qtbot, service):
        switcher = _switcher(qtbot, service)
        with qtbot.waitSignal(switcher.profile_changed) as changed:
            switcher.combo.setCurrentIndex(1)
        assert changed.args == ["TBC"]
        assert service.active().slug == "tbc" and service.ctx.profile is not None
        _settle(qtbot, switcher)
        assert switcher.count_label.text() == "1 raid"
        switcher.combo.setCurrentIndex(0)
        _settle(qtbot, switcher)
        assert service.active() is None and switcher.count_label.text() == "2 raids"

    def test_a_count_for_an_earlier_switch_is_dropped(self, qtbot, service):
        switcher = _switcher(qtbot, service)
        switcher._on_counted(switcher._generation - 1, 99)
        assert switcher.count_label.text() == "2 raids"

    def test_starts_on_the_saved_active_profile(self, qtbot, service):
        service.activate("tbc")
        switcher = _switcher(qtbot, service)
        assert switcher.combo.currentText() == "TBC"
        assert switcher.active_name() == "TBC"
        assert switcher.count_label.text() == "1 raid"
