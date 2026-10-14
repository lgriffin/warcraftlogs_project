"""Raid search: find a stored raid by its words and open it at the tab a query names ("kara healing")."""

from __future__ import annotations

from datetime import datetime

import pytest
from wcl_app import REPORT_TABS, AppContext, ReportIndex, ReportTab, SearchHit, SearchService
from wcl_app.profiles import Profile
from wcl_app.search import tab_by_key
from wcl_store import StorageError

KARA = "KaraKaraKaraKar1"
GRUUL = "GruulGruulGruul1"
MAG = "MagMagMagMagMag1"
RAIDS = [  # newest first, as get_raid_list returns them
    {"report_id": MAG, "title": "Magtheridon", "zone": "Magtheridon's Lair", "raid_date": "2026-10-08 20:00:00"},
    {"report_id": GRUUL, "title": "Gruul's Lair", "zone": "Gruul's Lair", "raid_date": "2026-10-07 20:00:00"},
    {"report_id": KARA, "title": "Kara Wednesday", "zone": "Karazhan", "raid_date": "2026-09-30 19:30:00"},
]


def _found(hits):
    return [(h.report_id, h.tab.key if h.tab else None) for h in hits]


@pytest.fixture
def index():
    return ReportIndex(RAIDS)


def test_raid_words_find_raids_newest_first(index):
    assert _found(index.search("lair")) == [(MAG, None), (GRUUL, None)]
    assert _found(index.search("karazhan")) == [(KARA, None)]


def test_a_raid_and_a_tab_word_open_that_raid_at_the_tab(index):
    assert _found(index.search("kara healing")) == [(KARA, "healers")]
    assert _found(index.search("Healing KARA")) == [(KARA, "healers")]


def test_tab_words_are_matched_by_synonym_and_prefix(index):
    assert _found(index.search("gruul pots")) == [(GRUUL, "consumables")]
    assert _found(index.search("gruul kicks")) == [(GRUUL, "interrupts")]
    assert _found(index.search("gruul heal")) == [(GRUUL, "healers")]
    assert _found(index.search("gruul roster")) == [(GRUUL, "composition")]


def test_two_letters_are_not_a_tab_prefix(index):
    assert all(hit.tab is None for hit in index.search("he"))  # "he" only finds MagtHEridon


def test_a_bare_tab_word_lists_that_tab_of_the_newest_raids(index):
    assert _found(index.search("healing")) == [(MAG, "healers"), (GRUUL, "healers"), (KARA, "healers")]


def test_a_bare_tab_word_lists_only_the_five_newest_raids():
    raids = [{"report_id": f"raid{n:012d}", "title": f"Raid {n}", "raid_date": "2026-10-01"} for n in range(9)]
    assert len(ReportIndex(raids).search("healing")) == 5


def test_several_tab_words_narrow_to_the_tab_they_share(index):
    assert _found(index.search("kara debuff uptime")) == [(KARA, "debuff_uptime")]
    assert _found(index.search("kara damage taken")) == [(KARA, "tanks")]


def test_a_word_naming_several_tabs_lists_each(index):
    assert _found(index.search("kara dps")) == [(KARA, "melee"), (KARA, "ranged")]
    assert _found(index.search("kara healing tanks")) == [(KARA, "healers"), (KARA, "tanks")]


def test_raids_are_found_by_date_weekday_and_code(index):
    assert _found(index.search("2026-10-07")) == [(GRUUL, None)]
    assert _found(index.search("thursday")) == [(MAG, None)]
    assert _found(index.search("wednesday")) == [(GRUUL, None), (KARA, None)]


def test_every_raid_word_must_match(index):
    assert index.search("kara gruul") == []
    assert index.search("onyxia") == []
    assert index.search("   ") == []


def test_a_pasted_report_link_opens_its_view(index):
    url = f"https://fresh.warcraftlogs.com/reports/{KARA}#fight=3&type=healing"
    assert _found(index.search(url)) == [(KARA, "healers")]
    assert _found(index.search(f"https://www.warcraftlogs.com/reports/{GRUUL}?type=interrupts")) == [
        (GRUUL, "interrupts")
    ]
    assert _found(index.search(KARA)) == [(KARA, None)]


