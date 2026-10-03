"""Step definitions for the raid profile and Discord identity requirements (PROF-*, IDENT-* in
guides/identity_and_profiles.md). Each scenario drives the services the desktop, CLI and Toads Hub share."""

import argparse
import base64
import hashlib
import socket
import threading
import webbrowser
from dataclasses import replace
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from wcl_app import AppContext, CharacterService, PlayerService, ProfileSiteUnknown, RaidService
from wcl_app.identity import IdentityService
from wcl_app.profiles import JsonProfileStore, MemoryProfileStore, Profile, ProfileService, ProfileSet
from wcl_core import config, consumes_analysis, paths
from wcl_core.common.errors import AuthenticationError
from wcl_core.discord_auth import DiscordIdentity, DiscordIdentityStore, PkcePair
from wcl_core.testing import FakeDiscord, FakeWarcraftLogs

from warcraftlogs_client import cli

scenarios("profiles.feature")

FRESH = "https://fresh.warcraftlogs.com/api/v2/client"
CONFIG = {"client_id": "id", "client_secret": "secret", "wcl_api_url": FRESH}
TBC = "The Burning Crusade"
DAY = 86_400_000
T0 = 1_790_000_000_000
RAIDS = {  # name: (report id, zone, game version, expansion)
    "Molten Core": ("MoltenCoreMolten", "Molten Core", "fresh", "Classic"),
    "Karazhan": ("KaraKaraKaraKara", "Karazhan", "fresh", TBC),
    "Nowhere Keep": ("NowhereKeepNowhe", "Nowhere Keep", None, None),
}
CODES = {code: name for name, (code, *_) in RAIDS.items()}


def _raid(build_analysis, name: str, n: int = 0, *, game_version=None, expansion=None):
    code, zone, *_ = RAIDS[name]
    analysis = build_analysis(report_id=code, start_time=T0 + n * DAY)
    analysis.metadata = replace(analysis.metadata, zone=zone, game_version=game_version, expansion=expansion)
    return analysis


def _names(rows) -> set[str]:
    return {CODES[row["report_id"]] for row in rows}


@given(
    "a raid database with Molten Core tagged Classic, Karazhan tagged The Burning Crusade and Nowhere Keep untagged",
    target_fixture="world",
)
def raid_database(tmp_path, build_analysis, monkeypatch):
    monkeypatch.delenv("DISCORD_OAUTH_URL", raising=False)
    ctx = AppContext(config=dict(CONFIG), db_path=str(tmp_path / "profiles.db"))
    with ctx.repository() as repo:
        for n, (name, (_, _, version, expansion)) in enumerate(RAIDS.items()):
            repo.import_raid(_raid(build_analysis, name, n, game_version=version, expansion=expansion))
    return {"ctx": ctx, "tmp": tmp_path, "build": build_analysis}


def _era(world, name: str) -> tuple:
    with world["ctx"].repository() as repo:
        row = next(r for r in repo.get_raids_by_source("guild") if r["report_id"] == RAIDS[name][0])
    return row["game_version"], row["expansion"]


@when("Karazhan is imported again with no era")
def reimport_without_era(world):
    with world["ctx"].repository() as repo:
        repo.import_raid(_raid(world["build"], "Karazhan", 1))


@when(parsers.parse('Karazhan is imported again on "{version}" in "{expansion}"'))
def reimport_with_era(world, version, expansion):
    with world["ctx"].repository() as repo:
        repo.import_raid(_raid(world["build"], "Karazhan", 1, game_version=version, expansion=expansion))


@then(parsers.parse('{name} should still be on "{version}" in "{expansion}"'))
@then(parsers.parse('{name} should be on "{version}" in "{expansion}"'))
def raid_era(world, name, version, expansion):
    assert _era(world, name) == (version, expansion)


@then(parsers.parse('{name} should be on "{version}" with no expansion'))
def raid_era_without_expansion(world, name, version):
    assert _era(world, name) == (version, None)


@when(parsers.parse('the guild raids are read in "{expansion}"'), target_fixture="rows")
def read_in(world, expansion):
    from wcl_store import RaidScope

    with world["ctx"].repository() as repo:
        return repo.get_raid_list(scope=RaidScope(expansions=(expansion,)))


@then(parsers.parse("the read should return {first} and {second}"))
def read_returns(rows, first, second):
    assert _names(rows) == {first, second}


@given("no profile is active")
def no_profile(world):
    world["ctx"].use_profile(None)


@then("the raid list, raid count and character history should match unscoped reads of all three raids")
def matches_unscoped(world):
    ctx = world["ctx"]
    assert ctx.scope is None
    with ctx.repository() as repo:
        unscoped = repo.get_raid_list()
        assert _names(RaidService(ctx).list_raids()) == _names(unscoped) == set(RAIDS)
        assert RaidService(ctx).count_raids() == repo.count_raids("guild") == 3
        history = repo.get_character_history("HolyPriest")
        assert PlayerService(ctx).history("HolyPriest").total_raids == history.total_raids == 3


