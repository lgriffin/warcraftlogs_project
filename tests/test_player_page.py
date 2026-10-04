"""Tests for the player page service: discovering and collecting a character's reports."""

import json
from unittest.mock import MagicMock, patch

import pytest

from warcraftlogs_client.services.player_page import (
    ADDED,
    ALREADY_ON_PAGE,
    DISMISSED,
    FAILED,
    INVALID,
    NEW,
    NOT_IN_REPORT,
    ON_PAGE,
    AddResult,
    PlayerPageService,
    PlayerRef,
    parse_report_code,
    server_slug,
)

CODE_A = "AAAAbbbbCCCCdddd"
CODE_B = "BBBBccccDDDDeeee"
CODE_C = "CCCCddddEEEEffff"

PLAYER = PlayerRef.create("HolyPriest", "Spineshatter", "EU")


def _wcl_report(code, title="Kara", start=1_700_000_000_000, zone="Karazhan"):
    return {
        "code": code,
        "title": title,
        "owner": "Uploader",
        "guild": "Toads",
        "start_time": start,
        "end_time": start + 3_600_000,
        "zone": zone,
    }


@pytest.fixture
def fake_client():
    client = MagicMock()
    client.get_character_reports.return_value = (
        [_wcl_report(CODE_A, start=1_700_000_000_000), _wcl_report(CODE_B, "Gruul", start=1_700_100_000_000)],
        False,
    )
    client.get_all_actors.return_value = [
        {"id": 1, "name": "HolyPriest", "type": "Player"},
        {"id": 50, "name": "Prince Malchezaar", "type": "NPC"},
    ]
    return client


@pytest.fixture
def analyzer(build_analysis):
    calls = []

    def _analyze(code):
        calls.append(code)
        return build_analysis(report_id=code, title=f"Raid {code[:4]}")

    _analyze.calls = calls
    return _analyze


class TestParsing:
    @pytest.mark.parametrize(
        "text",
        [
            CODE_A,
            f"  {CODE_A}  ",
            f"https://fresh.warcraftlogs.com/reports/{CODE_A}",
            f"https://www.warcraftlogs.com/reports/{CODE_A}#fight=3&type=healing",
            f"https://classic.warcraftlogs.com/reports/{CODE_A}/",
            f"https://fresh.warcraftlogs.com/reports/{CODE_A}?fight=last",
        ],
    )
    def test_parse_report_code(self, text):
        assert parse_report_code(text) == CODE_A

    @pytest.mark.parametrize(
        "text", ["", "short", "AAAAbbbbCCCCdddd1", "https://example.com/reports/AAAAbbbbCCCCdddd", "a'; DROP--xxxxxx"]
    )
    def test_rejects_non_reports(self, text):
        assert parse_report_code(text) is None

    def test_server_slug(self):
        assert server_slug("Pyrewood Village") == "pyrewood-village"
        assert server_slug("Mograine") == "mograine"
        assert server_slug("Zul'jin") == "zuljin"

    def test_player_ref_normalises(self):
        ref = PlayerRef.create("  hOLYpriest ", "Spine Shatter", "EU")
        assert ref == PlayerRef("Holypriest", "spine-shatter", "eu")

    @pytest.mark.parametrize(
        "name,server,region",
        [("", "s", "eu"), ('Bad"Name', "s", "eu"), ("Name", "", "eu"), ("Name", "s", "e1"), ("Two Words", "s", "eu")],
    )
    def test_player_ref_rejects_bad_input(self, name, server, region):
        with pytest.raises(ValueError):
            PlayerRef.create(name, server, region)