def test_a_link_to_an_unstored_report_offers_to_analyze_it(index):
    [hit] = index.search("https://fresh.warcraftlogs.com/reports/NewRaidNewRaid12#type=damage-taken")
    assert (hit.report_id, hit.stored, hit.tab.key) == ("NewRaidNewRaid12", False, "tanks")
    assert hit.label == "Analyze report NewRaidNewRaid12  >  Tanks"


def test_a_sixteen_letter_word_is_not_a_report_code(index):
    assert index.search("serpentshrinecav") == []


def test_an_unstored_code_of_letters_alone_is_still_a_code(index):
    [hit] = index.search("NewRaidNewRaidAb")
    assert (hit.report_id, hit.stored) == ("NewRaidNewRaidAb", False)


def test_a_damage_done_link_offers_both_damage_tabs(index):
    url = f"https://fresh.warcraftlogs.com/reports/{KARA}#type=damage-done"
    assert _found(index.search(url)) == [(KARA, "melee"), (KARA, "ranged")]


def test_the_full_boss_vs_trash_name_finds_that_tab(index):
    assert _found(index.search("kara boss vs trash")) == [(KARA, "boss_vs_trash")]


def test_a_raid_named_with_a_tab_word_is_listed_after_the_tab_hits():
    raids = [*RAIDS, {"report_id": "TimsRaidTimsRai1", "title": "Kara", "owner": "Tim", "raid_date": "2026-09-01"}]
    found = _found(ReportIndex(raids).search("tim"))
    assert found[:3] == [(MAG, "timeline"), (GRUUL, "timeline"), (KARA, "timeline")]
    assert found[-1] == ("TimsRaidTimsRai1", None)


def test_the_label_shows_date_title_zone_and_tab(index):
    [hit] = index.search("kara healing")
    assert isinstance(hit, SearchHit)
    assert hit.label == "2026-09-30  Kara Wednesday  Karazhan  >  Healers"
    [hit] = index.search("gruul")
    assert hit.label == "2026-10-07  Gruul's Lair"  # a zone the title already names is not repeated


def test_results_stop_at_the_limit(index):
    assert len(index.search("dps", limit=4)) == 4


def test_tabs_are_found_by_key():
    assert isinstance(tab_by_key("healers"), ReportTab)
    assert tab_by_key("healers").label == "Healers"
    assert tab_by_key("nope") is None
    assert len({tab.key for tab in REPORT_TABS}) == len(REPORT_TABS)


def test_the_service_searches_the_active_profiles_raids(tmp_path, build_analysis):
    ctx = AppContext(config={}, db_path=str(tmp_path / "search.db"))
    start = int(datetime(2026, 10, 1, 20, 0).timestamp() * 1000)
    with ctx.repository() as repo:
        repo.import_raid(build_analysis(report_id=KARA, title="Karazhan", start_time=start))
        repo.import_raid(build_analysis(report_id=MAG, title="Onyxia", start_time=start + 86_400_000))
        repo.set_raid_era(KARA, "fresh", "The Burning Crusade")
        repo.set_raid_era(MAG, "fresh", "Classic")

    index = SearchService(ctx).index()
    assert (len(index), index.error) == (2, None)
    assert _found(index.search("karazhan healing")) == [(KARA, "healers")]

    ctx.use_profile(Profile("classic", "Classic", expansions=("Classic",)))
    assert _found(SearchService(ctx).index().search("karazhan")) == []


def test_a_storage_failure_leaves_an_empty_index_that_says_why():
    class Broken:
        def __enter__(self):
            raise StorageError("database is locked")

        def __exit__(self, *exc):
            return False

    index = SearchService(AppContext(config={}, storage=Broken)).index()
    assert (len(index), index.error) == (0, "database is locked")
    assert index.search(f"https://fresh.warcraftlogs.com/reports/{KARA}")[0].stored is False


def test_punctuation_alone_finds_nothing(index):
    assert index.search("?!") == []


def test_a_raid_without_a_readable_date_is_still_found_by_title():
    index = ReportIndex([{"report_id": KARA, "title": "Kara", "raid_date": "someday"}, {"title": "no code"}])
    assert (len(index), _found(index.search("kara"))) == (1, [(KARA, None)])
