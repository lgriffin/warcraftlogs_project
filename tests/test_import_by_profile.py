"""Import by profile (phase 3 in ``guides/identity_and_profiles.md``): a profile imports only its own era.

The guild list comes from the profile's guild and is cut to its era by ``RaidScope.admits``; every raid an import
stores is tagged from the site and zone, so the profile lists it without a backfill; and a profile whose site the
client is not on (Forever, until Warcraft Logs announces it) refuses to import rather than mistag.
"""

from datetime import datetime
from unittest.mock import patch

import pytest
from wcl_core.testing import FakeWarcraftLogs
from wcl_store import RaidScope

from warcraftlogs_client import cli
from warcraftlogs_client.services import AppContext, Profile, ProfileSiteUnknown, RaidService, ReferenceAuthRequired

FRESH = "https://fresh.warcraftlogs.com/api/v2/client"
TBC = "The Burning Crusade"
KARA, MC, GRUUL, TRASH = "KaraKaraKaraKara", "MoltenCoreMolten", "GruulGruulGruulG", "TrashTrashTrashT"
NOV_3 = int(datetime(2026, 11, 3, 20, 0).timestamp() * 1000)
DAY = 86_400_000


def _report(code, zone, expansion=None, start=NOV_3):
    return {
        "code": code,
        "title": zone or "Trash",
        "owner": {"name": "Raidlead"},
        "startTime": start,
        "endTime": start + 3_600_000,
        "zone": {"name": zone, "expansion": {"name": expansion} if expansion else None} if zone else None,
    }


GUILD_LIST = {
    "reportData": {
        "reports": {
            "data": [
                _report(KARA, "Karazhan", TBC),
                _report(MC, "Molten Core", "Classic", NOV_3 - DAY),
                _report(GRUUL, "Gruul's Lair", start=NOV_3 - 2 * DAY),  # no expansion from the API: from the zone
                _report(TRASH, None, start=NOV_3 - 3 * DAY),  # no zone: unknown era, inside every era
            ],
            "has_more_pages": False,
        }
    }
}


ZONES = {KARA: ("Karazhan", TBC), GRUUL: ("Gruul's Lair",), TRASH: (None,)}


def _report_metadata(_query, variables):
    return {"reportData": {"report": _report(variables["code"], *ZONES[variables["code"]])}}


@pytest.fixture
def wcl():
    fake = FakeWarcraftLogs()
    with fake.install():
        yield fake


def _ctx(wcl, tmp_path, profile=None, api_url=FRESH):
    ctx = AppContext(config={"guild_id": 7}, db_path=str(tmp_path / "t.db"), _client=wcl.client(api_url))
    ctx.profile = profile
    return ctx


def _codes(reports):
    return [r["code"] for r in reports]


def test_the_guild_list_carries_each_reports_era(wcl, tmp_path):
    wcl.answer("reports(guildID", GUILD_LIST)
    reports = RaidService(_ctx(wcl, tmp_path)).guild_reports()
    assert [(r["code"], r["game_version"], r["expansion"]) for r in reports] == [
        (KARA, "fresh", TBC),
        (MC, "fresh", "Classic"),
        (GRUUL, "fresh", TBC),
        (TRASH, "fresh", None),
    ]
    assert wcl.queries[0].variables["guildID"] == 7
    assert "expansion { name }" in wcl.queries[0].query
    assert reports[0]["url"] == f"https://fresh.warcraftlogs.com/reports/{KARA}"


def _pages(*pages):
    """Guild report pages by number; every page but the last says there are more."""

    def answer(_query, variables):
        n = variables["page"]
        return {"reportData": {"reports": {"data": pages[n - 1], "has_more_pages": n < len(pages)}}}

    return answer


def test_a_profile_pages_past_newer_reports_from_other_eras(wcl, tmp_path):
    classic = [_report(f"MoltenCore{i:06d}", "Molten Core", "Classic") for i in range(100)]
    tbc = [_report(f"Karazhan{i:08d}", "Karazhan", TBC) for i in range(3)]
    wcl.answer("reports(guildID", _pages(classic, tbc))
    reports = RaidService(_ctx(wcl, tmp_path, Profile("tbc", "TBC", expansions=(TBC,)))).guild_reports()
    assert len(reports) == 3 and [q.variables["page"] for q in wcl.queries] == [1, 2]
    assert all(q.variables["limit"] == 100 for q in wcl.queries)