@pytest.mark.database
class TestDiscover:
    def test_lists_wcl_reports_newest_first(self, db, fake_client):
        logs = PlayerPageService(db, fake_client).discover_reports(PLAYER)
        assert [log.code for log in logs] == [CODE_B, CODE_A]
        assert all(log.status == NEW and not log.imported and log.source == "wcl" for log in logs)
        fake_client.get_character_reports.assert_called_once_with("Holypriest", "spineshatter", "eu", limit=50, page=1)

    def test_paginates_until_limit(self, db):
        client = MagicMock()
        client.get_character_reports.side_effect = [
            ([_wcl_report(CODE_A)], True),
            ([_wcl_report(CODE_B)], True),
            ([_wcl_report(CODE_C)], False),
        ]
        logs = PlayerPageService(db, client).discover_reports(PLAYER, limit=2)
        assert len(logs) == 2
        assert client.get_character_reports.call_count == 2

    def test_merges_local_raids(self, db, fake_client, build_analysis):
        db.import_raid(build_analysis(report_id=CODE_A))
        db.import_raid(build_analysis(report_id=CODE_C, start_time=1_600_000_000_000))
        logs = {log.code: log for log in PlayerPageService(db, fake_client).discover_reports(PLAYER)}
        assert logs[CODE_A].source == "both" and logs[CODE_A].imported
        assert logs[CODE_C].source == "local" and logs[CODE_C].imported
        assert logs[CODE_B].source == "wcl" and not logs[CODE_B].imported

    def test_local_only_without_client(self, db, build_analysis):
        db.import_raid(build_analysis(report_id=CODE_A))
        db.import_raid(build_analysis(report_id=CODE_B, healer_name="SomeoneElse"))
        logs = PlayerPageService(db).discover_reports(PLAYER)
        assert [log.code for log in logs] == [CODE_A]

    def test_marks_on_page_and_dismissed(self, db, fake_client, analyzer):
        service = PlayerPageService(db, fake_client, analyze=analyzer)
        service.add_reports(PLAYER, [CODE_A])
        service.dismiss(PLAYER, [CODE_B])
        logs = {log.code: log.status for log in service.discover_reports(PLAYER)}
        assert logs == {CODE_A: ON_PAGE, CODE_B: DISMISSED}


@pytest.mark.database
class TestAddLogs:
    def test_imports_and_links_discovered_report(self, db, fake_client, analyzer):
        service = PlayerPageService(db, fake_client, analyze=analyzer)
        known = {log.code: log for log in service.discover_reports(PLAYER)}
        results = service.add_reports(PLAYER, [CODE_A], known=known)

        assert all(isinstance(r, AddResult) for r in results)
        assert [(r.code, r.outcome) for r in results] == [(CODE_A, ADDED)]
        assert analyzer.calls == [CODE_A]
        assert db.is_raid_imported(CODE_A)
        fake_client.get_all_actors.assert_not_called()  # discovery already proved participation

        page = service.get_page(PLAYER)
        assert [log.code for log in page.logs] == [CODE_A]
        assert page.logs[0].title == "Kara"  # WCL metadata kept
        assert page.history["total_raids"] == 1

    def test_add_by_url_verifies_participation(self, db, fake_client, analyzer):
        service = PlayerPageService(db, fake_client, analyze=analyzer)
        results = service.add_reports(PLAYER, [f"https://fresh.warcraftlogs.com/reports/{CODE_C}#fight=1"])
        assert results[0].outcome == ADDED
        fake_client.get_all_actors.assert_called_once_with(CODE_C)
        assert service.get_page(PLAYER).logs[0].title == f"Raid {CODE_C[:4]}"

    def test_rejects_report_without_player(self, db, fake_client, analyzer):
        fake_client.get_all_actors.return_value = [{"id": 2, "name": "Stranger", "type": "Player"}]
        results = PlayerPageService(db, fake_client, analyze=analyzer).add_reports(PLAYER, [CODE_C])
        assert results[0].outcome == NOT_IN_REPORT
        assert analyzer.calls == []
        assert not db.is_raid_imported(CODE_C)

    def test_no_verify_skips_check(self, db, fake_client, analyzer):
        fake_client.get_all_actors.return_value = []
        results = PlayerPageService(db, fake_client, analyze=analyzer).add_reports(PLAYER, [CODE_C], verify=False)
        assert results[0].outcome == ADDED

    def test_already_imported_report_is_linked_without_api(self, db, build_analysis):
        db.import_raid(build_analysis(report_id=CODE_A, title="Stored Raid"))
        service = PlayerPageService(db)  # no client, no analyzer
        results = service.add_reports(PLAYER, [CODE_A])
        assert results[0].outcome == ADDED
        page = service.get_page(PLAYER)
        assert page.logs[0].title == "Stored Raid" and page.logs[0].imported

    def test_invalid_duplicate_and_already_on_page(self, db, fake_client, analyzer):
        service = PlayerPageService(db, fake_client, analyze=analyzer)
        service.add_reports(PLAYER, [CODE_A])
        results = service.add_reports(PLAYER, ["not a report", CODE_A, CODE_B, CODE_B])
        assert [(r.code, r.outcome) for r in results] == [
            ("not a report", INVALID),
            (CODE_A, ALREADY_ON_PAGE),
            (CODE_B, ADDED),
        ]

    def test_api_failure_is_reported_not_raised(self, db, fake_client):
        def boom(code):
            raise ValueError("Report not found or inaccessible")

        results = PlayerPageService(db, fake_client, analyze=boom).add_reports(PLAYER, [CODE_A], verify=False)
        assert results[0].outcome == FAILED
        assert "inaccessible" in results[0].message
        assert PlayerPageService(db).get_page(PLAYER).logs == []

    def test_new_report_without_client_fails_cleanly(self, db):
        results = PlayerPageService(db).add_reports(PLAYER, [CODE_A], verify=False)
        assert results[0].outcome == FAILED