@when(parsers.parse('a profile on "{version}" is activated'))
def activate_version(world, version):
    ctx = world["ctx"]
    assert ctx.wcl_client is not None  # a client built before the switch must not outlive it
    ctx.use_profile(Profile(version, version, game_version=version))


@then(parsers.parse('imports should come from "{url}"'))
def imports_from(world, url):
    assert world["ctx"].api_url == world["ctx"].wcl_client.api_url == url


@given(parsers.parse('the Discord account "{discord_id}" is linked'))
def linked(world, discord_id):
    store = DiscordIdentityStore(world["tmp"] / "identity.json")
    store.identity = DiscordIdentity.from_api({"id": discord_id, "username": "toadlord"})
    store.save()
    world["identity"] = IdentityService(store)


@when(parsers.parse('a profile named "{name}" is created'), target_fixture="profile")
def create_profile(world, name):
    who = world["identity"].current()
    profiles = ProfileService(MemoryProfileStore(), world["ctx"], owner=who.id if who else None)
    return profiles.create(name)


@then(parsers.parse('the profile should be owned by "{discord_id}"'))
def owned_by(profile, discord_id):
    assert profile.owner == discord_id


@given("the raids were stored before eras were read")
def stored_before_eras(world):
    with world["ctx"].repository() as repo:
        for code, *_ in RAIDS.values():
            repo.set_raid_era(code, None, None)
        assert len(repo.get_raids_without_era()) == 3


@when("the stored raids are backfilled")
def backfill(world):
    assert ProfileService(MemoryProfileStore(), world["ctx"]).backfill_eras() == 3


@given("the services were built before any profile was active")
def services_built(world):
    ctx = world["ctx"]
    world["services"] = (RaidService(ctx), ProfileService(MemoryProfileStore(), ctx), PlayerService(ctx))
    world["characters"] = CharacterService(ctx)


@when(parsers.parse('the "{name}" profile becomes active'))
def profile_becomes_active(world, name):
    world["ctx"].use_profile(Profile(name.lower(), name, expansions=(name,)))


@then("the raid list, raid count and character history should hold only Nowhere Keep and Molten Core")
def scoped_reads(world):
    raids, profiles, players = world["services"]
    assert _names(raids.list_raids()) == {"Nowhere Keep", "Molten Core"}
    assert raids.count_raids() == profiles.raid_count() == 2
    assert players.history("HolyPriest").total_raids == 2
    assert world["characters"].dossier("HolyPriest").history.total_raids == 2


@given(parsers.parse('"{name}" on "{version}" is saved as the active profile'))
def saved_active(name, version):
    profile = Profile(name.lower(), name, game_version=version, expansions=(name,))
    JsonProfileStore(paths.get_profiles_path()).save(ProfileSet(profiles=[profile], active=profile.slug))


@when("the desktop and CLI context starts", target_fixture="started")
def desktop_starts(world):
    return AppContext.desktop(with_config=False, db_path=world["ctx"].db_path)


@then(parsers.parse('its active profile should be "{name}"'))
def started_in(started, name):
    assert started.profile is not None and started.profile.name == name
    assert started.scope == started.profile.scope


@when("the CLI runs the consumes command")
def cli_consumes(world, monkeypatch):
    used = world["consumes"] = {}
    monkeypatch.setattr(config, "load_config", lambda path=None: dict(CONFIG))
    monkeypatch.setattr(
        consumes_analysis, "run_consumes_analysis", lambda *a, client=None, **k: used.update(client=client)
    )
    args = argparse.Namespace(raid_ids=["KaraKaraKaraKara"], csv=None, healers=False, md=None)
    assert cli.run_consumes_analysis(args) == 0


@then(parsers.parse('the command should import from "{url}"'))
def command_imports_from(world, url):
    assert world["consumes"]["client"].api_url == url


def _listed(name: str) -> dict:
    code, zone, _, expansion = RAIDS[name]
    return {
        "code": code,
        "title": name,
        "owner": {"name": "Raidlead"},
        "startTime": T0,
        "endTime": T0 + 3_600_000,
        "zone": {"name": zone, "expansion": {"name": expansion} if expansion else None},
    }


@given(parsers.parse("Warcraft Logs lists Molten Core, Karazhan and Nowhere Keep for guild {guild:d}"))
def warcraft_logs_lists(world, guild):
    """The real client on the Anniversary site, answered by the fake Warcraft Logs at the HTTP seam."""
    wcl = FakeWarcraftLogs().answer(
        "reports(guildID", {"reportData": {"reports": {"data": [_listed(n) for n in RAIDS], "has_more_pages": False}}}
    )
    wcl.answer(
        "report(code: $code)", lambda query, variables: {"reportData": {"report": _listed(CODES[variables["code"]])}}
    )
    world["ctx"]._client = wcl.client(FRESH)
    world["wcl"] = wcl


@given("no raid is stored")
def nothing_stored(world):
    with world["ctx"].repository() as repo:
        for code, *_ in RAIDS.values():
            repo.delete_raid(code)
        assert repo.count_raids("guild") == 0


@when(parsers.parse('the "{name}" profile for guild {guild:d} becomes active'))
def guild_profile_becomes_active(world, name, guild):
    world["ctx"].use_profile(Profile("p", name, expansions=(name,), guild_id=guild))