def test_the_client_keeps_paging_only_as_far_as_asked(wcl):
    classic = [_report(f"MoltenCore{i:06d}", "Molten Core", "Classic") for i in range(100)]
    wcl.answer("reports(guildID", _pages(*[classic] * 9))
    client = wcl.client(FRESH)
    assert client.get_guild_reports(9, total=2, keep=lambda r: r["expansion"] == TBC, scan=250) == []
    assert len(wcl.queries) == 3  # 300 scanned: past the 250 asked for, and no further
    kept = client.get_guild_reports(9, total=2, keep=lambda r: True)
    assert [r["code"] for r in kept] == ["MoltenCore000000", "MoltenCore000001"] and len(wcl.queries) == 4
    plain = client.get_guild_reports(9, total=150)
    assert len(plain) == 150 and [q.variables["limit"] for q in wcl.queries[4:]] == [100, 100]


def test_an_empty_page_ends_the_scan(wcl):
    wcl.answer("reports(guildID", {"reportData": {"reports": {"data": [], "has_more_pages": True}}})
    assert wcl.client(FRESH).get_guild_reports(9, keep=lambda r: True) == []
    assert len(wcl.queries) == 1


def test_a_profile_fetches_only_its_eras_reports_from_its_guild(wcl, tmp_path):
    wcl.answer("reports(guildID", GUILD_LIST)
    profile = Profile("tbc", "TBC", game_version="fresh", expansions=(TBC,), guild_id=9)
    assert _codes(RaidService(_ctx(wcl, tmp_path, profile)).guild_reports()) == [KARA, GRUUL, TRASH]
    assert wcl.queries[0].variables["guildID"] == 9


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (Profile("classic", "Classic days", expansions=("Classic",)), [MC, TRASH]),
        (Profile("kara", "Kara", zones=("KARAZHAN",)), [KARA]),
        (Profile("recent", "Recent", since="2026-11-02 00:00:00"), [KARA, MC]),
        (Profile("old", "Old", until="2026-11-02 00:00:00"), [GRUUL, TRASH]),
    ],
)
def test_every_axis_of_the_scope_cuts_the_guild_list(wcl, tmp_path, profile, expected):
    wcl.answer("reports(guildID", GUILD_LIST)
    assert _codes(RaidService(_ctx(wcl, tmp_path, profile)).guild_reports()) == expected


def test_admits_follows_the_store_rule_for_unstored_raids():
    tbc = RaidScope(game_versions=("fresh",), expansions=(TBC,))
    assert tbc.admits(game_version="fresh", expansion=TBC)
    assert tbc.admits()  # an unknown era is inside every era
    assert not tbc.admits(game_version="classic", expansion=TBC)
    assert not tbc.admits(game_version="fresh", expansion="Classic")
    assert not tbc.admits(source="reference", game_version="fresh", expansion=TBC)
    assert RaidScope(zones=("gruul's lair",)).admits(zone="Gruul's Lair")
    assert not RaidScope(zones=("Karazhan",)).admits(zone=None)
    window = RaidScope(since="2026-11-01 00:00:00", until="2026-11-02 00:00:00")
    assert window.admits(raid_date="2026-11-01 00:00:00")
    assert not window.admits(raid_date="2026-11-02 00:00:00")
    assert not window.admits(raid_date="2026-10-31 23:59:59")
    assert not window.admits(raid_date=None)
    assert not RaidScope(zones=("äRA",)).admits(zone="Ära")  # only ASCII letters fold, as in the stores


def test_new_guild_reports_leaves_out_stored_ones(wcl, tmp_path):
    wcl.answer("reports(guildID", GUILD_LIST)
    raids = RaidService(_ctx(wcl, tmp_path, Profile("tbc", "TBC", expansions=(TBC,))))
    with patch.object(RaidService, "imported_codes", return_value={KARA}):
        assert _codes(raids.new_guild_reports()) == [GRUUL, TRASH]