@pytest.mark.database
class TestPageManagement:
    def test_remove_keeps_raid_data(self, db, fake_client, analyzer):
        service = PlayerPageService(db, fake_client, analyze=analyzer)
        service.add_reports(PLAYER, [CODE_A])
        assert service.remove(PLAYER, [CODE_A]) == 1
        assert service.get_page(PLAYER).logs == []
        assert db.is_raid_imported(CODE_A)

    def test_pages_are_case_insensitive_and_listed(self, db, fake_client, analyzer):
        service = PlayerPageService(db, fake_client, analyze=analyzer)
        service.add_reports(PLAYER, [CODE_A])
        same = PlayerRef("HOLYPRIEST", "SPINESHATTER", "EU")
        assert service.open_page(same) == service.open_page(PLAYER)
        pages = service.list_pages("holypriest")
        assert len(pages) == 1 and pages[0]["log_count"] == 1

    def test_to_dict_is_json_serialisable(self, db, fake_client, analyzer):
        service = PlayerPageService(db, fake_client, analyze=analyzer)
        service.add_reports(PLAYER, [CODE_A])
        payload = json.loads(json.dumps(service.get_page(PLAYER).to_dict()))
        assert payload["player"] == {"name": "Holypriest", "server": "spineshatter", "region": "eu"}
        assert payload["logs"][0]["code"] == CODE_A
        assert payload["logs"][0]["date"]
        assert payload["badges"]["name"] == "Holypriest" and payload["badges"]["player_class"] == "Priest"
        attendance = payload["badges"]["badges"][0]
        assert (attendance["id"], attendance["value"], attendance["tier"]) == ("attendance", 1, 0)

    def test_page_badges_use_the_configured_thresholds(self, db, fake_client, analyzer):
        from warcraftlogs_client.services import AppContext

        ctx = AppContext(config={"badges": {"thresholds": {"attendance": [1]}}}, _client=fake_client)
        PlayerPageService(db, fake_client, analyze=analyzer).add_reports(PLAYER, [CODE_A])
        page = PlayerPageService.from_context(ctx, db, with_api=False).get_page(PLAYER)
        assert page.badges is not None
        assert [b.id for b in page.badges.earned] == ["attendance"]

    def test_clear_all_removes_pages(self, db, fake_client, analyzer):
        PlayerPageService(db, fake_client, analyze=analyzer).add_reports(PLAYER, [CODE_A])
        db.clear_all()
        assert db.find_player_pages() == []


class TestFromContext:
    def test_uses_context_client_and_raid_service(self, db, fake_client):
        from warcraftlogs_client.services import AppContext, RaidService

        ctx = AppContext(config={}, _client=fake_client)
        service = PlayerPageService.from_context(ctx, db)
        assert service.client is fake_client
        assert service._analyze.__func__ is RaidService.analyze

    def test_local_only_never_builds_client(self, db):
        from warcraftlogs_client.services import AppContext

        ctx = AppContext(config={})  # no credentials: touching wcl_client would raise
        service = PlayerPageService.from_context(ctx, db, with_api=False)
        assert service.client is None


