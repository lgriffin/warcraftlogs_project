"""The top bar's raid profile switcher (PROF-09)."""

import pytest

pytest.importorskip("PySide6")

from wcl_app.profiles import JsonProfileStore, ProfileService

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.gui.profile_switcher import ALL_RAIDS, ProfileSwitcher
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


@pytest.mark.gui
class TestProfileSwitcher:
    def test_lists_all_raids_and_each_profile(self, qtbot, service):
        switcher = ProfileSwitcher(service)
        qtbot.addWidget(switcher)
        assert [switcher.combo.itemText(i) for i in range(switcher.combo.count())] == [ALL_RAIDS, "TBC"]
        assert switcher.combo.currentText() == ALL_RAIDS
        assert switcher.count_label.text() == "2 raids"

    def test_switching_activates_the_profile_and_recounts(self, qtbot, service):
        switcher = ProfileSwitcher(service)
        qtbot.addWidget(switcher)
        with qtbot.waitSignal(switcher.profile_changed) as signal:
            switcher.combo.setCurrentIndex(1)
        assert signal.args == ["TBC"]
        assert service.active().slug == "tbc"
        assert service.ctx.profile is not None
        assert switcher.count_label.text() == "1 raid"
        switcher.combo.setCurrentIndex(0)
        assert service.active() is None and switcher.count_label.text() == "2 raids"

    def test_starts_on_the_saved_active_profile(self, qtbot, service):
        service.activate("tbc")
        switcher = ProfileSwitcher(service)
        qtbot.addWidget(switcher)
        assert switcher.combo.currentText() == "TBC"
        assert switcher.active_name() == "TBC"
