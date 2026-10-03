"""Step definitions for the raid profile and Discord identity requirements (PROF-*, IDENT-* in
guides/identity_and_profiles.md). Each scenario drives the services the desktop, CLI and Toads Hub share."""

from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from wcl_app import AppContext, CharacterService, PlayerService, RaidService
from wcl_app.identity import IdentityService
from wcl_app.profiles import JsonProfileStore, MemoryProfileStore, Profile, ProfileService, ProfileSet
from wcl_core import discord_auth, paths
from wcl_core.common.errors import AuthenticationError
from wcl_core.discord_auth import DiscordIdentity, DiscordIdentityStore, PkcePair

scenarios("profiles.feature")

FRESH = "https://fresh.warcraftlogs.com/api/v2/client"
TBC = "The Burning Crusade"
DAY = 86_400_000
T0 = 1_790_000_000_000
RAIDS = {  # name: (report id, zone, game version, expansion)
    "Molten Core": ("MoltenCoreMolten", "Molten Core", "fresh", "Classic"),
    "Karazhan": ("KaraKaraKaraKara", "Karazhan", "fresh", TBC),
    "Nowhere Keep": ("NowhereKeepNowhe", "Nowhere Keep", None, None),
}
CODES = {code: name for name, (code, *_) in RAIDS.items()}
PORT = 9000


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
    ctx = AppContext(config={"wcl_api_url": FRESH}, db_path=str(tmp_path / "profiles.db"))
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
    world["ctx"].use_profile(Profile(version, version, game_version=version))


@then(parsers.parse('imports should come from "{url}"'))
def imports_from(world, url):
    assert world["ctx"].api_url == url


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


@given(parsers.parse('"{name}" is saved as the active profile'))
def saved_active(name):
    profile = Profile(name.lower(), name, expansions=(name,))
    JsonProfileStore(paths.get_profiles_path()).save(ProfileSet(profiles=[profile], active=profile.slug))


@when("the desktop and CLI context starts", target_fixture="started")
def desktop_starts(world):
    return AppContext.desktop(with_config=False, db_path=world["ctx"].db_path)


@then(parsers.parse('its active profile should be "{name}"'))
def started_in(started, name):
    assert started.profile is not None and started.profile.name == name
    assert started.scope == started.profile.scope


@when(parsers.parse('the Discord sign-in starts for the application "{client_id}"'), target_fixture="sign_in")
def sign_in_starts(client_id):
    pkce = PkcePair.generate()
    url = discord_auth.build_authorize_url(client_id, "st4te", pkce.challenge, PORT)
    return {"pkce": pkce, "url": url, "client_id": client_id}


@then("the sign-in should ask for the code with an S256 challenge and the identify scope only")
def asks_with_pkce(sign_in):
    query = {k: v[0] for k, v in parse_qs(urlparse(sign_in["url"]).query).items()}
    assert query["response_type"] == "code" and query["scope"] == "identify"
    assert query["code_challenge"] == sign_in["pkce"].challenge and query["code_challenge_method"] == "S256"
    assert "client_secret" not in query


class _Answer:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


@when(parsers.parse('Discord answers with the code "{code}"'))
def discord_answers(world, sign_in, code, monkeypatch):
    sent = sign_in["sent"] = {}

    def post(url, data=None, **kwargs):
        sent.update(data or {})
        return _Answer(200, {"access_token": "acc", "refresh_token": "ref"})

    monkeypatch.setattr(discord_auth.requests, "post", post)
    monkeypatch.setattr(discord_auth.requests, "get", lambda *a, **k: _Answer(200, {"id": "1", "username": "toad"}))
    store = DiscordIdentityStore(world["tmp"] / "identity.json")
    sign_in["identity"] = store.complete_auth(code, sign_in["client_id"], sign_in["pkce"].verifier, PORT)


@then("the code should be exchanged with the verifier and no client secret")
def exchanged(sign_in):
    sent = sign_in["sent"]
    assert sent["grant_type"] == "authorization_code" and sent["code_verifier"] == sign_in["pkce"].verifier
    assert "client_secret" not in sent and sign_in["identity"].id == "1"


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


@then(parsers.parse('the sign-in should open "{prefix}"'))
def opens(sign_in, prefix):
    assert sign_in["url"].startswith(prefix + "?")