@pytest.mark.api
class TestClientCharacterReports:
    @patch("wcl_core.http.requests.post")
    def test_parses_reports(self, mock_post):
        from warcraftlogs_client.client import WarcraftLogsClient

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "characterData": {
                        "character": {
                            "recentReports": {
                                "data": [
                                    {
                                        "code": CODE_A,
                                        "title": "Kara",
                                        "startTime": 1,
                                        "endTime": 2,
                                        "owner": {"name": "Up"},
                                        "guild": None,
                                        "zone": {"name": "Karazhan"},
                                    }
                                ],
                                "has_more_pages": True,
                            }
                        }
                    }
                }
            },
        )
        client = WarcraftLogsClient(MagicMock(get_token=lambda: "t"), cache_enabled=False)
        reports, more = client.get_character_reports('Evil"Name', "server", "eu", limit=10, page=2)
        assert more is True
        assert reports == [
            {
                "code": CODE_A,
                "title": "Kara",
                "owner": "Up",
                "guild": "",
                "start_time": 1,
                "end_time": 2,
                "zone": "Karazhan",
            }
        ]
        payload = mock_post.call_args.kwargs["json"]
        assert "Evil" not in payload["query"]  # user input travels as a variable, never in the query text
        assert payload["variables"] == {
            "name": 'Evil"Name',
            "serverSlug": "server",
            "serverRegion": "eu",
            "limit": 10,
            "page": 2,
        }

    @patch("wcl_core.http.requests.post")
    def test_unknown_character_raises(self, mock_post):
        from warcraftlogs_client.client import WarcraftLogsClient

        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {"data": {"characterData": {"character": None}}}
        )
        client = WarcraftLogsClient(MagicMock(get_token=lambda: "t"), cache_enabled=False)
        with pytest.raises(ValueError, match="not found"):
            client.get_character_reports("Nobody", "server", "eu")


class TestPlayerCli:
    @pytest.fixture
    def run_cli(self, tmp_path, fake_client, analyzer, capsys):
        from warcraftlogs_client import cli
        from warcraftlogs_client.services import AppContext

        ctx = AppContext(config={"default_region": "EU"}, db_path=str(tmp_path / "cli.db"), _client=fake_client)
        real_from_context = PlayerPageService.from_context.__func__

        def from_context(cls, ctx, db, *, with_api=True):
            service = real_from_context(cls, ctx, db, with_api=with_api)
            service._analyze = analyzer
            return service

        def _run(*argv):
            with (
                patch("sys.argv", ["warcraftlogs", *argv]),
                patch("warcraftlogs_client.services.AppContext.from_config_file", return_value=ctx),
                patch.object(PlayerPageService, "from_context", classmethod(from_context)),
            ):
                code = cli.main()
            return code, capsys.readouterr().out

        return _run

    def test_parser(self):
        from warcraftlogs_client.cli import create_parser

        args = create_parser().parse_args(["player", "add", "Hadur", CODE_A, "-s", "gehennas", "--no-verify"])
        assert (args.command, args.player_command, args.name, args.reports) == ("player", "add", "Hadur", [CODE_A])
        assert args.server == "gehennas" and args.no_verify is True

    def test_discover_add_show_flow(self, run_cli):
        code, out = run_cli("player", "discover", "HolyPriest", "-s", "spineshatter", "-r", "eu")
        assert code == 0 and CODE_A in out and "2 new" in out

        code, out = run_cli("player", "add", "HolyPriest", "--new")  # server/region come from the page
        assert code == 0 and sum(f" {ADDED} " in line for line in out.splitlines()) == 2

        code, out = run_cli("player", "show", "HolyPriest", "--json")
        payload = json.loads(out)
        assert {log["code"] for log in payload["logs"]} == {CODE_A, CODE_B}

        code, out = run_cli("player", "list", "--json")
        assert json.loads(out)[0]["log_count"] == 2

    def test_add_reports_failures_in_exit_code(self, run_cli):
        code, out = run_cli("player", "add", "HolyPriest", "nonsense", "-s", "x", "-r", "eu")
        assert code == 1 and INVALID in out