@then(parsers.parse("the guild report list should hold {first} and {second}, asked of guild {guild:d}"))
def guild_list_holds(world, first, second, guild):
    with world["wcl"].install():
        reports = RaidService(world["ctx"]).guild_reports()
    assert [CODES[r["code"]] for r in reports] == [n for n in RAIDS if n in (first, second)]
    assert world["wcl"].queries[-1].variables["guildID"] == guild


@when(parsers.parse("{name} is fetched from Warcraft Logs and saved"))
def fetched_and_saved(world, name):
    ctx = world["ctx"]
    analysis = world["build"](report_id=RAIDS[name][0], start_time=T0)
    with world["wcl"].install():
        analysis.metadata = ctx.wcl_client.get_report_metadata(RAIDS[name][0])
    RaidService(ctx).save(analysis)


@then(parsers.parse("the profile's raid list should hold {name} only"))
def profile_lists_only(world, name):
    assert _names(RaidService(world["ctx"]).list_raids()) == {name}


@then("importing the guild's new reports should fail without asking Warcraft Logs anything")
def import_refused(world):
    with world["wcl"].install(), pytest.raises(ProfileSiteUnknown):
        RaidService(world["ctx"]).import_new(9)
    assert world["wcl"].requests == []


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@when(
    parsers.parse('the user signs in with Discord in the browser for the application "{client_id}"'),
    target_fixture="sign_in",
)
def browser_sign_in(world, client_id, monkeypatch):
    """The whole desktop sign-in: IdentityService.link starts the real loopback server and opens the authorize URL;
    the fake browser approves by calling back with a code and the state it was given; Discord's token and user
    endpoints answer through the fake Discord in wcl_core.testing."""
    seen: dict = {}

    def browser(url):
        seen["url"] = url
        query = parse_qs(urlparse(url).query)
        callback = f"{query['redirect_uri'][0]}?code=c0de&state={query['state'][0]}"
        threading.Thread(target=lambda: urlopen(callback, timeout=5).close(), daemon=True).start()  # noqa: S310
        return True

    discord = FakeDiscord().user({"id": "123456789", "username": "toadlord"})
    monkeypatch.setattr(webbrowser, "open", browser)
    store = DiscordIdentityStore(world["tmp"] / "identity.json")
    service = IdentityService(store, config={"discord_client_id": client_id}, redirect_port=_free_port())
    with discord.install():
        service.link(open_browser=True, timeout=10)
    seen["service"] = service
    seen["sent"] = discord.requests[0].data
    return seen


@then("the browser should have asked for the code with an S256 challenge and the identify scope only")
def asked_with_pkce(sign_in):
    query = {k: v[0] for k, v in parse_qs(urlparse(sign_in["url"]).query).items()}
    assert query["response_type"] == "code" and query["scope"] == "identify"
    assert query["code_challenge_method"] == "S256" and "client_secret" not in query
    sign_in["challenge"] = query["code_challenge"]


@then("the code should have been exchanged with the challenge's verifier and no client secret")
def exchanged(sign_in):
    sent = sign_in["sent"]
    digest = hashlib.sha256(sent["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == sign_in["challenge"]
    assert sent["grant_type"] == "authorization_code" and sent["code"] == "c0de"
    assert "client_secret" not in sent


@then(parsers.parse('the Discord account "{discord_id}" should be linked'))
def account_linked(sign_in, discord_id):
    current = sign_in["service"].current()
    assert sign_in["service"].is_linked() and current is not None and current.id == discord_id


ANSWERS = {
    "with a forged state": {"code": "c0de", "state": "forged"},
    "with access denied": {"error": "access_denied"},
    "with nothing": None,
}


class _Server:
    def __init__(self, answer):
        self.answer = answer

    def wait(self, timeout=None):
        return self.answer

    def shutdown(self):
        """The fake callback server holds no socket."""


@when(parsers.parse("the Discord callback comes back {answer}"), target_fixture="attempt")
def callback_comes_back(world, answer):
    store = DiscordIdentityStore(world["tmp"] / "identity.json")

    def flow(client_id, port, open_browser):
        return _Server(ANSWERS[answer]), "st4te", PkcePair.generate()

    service = IdentityService(store, config={"discord_client_id": "app"}, flow=flow)
    with pytest.raises(AuthenticationError) as failure:
        service.link(open_browser=False)
    return {"store": store, "error": str(failure.value)}


@then(parsers.parse('the sign-in should fail with "{message}"'))
def fails_with(attempt, message):
    assert message in attempt["error"]


@then("no Discord account should be linked")
def nothing_linked(attempt):
    assert not attempt["store"].is_linked()


@given(parsers.parse('DISCORD_OAUTH_URL is "{url}"'))
def oauth_url(monkeypatch, url):
    monkeypatch.setenv("DISCORD_OAUTH_URL", url)


@then(parsers.parse('the browser should have opened "{prefix}"'))
def opened(sign_in, prefix):
    assert sign_in["url"].startswith(prefix + "?")
