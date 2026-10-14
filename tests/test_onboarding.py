"""First-run setup (``wcl_app.onboarding``): check the API keys, find the guild, save both."""

import json

import pytest
import requests
from wcl_app import AppContext, GuildMatch, JsonConfigStore, MemoryConfigStore, OnboardingService, SetupError
from wcl_app.onboarding import KEYS_URL, REDIRECT_URL, is_placeholder
from wcl_core.common.errors import ConfigurationError
from wcl_core.config import load_config
from wcl_core.testing import FakeWarcraftLogs, status

AMICABLE = {
    "id": 774065,
    "name": "Amicable",
    "server": {"name": "Gehennas", "slug": "gehennas", "region": {"slug": "EU"}},
}
FRESH_API = "https://fresh.warcraftlogs.com/api/v2/client"
TEMPLATE = {  # config.example.json's keys, as a first run copies it
    "client_id": "YOUR_CLIENT_ID_HERE",
    "client_secret": "YOUR_CLIENT_SECRET_HERE",
    "report_id": "YOUR_DEFAULT_REPORT_ID",
    "wcl_api_url": FRESH_API,
}


@pytest.fixture(autouse=True)
def no_key_env(monkeypatch):
    monkeypatch.delenv("WARCRAFTLOGS_CLIENT_ID", raising=False)
    monkeypatch.delenv("WARCRAFTLOGS_CLIENT_SECRET", raising=False)


def _service(config=None) -> OnboardingService:
    return OnboardingService(MemoryConfigStore(config))


def _wcl(guild=AMICABLE) -> FakeWarcraftLogs:
    return FakeWarcraftLogs().answer("guildData", {"guildData": {"guild": guild}})


class TestNeedsSetup:
    def test_no_config_or_the_template_needs_setup(self):
        assert _service().needs_setup()
        assert _service(TEMPLATE).needs_setup()
        assert _service({"client_id": "abc", "client_secret": " "}).needs_setup()

    def test_real_keys_or_environment_keys_do_not(self, monkeypatch):
        assert not _service({"client_id": "abc", "client_secret": "xyz"}).needs_setup()
        monkeypatch.setenv("WARCRAFTLOGS_CLIENT_ID", "abc")
        monkeypatch.setenv("WARCRAFTLOGS_CLIENT_SECRET", "xyz")
        assert not _service(TEMPLATE).needs_setup()

    def test_saved_keys_hide_the_template_stand_ins(self):
        assert _service(TEMPLATE).saved_keys() == ("", "")
        assert _service({"client_id": " abc ", "client_secret": "xyz"}).saved_keys() == ("abc", "xyz")

    def test_the_site_is_config_s_or_the_loader_s_default(self):
        assert _service({"wcl_api_url": "https://sod.warcraftlogs.com/api/v2/client"}).site() == "sod"
        assert _service().site() == "fresh"  # what load_config fills in when config names no site

    def test_placeholders(self):
        assert is_placeholder(None) and is_placeholder("") and is_placeholder("your_client_id_here")
        assert not is_placeholder("9f1c")

    def test_the_links_point_at_warcraft_logs_and_the_sign_in_callback(self):
        assert KEYS_URL == "https://www.warcraftlogs.com/api/clients/"
        assert REDIRECT_URL == "http://localhost:8764/callback"


class TestCheckKeys:
    def test_good_keys_get_a_token(self):
        wcl = FakeWarcraftLogs()
        with wcl.install():
            _service().check_keys(" abc ", "xyz")
        assert len(wcl.token_requests) == 1

    def test_refused_keys_say_to_copy_them_again(self):
        with FakeWarcraftLogs().token(status(401)).install(), pytest.raises(SetupError, match="did not accept"):
            _service().check_keys("abc", "wrong")

    def test_no_network_says_so(self):
        wcl = FakeWarcraftLogs().token(requests.ConnectionError("down"))
        with wcl.install(), pytest.raises(SetupError, match="internet connection"):
            _service().check_keys("abc", "xyz")

    def test_blank_or_template_keys_are_refused_before_asking(self):
        wcl = FakeWarcraftLogs()
        with wcl.install(), pytest.raises(SetupError, match="both the Client ID"):
            _service().check_keys("YOUR_CLIENT_ID_HERE", "xyz")
        assert wcl.requests == []