def test_a_raid_imported_under_a_profile_is_listed_by_it_without_a_backfill(wcl, tmp_path, sample_raid_analysis):
    wcl.answer("reports(guildID", GUILD_LIST)
    wcl.answer("report(code: $code)", _report_metadata)
    profile = Profile("tbc", "TBC", game_version="fresh", expansions=(TBC,))
    ctx = _ctx(wcl, tmp_path, profile)

    def analyze(client, code, **_):
        sample_raid_analysis.metadata = client.get_report_metadata(code)
        return sample_raid_analysis

    with patch("warcraftlogs_client.services.raids.analyze_raid", side_effect=analyze):
        assert RaidService(ctx).import_new() == [KARA, GRUUL, TRASH]
        assert RaidService(ctx).import_new() == []
    listed = {r["report_id"]: (r["game_version"], r["expansion"]) for r in RaidService(ctx).list_raids()}
    assert listed == {KARA: ("fresh", TBC), GRUUL: ("fresh", TBC), TRASH: ("fresh", None)}


def test_a_profile_whose_site_is_unknown_refuses_to_import(wcl, tmp_path):
    forever = Profile("forever", "Forever", game_version="forever")
    assert forever.api_url is None  # Warcraft Logs has not announced the site, so the configured host stays
    raids = RaidService(_ctx(wcl, tmp_path, forever))
    with pytest.raises(ProfileSiteUnknown, match="Forever profile is forever, but imports would come from the fresh"):
        raids.guild_reports()
    with pytest.raises(ProfileSiteUnknown):
        raids.import_missing([KARA])
    with patch("warcraftlogs_client.services.raids.analyze_raid") as analyze, pytest.raises(ProfileSiteUnknown):
        raids.analyze(KARA)
    analyze.assert_not_called()
    assert wcl.queries == []


def test_the_site_check_passes_with_the_profiles_own_url_or_no_game_version(wcl, tmp_path):
    forever = Profile("forever", "Forever", game_version="forever", wcl_api_url="https://forever.warcraftlogs.com/x")
    RaidService(_ctx(wcl, tmp_path, forever, api_url=forever.api_url)).check_profile_site()
    RaidService(_ctx(wcl, tmp_path, Profile("tbc", "TBC", expansions=(TBC,)))).check_profile_site()
    RaidService(_ctx(wcl, tmp_path)).check_profile_site()
    with patch.object(AppContext, "user_client", return_value=None), pytest.raises(ReferenceAuthRequired):
        RaidService(_ctx(wcl, tmp_path, Profile("f", "F", game_version="forever"))).analyze(KARA, reference=True)


class TestCli:
    def _run(self, wcl, tmp_path, monkeypatch, profile, *argv):
        ctx = _ctx(wcl, tmp_path, profile)
        service = type("S", (), {"ctx": ctx})()
        monkeypatch.setattr(cli, "_profile_service", lambda need_config: service)
        monkeypatch.setattr("sys.argv", ["warcraftlogs", "profile", "import", *argv])
        return cli.main()

    def test_import_lists_then_imports_the_profiles_new_reports(self, wcl, tmp_path, monkeypatch, capsys):
        wcl.answer("reports(guildID", GUILD_LIST)
        profile = Profile("classic", "Classic days", expansions=("Classic",))
        with patch.object(RaidService, "import_missing", return_value=[MC, TRASH]) as imported:
            assert self._run(wcl, tmp_path, monkeypatch, profile, "--list") == 0
            imported.assert_not_called()
            assert "2 new report(s) to import." in capsys.readouterr().out
            assert self._run(wcl, tmp_path, monkeypatch, profile) == 0
        assert imported.call_args.args[0] == [MC, TRASH]
        out = capsys.readouterr().out
        assert MC in out and KARA not in out and "2 new report(s) imported." in out

    def test_import_says_why_a_profile_cannot_import(self, wcl, tmp_path, monkeypatch, capsys):
        assert self._run(wcl, tmp_path, monkeypatch, Profile("forever", "Forever", game_version="forever")) == 1
        assert "Import failed: The Forever profile is forever" in capsys.readouterr().out