class TestFindGuild:
    @pytest.mark.parametrize(
        "link",
        [
            "https://fresh.warcraftlogs.com/guild/id/774065",
            "fresh.warcraftlogs.com/guild/reports-list/774065/",
            "https://fresh.warcraftlogs.com/guild/rankings/774065/latest?zone=1007",
        ],
    )
    def test_a_guild_link_by_id_looks_on_its_own_site(self, link):
        wcl = _wcl()
        with wcl.install():
            guild = _service().find_guild(link, "abc", "xyz")
        assert guild == GuildMatch(774065, "Amicable", "Gehennas", "eu", "fresh")
        assert wcl.queries[0].url == "https://fresh.warcraftlogs.com/api/v2/client"
        assert wcl.queries[0].variables == {"id": 774065}

    def test_a_guild_link_by_name(self):
        wcl = _wcl()
        with wcl.install():
            guild = _service().find_guild(
                "https://classic.warcraftlogs.com/guild/eu/pyrewood-village/The%20Toads", "a", "b"
            )
        assert guild.game_version == "classic" and wcl.queries[0].url.startswith("https://classic.")
        assert wcl.queries[0].variables == {"name": "The Toads", "serverSlug": "pyrewood-village", "serverRegion": "eu"}

    def test_a_report_link_finds_the_guild_that_logged_it(self):
        wcl = FakeWarcraftLogs().answer("reportData", {"reportData": {"report": {"guild": AMICABLE}}})
        with wcl.install():
            guild = _service().find_guild("https://fresh.warcraftlogs.com/reports/aBcD1234eFgH5678#fight=3", "a", "b")
        assert guild.id == 774065 and wcl.queries[0].variables == {"code": "aBcD1234eFgH5678"}

    def test_a_report_on_another_site_says_so(self):
        wcl = FakeWarcraftLogs().answer("reportData", {"reportData": {"report": None}})
        with wcl.install(), pytest.raises(SetupError, match="no report aBcD1234eFgH5678 on the fresh site"):
            _service(TEMPLATE).find_guild("aBcD1234eFgH5678", "a", "b")

    def test_a_personal_report_has_no_guild(self):
        wcl = FakeWarcraftLogs().answer("reportData", {"reportData": {"report": {"guild": None}}})
        with wcl.install(), pytest.raises(SetupError, match="personal log"):
            _service().find_guild("aBcD1234eFgH5678", "a", "b")

    def test_a_name_with_server_and_region_searches_config_site(self):
        wcl = _wcl()
        service = _service({"wcl_api_url": "https://sod.warcraftlogs.com/api/v2/client"})
        with wcl.install():
            guild = service.find_guild(" Amicable ", "a", "b", server="Pyrewood Village", region="EU")
        assert guild.label == "Amicable on Gehennas (EU)" and guild.game_version == "sod"
        assert wcl.queries[0].variables == {"name": "Amicable", "serverSlug": "pyrewood-village", "serverRegion": "eu"}

    def test_a_chosen_site_wins_over_config(self):
        wcl = _wcl()
        with wcl.install():
            guild = _service().find_guild("774065", "a", "b", game_version="classic")
        assert guild.game_version == "classic" and guild.url == "https://classic.warcraftlogs.com/guild/id/774065"

    def test_an_unknown_guild_says_so(self):
        with _wcl(guild=None).install(), pytest.raises(SetupError, match="no such guild"):
            _service().find_guild("Nobody", "a", "b", server="Gehennas", region="eu")

    @pytest.mark.parametrize(
        ("text", "server", "region", "message"),
        [
            ("", "", "", "Paste a link"),
            ("Amicable", "", "eu", "server and region"),
            ("Amicable", "Gehennas", "mars", "server and region"),
            ("https://fresh.warcraftlogs.com/character/eu/gehennas/toad", "", "", "not a Warcraft Logs guild"),
            ("https://evil.example/guild/id/123?from=warcraftlogs.com", "", "", "not a Warcraft Logs link"),
            ("warcraftlogs.com.evil.example/guild/id/123", "", "", "not a Warcraft Logs link"),
        ],
    )
    def test_input_it_cannot_use_is_refused_before_asking(self, text, server, region, message):
        wcl = FakeWarcraftLogs()
        with wcl.install(), pytest.raises(SetupError, match=message):
            _service().find_guild(text, "a", "b", server=server, region=region)
        assert wcl.requests == []

    def test_an_unknown_site_is_refused(self):
        with pytest.raises(SetupError, match="Unknown Warcraft Logs site"):
            _service().find_guild("774065", "a", "b", game_version="mists")

    def test_bad_keys_and_outages_read_as_setup_errors(self):
        with FakeWarcraftLogs().token(status(401)).install(), pytest.raises(SetupError, match="API keys first"):
            _service().find_guild("774065", "a", "b")
        wcl = FakeWarcraftLogs().answer("guildData", status(404))
        with wcl.install(), pytest.raises(SetupError, match="Could not reach"):
            _service().find_guild("774065", "a", "b")


class TestSave:
    def test_keys_and_guild_are_saved_and_the_template_report_cleared(self):
        store = MemoryConfigStore({**TEMPLATE, "guild_id": 0, "badges": {"disabled": []}})
        guild = GuildMatch(774065, "Amicable", "Gehennas", "eu", "fresh")
        OnboardingService(store).save(" abc ", "xyz", guild)
        assert store.config == {
            "client_id": "abc",
            "client_secret": "xyz",
            "report_id": "",
            "guild_id": 774065,
            "guild_name": "Amicable",
            "guild_server": "Gehennas",
            "wcl_api_url": FRESH_API,
            "badges": {"disabled": []},
        }

    def test_a_guild_on_another_site_moves_imports_there(self):
        store = MemoryConfigStore({"wcl_api_url": FRESH_API})
        OnboardingService(store).save("abc", "xyz", GuildMatch(1, "Toads", "Mograine", "eu", "classic"))
        assert store.config["wcl_api_url"] == "https://classic.warcraftlogs.com/api/v2/client"

    def test_keys_alone_leave_the_guild_alone(self):
        store = MemoryConfigStore({"guild_id": 5, "report_id": "aBcD1234eFgH5678"})
        OnboardingService(store).save("abc", "xyz")
        assert store.config == {
            "guild_id": 5,
            "report_id": "aBcD1234eFgH5678",
            "client_id": "abc",
            "client_secret": "xyz",
        }

    def test_blank_keys_are_not_saved(self):
        store = MemoryConfigStore()
        with pytest.raises(SetupError):
            OnboardingService(store).save("", "xyz")
        assert store.config == {}

    def test_the_json_store_writes_a_config_the_app_loads(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({**TEMPLATE, "guild_logo": "logo.png"}))
        service = OnboardingService(JsonConfigStore(path))
        assert service.needs_setup()
        service.save("abc", "xyz", GuildMatch(774065, "Amicable", "Gehennas", "eu", "fresh"))
        assert not service.needs_setup()
        config = load_config()  # the store pointed the config manager at the file it wrote
        assert config["client_id"] == "abc" and config["client_secret"].get_secret_value() == "xyz"
        assert config["guild_id"] == 774065 and config["report_id"] == "" and config["guild_logo"] == "logo.png"
        assert not path.with_suffix(".json.partial").exists()

    def test_the_json_store_starts_empty_and_reports_a_broken_file(self, tmp_path):
        assert JsonConfigStore(tmp_path / "none.json").read() == {}
        broken = tmp_path / "config.json"
        broken.write_text("{nope")
        with pytest.raises(SetupError, match=r"Could not read config\.json"):
            OnboardingService(JsonConfigStore(broken)).needs_setup()

    def test_the_desktop_uses_config_json(self, tmp_path, monkeypatch):
        from wcl_core import paths

        monkeypatch.setattr(paths, "get_config_path", lambda: tmp_path / "config.json")
        service = OnboardingService.desktop()
        assert isinstance(service.store, JsonConfigStore) and service.store.path == tmp_path / "config.json"

    def test_a_config_without_a_site_gets_a_retail_guild_site(self):
        store = MemoryConfigStore()  # no wcl_api_url: imports go to the loader's default, the fresh site
        OnboardingService(store).save("abc", "xyz", GuildMatch(1, "Method", "Tarren Mill", "eu", "retail"))
        assert store.config["wcl_api_url"] == "https://www.warcraftlogs.com/api/v2/client"

    def test_skipping_the_guild_on_a_new_config_names_no_guild(self, tmp_path):
        path = tmp_path / "config.json"
        OnboardingService(JsonConfigStore(path)).save("abc", "xyz")
        assert json.loads(path.read_text())["guild_id"] == 0
        assert AppContext.from_config_file(str(path)).guild_id is None  # not the loader's built-in guild


class TestReloadConfig:
    def test_the_window_context_takes_the_saved_keys(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps(TEMPLATE))
        ctx = AppContext.from_config_file(str(path))
        handed_out = ctx.config  # what a service was given at start-up
        before = ctx.wcl_client
        OnboardingService(JsonConfigStore(path)).save("abc", "xyz", GuildMatch(1, "Toads", "Gehennas", "eu", "fresh"))
        ctx.reload_config(str(path))
        assert handed_out["client_id"] == "abc" and ctx.guild_id == 1
        assert ctx.wcl_client is not before and ctx.wcl_client.token_manager.client_id == "abc"

    def test_a_config_that_does_not_load_leaves_the_old_one(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"guild_id": 3}))
        ctx = AppContext(config={"client_id": "abc", "client_secret": "xyz"})
        with pytest.raises(ConfigurationError):
            ctx.reload_config(str(path))
        assert ctx.config == {"client_id": "abc", "client_secret": "xyz"}

    def test_a_headless_host_keeps_its_own_client(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"client_id": "abc", "client_secret": "xyz"}))
        client = FakeWarcraftLogs().client()
        ctx = AppContext.headless(client, storage=lambda: None)  # type: ignore[arg-type, return-value]
        ctx.reload_config(str(path))
        assert ctx.wcl_client is client and ctx.config["client_id"] == "abc"
