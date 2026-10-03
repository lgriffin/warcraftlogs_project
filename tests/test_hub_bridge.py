"""The Toads Hub link (phase 4): redeem the bot's one-time code, publish profiles, and let the bot resolve a member.

Everything runs against ``wcl_core.testing.FakeHub`` at the HTTP seam, so the real ``wcl_core.hub`` client and
``wcl_app.bridge`` service do the work.
"""

import json
import logging
import os
import stat

import pytest
import requests
from pydantic import SecretStr
from warcraftlogs_client.services.profiles import MemoryProfileStore
from wcl_core import hub, paths
from wcl_core.common.errors import AuthenticationError, ConfigurationError
from wcl_core.discord_auth import DiscordIdentity, DiscordIdentityStore
from wcl_core.hub import HubError, HubLink, HubLinkStore, HubMember
from wcl_core.testing import FakeHub, FakeResponse, UnexpectedRequest
from wcl_store import RaidScope

from warcraftlogs_client import cli
from warcraftlogs_client.services import (
    AppContext,
    BridgeService,
    HubLinkedNotPublished,
    HubMemberMismatch,
    HubNotLinked,
    IdentityService,
    Profile,
    ProfileDirectory,
    ProfileNotPublished,
    ProfileService,
    ProfileSet,
    member_profile,
)

HUB = "https://hub.toads.test"
LEIGH = "123456789"
TBC = Profile("tbc", "TBC", game_version="fresh", expansions=("The Burning Crusade",))
ERA = Profile("era", "Era", game_version="classic")


@pytest.fixture
def fake_hub(monkeypatch):
    monkeypatch.setenv("TOADS_HUB_URL", HUB)
    fake = FakeHub(HUB)
    with fake.install():
        yield fake


def _identity(tmp_path, discord_id=None):
    store = DiscordIdentityStore(tmp_path / "identity.json")
    if discord_id:
        store.identity = DiscordIdentity(id=discord_id, username="toadlord")
        store.save()
    return IdentityService(store)


def _bridge(tmp_path, discord_id=None, profiles=ProfileSet([TBC, ERA], active="tbc")):
    return BridgeService(
        HubLinkStore(tmp_path / "hub_link.json"),
        identity=_identity(tmp_path, discord_id),
        profiles=ProfileService(MemoryProfileStore(profiles)),
        app_version="9.9",
    )


class TestCodes:
    @pytest.mark.parametrize("typed", ["7kq2-m9xd", " 7KQ2 M9XD ", "7KQ2M9XD"])
    def test_a_code_is_read_however_it_is_typed(self, typed):
        assert hub.link_code(typed) == "7KQ2-M9XD"

    @pytest.mark.parametrize("typed", ["", "7KQ2-M9X", "7KQ2-M9XDD", "OOPS-1234", "7KQ2_M9XD"])
    def test_anything_else_is_refused(self, typed):
        with pytest.raises(ValueError, match="eight letters and digits"):
            hub.link_code(typed)


class TestHubUrl:
    def test_from_the_environment_then_config(self, monkeypatch):
        monkeypatch.delenv("TOADS_HUB_URL", raising=False)
        assert hub.hub_url({"toads_hub_url": "https://toads.example/"}) == "https://toads.example"
        monkeypatch.setenv("TOADS_HUB_URL", "http://localhost:8000")
        assert hub.hub_url({"toads_hub_url": "https://toads.example"}) == "http://localhost:8000"

    @pytest.mark.parametrize("url", ["http://toads.example", "ftp://toads.example", "toads.example"])
    def test_plain_http_is_refused_off_this_machine(self, monkeypatch, url):
        monkeypatch.setenv("TOADS_HUB_URL", url)
        with pytest.raises(ConfigurationError, match="must be https"):
            hub.hub_url()

    def test_no_hub_is_a_configuration_error(self, monkeypatch):
        monkeypatch.delenv("TOADS_HUB_URL", raising=False)
        with pytest.raises(ConfigurationError, match="toads_hub_url"):
            hub.hub_url({})


class TestLink:
    def test_a_code_from_the_bot_links_the_app_and_publishes_its_profiles(self, fake_hub, tmp_path):
        code = fake_hub.issue_code(LEIGH, "toadlord", "Leigh")
        link = _bridge(tmp_path).link(code.lower())
        assert (link.app_id, link.member) == ("app-1", HubMember(LEIGH, "toadlord", "Leigh"))
        assert fake_hub.requests[0].json == {"code": code, "app": {"name": "WarcraftLogs Analyzer", "version": "9.9"}}
        assert fake_hub.requests[1].headers == {"Authorization": "Bearer fake-app-token-1"}
        assert fake_hub.load(LEIGH) == ProfileSet([TBC, ERA], active="tbc").to_dict()
        again = BridgeService(HubLinkStore(tmp_path / "hub_link.json"))
        assert again.is_linked() and again.current() == link

    def test_redeem_returns_the_registration(self, fake_hub):
        link = hub.redeem(HUB, fake_hub.issue_code(LEIGH), "Bot test", "1")
        assert link.hub_url == HUB and fake_hub.apps[link.token.get_secret_value()]["app"] == {
            "name": "Bot test",
            "version": "1",
        }

    def test_a_code_works_once(self, fake_hub, tmp_path):
        code = fake_hub.issue_code(LEIGH)
        _bridge(tmp_path).link(code)
        with pytest.raises(AuthenticationError, match="did not accept that code"):
            _bridge(tmp_path / "other").link(code)

    def test_a_code_issued_to_someone_else_links_nothing(self, fake_hub, tmp_path):
        code = fake_hub.issue_code("555", "othertoad", "Other")
        service = _bridge(tmp_path, discord_id=LEIGH)
        with pytest.raises(HubMemberMismatch, match="issued to Other, but this app is linked to toadlord"):
            service.link(code)
        assert not service.is_linked() and not (tmp_path / "hub_link.json").exists()
        assert fake_hub.apps == {} and fake_hub.profiles == {}  # the Hub was told to drop the app

    def test_linking_again_retires_the_previous_registration(self, fake_hub, tmp_path):
        service = _bridge(tmp_path)
        first = service.link(fake_hub.issue_code(LEIGH))
        second = service.link(fake_hub.issue_code(LEIGH))
        assert service.current() == second != first
        assert list(fake_hub.apps) == [second.token.get_secret_value()]  # the first token publishes nothing now

    def test_relinking_survives_a_hub_that_cannot_retire_the_old_registration(self, fake_hub, tmp_path):
        service = _bridge(tmp_path)
        service.link(fake_hub.issue_code(LEIGH))
        answer = fake_hub._route

        def route(request):
            return FakeResponse(503) if request.url.endswith("/unlink") else answer(request)

        fake_hub._route = route
        second = service.link(fake_hub.issue_code(LEIGH))
        assert service.current() == second

    def test_a_link_whose_profiles_fail_to_publish_says_it_is_linked(self, fake_hub, tmp_path):
        service = _bridge(tmp_path)
        route = fake_hub._route
        fake_hub._route = lambda request: FakeResponse(503) if request.url.endswith("/profiles") else route(request)
        with pytest.raises(HubLinkedNotPublished, match="Linked to the Toads Hub as toad, but the raid profiles"):
            service.link(fake_hub.issue_code(LEIGH))
        assert service.is_linked()  # the code is spent; publishing again is all that is left
        fake_hub._route = route
        service.publish()
        assert fake_hub.load(LEIGH) == ProfileSet([TBC, ERA], active="tbc").to_dict()

    def test_the_linked_discord_account_may_redeem_its_own_code(self, fake_hub, tmp_path):
        assert _bridge(tmp_path, discord_id=LEIGH).link(fake_hub.issue_code(LEIGH)).member.discord_id == LEIGH

    def test_a_malformed_code_never_reaches_the_hub(self, fake_hub, tmp_path):
        with pytest.raises(ValueError):
            _bridge(tmp_path).link("not a code")
        assert fake_hub.requests == []

    @pytest.mark.parametrize(
        ("reply", "error", "message"),
        [
            (requests.ConnectionError(), HubError, "Cannot reach the Toads Hub"),
            (requests.Timeout(), HubError, "timed out"),
            (FakeResponse(500, {"error": "boom"}), HubError, "HTTP 500"),
            (FakeResponse(201, text="<html>"), HubError, "unreadable"),
            (FakeResponse(201, {"app_id": "x"}), HubError, "unreadable"),
            (FakeResponse(410, {"error": "expired"}), AuthenticationError, "expired"),
        ],
    )
    def test_a_hub_that_misbehaves_links_nothing(self, monkeypatch, tmp_path, reply, error, message):
        monkeypatch.setenv("TOADS_HUB_URL", HUB)

        class Broken(FakeHub):
            def _route(self, request):
                if isinstance(reply, BaseException):
                    raise reply
                return reply

        service = _bridge(tmp_path)
        with Broken(HUB).install(), pytest.raises(error, match=message):
            service.link("7KQ2-M9XD")
        assert not service.is_linked()

    def test_the_token_is_never_logged(self, fake_hub, tmp_path, caplog):
        caplog.set_level(logging.DEBUG)
        code = fake_hub.issue_code(LEIGH)
        service = _bridge(tmp_path)
        service.link(code)
        service.publish()
        service.unlink()
        assert "fake-app-token" not in caplog.text and code not in caplog.text
        assert "POST https://hub.toads.test/api/apps/link" in caplog.text
        assert "fake-app-token" not in repr(HubLink.from_reply(HUB, {**_reply(), "token": "fake-app-token-9"}))


def _reply():
    return {"app_id": "a", "token": "t", "member": {"discord_id": LEIGH, "username": "toadlord"}}


class TestPublishAndUnlink:
    def test_publish_replaces_the_members_profiles(self, fake_hub, tmp_path):
        service = _bridge(tmp_path)
        service.link(fake_hub.issue_code(LEIGH))
        service.publish(ProfileSet([ERA], active=None))
        assert fake_hub.load(LEIGH) == {"version": 1, "active": None, "profiles": [ERA.to_dict()]}

    def test_publish_needs_a_link(self, fake_hub, tmp_path):
        with pytest.raises(HubNotLinked):
            _bridge(tmp_path).publish()
        assert fake_hub.requests == []

    def test_without_a_profile_service_an_empty_set_is_published(self, fake_hub, tmp_path):
        service = BridgeService(HubLinkStore(tmp_path / "hub_link.json"))
        service.link(fake_hub.issue_code(LEIGH))
        assert fake_hub.load(LEIGH) is None  # nothing published on link without profiles
        service.publish()
        assert fake_hub.load(LEIGH) == ProfileSet().to_dict()

    def test_a_hub_that_forgot_the_app_asks_for_a_new_code(self, fake_hub, tmp_path):
        service = _bridge(tmp_path)
        service.link(fake_hub.issue_code(LEIGH))
        fake_hub.apps.clear()
        with pytest.raises(AuthenticationError, match="link it again"):
            service.publish()

    def test_unlink_forgets_here_and_on_the_hub(self, fake_hub, tmp_path):
        service = _bridge(tmp_path)
        assert service.unlink() is False  # nothing to forget
        service.link(fake_hub.issue_code(LEIGH))
        assert service.unlink() is True
        assert not service.is_linked() and fake_hub.apps == {}
        assert not (tmp_path / "hub_link.json").exists()

    def test_unlink_forgets_here_even_when_the_hub_is_down(self, fake_hub, tmp_path):
        service = _bridge(tmp_path)
        service.link(fake_hub.issue_code(LEIGH))

        class Down(FakeHub):
            def _route(self, request):
                raise requests.ConnectionError

        with Down(HUB).install():
            assert service.unlink() is False
        assert not service.is_linked()

    def test_the_fake_hub_answers_only_its_own_endpoints(self, fake_hub):
        assert fake_hub.post(f"{HUB}/api/apps/nope", timeout=1).status_code == 401  # who asks comes first
        for url in (f"{HUB}/api/bots/x", "https://elsewhere.test/api/apps/link"):
            with pytest.raises(UnexpectedRequest):
                fake_hub.post(url, timeout=1, headers={"Authorization": "Bearer fake-app-token-1"})
        fake_hub.apps["fake-app-token-1"] = {"app_id": "a", "member": {"discord_id": LEIGH}}
        with pytest.raises(UnexpectedRequest):
            fake_hub.post(f"{HUB}/api/apps/nope", timeout=1, headers={"Authorization": "Bearer fake-app-token-1"})
        with pytest.raises(UnexpectedRequest):
            fake_hub.get(f"{HUB}/api/apps/link", timeout=1)
        assert fake_hub.post(f"{HUB}/api/apps/link", timeout=1, json={"code": "x"}).status_code == 400

    def test_a_hub_that_refuses_errors(self, monkeypatch, tmp_path):
        link = HubLink(HUB, "a", SecretStr("t"), HubMember(LEIGH, "toadlord"))

        class Refusing(FakeHub):
            def _route(self, request):
                return FakeResponse(503)

        with Refusing(HUB).install():
            with pytest.raises(HubError, match="refused the profiles"):
                hub.publish_profiles(link, {})
            with pytest.raises(HubError, match="refused the unlink"):
                hub.revoke(link)

    def test_a_broken_link_file_means_no_link(self, tmp_path):
        (tmp_path / "hub_link.json").write_text("{not json", encoding="utf-8")
        assert HubLinkStore(tmp_path / "hub_link.json").link is None
        for damaged in ({"hub_url": HUB}, {}, [], None, "x", {"hub_url": 3}, {**_reply(), "member": "toad"}):
            (tmp_path / "hub_link.json").write_text(json.dumps(damaged), encoding="utf-8")
            assert HubLinkStore(tmp_path / "hub_link.json").link is None


class TestTheBotResolvesAMember:
    def test_a_member_resolves_to_their_active_or_named_profile(self, fake_hub, tmp_path):
        _bridge(tmp_path).link(fake_hub.issue_code(LEIGH))
        assert member_profile(fake_hub, LEIGH) == TBC
        assert member_profile(fake_hub, LEIGH, "era") == ERA
        assert member_profile(fake_hub, "555") is None

    def test_a_profile_the_member_never_published_is_refused_not_widened(self, fake_hub, tmp_path):
        _bridge(tmp_path).link(fake_hub.issue_code(LEIGH))
        with pytest.raises(ProfileNotPublished, match="'wotlk'"):
            member_profile(fake_hub, LEIGH, "wotlk")
        with pytest.raises(ProfileNotPublished):
            member_profile(fake_hub, "555", "tbc")  # published nothing at all

    def test_the_profile_scopes_the_shared_services(self, fake_hub, tmp_path):
        _bridge(tmp_path).link(fake_hub.issue_code(LEIGH))
        ctx = AppContext.headless(client=None, storage=None, profile=member_profile(fake_hub, LEIGH))
        assert ctx.scope == RaidScope(game_versions=("fresh",), expansions=("The Burning Crusade",))

    def test_a_directory_may_hold_profile_sets(self):
        class Directory(ProfileDirectory):
            def load(self, discord_id):
                return ProfileSet([ERA], active=None)

        assert member_profile(Directory(), LEIGH) is None
        assert member_profile(Directory(), LEIGH, "era") == ERA


class TestCli:
    @pytest.fixture(autouse=True)
    def isolated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "get_hub_link_path", lambda: tmp_path / "hub_link.json")
        monkeypatch.setattr(paths, "get_discord_identity_path", lambda: tmp_path / "identity.json")
        monkeypatch.setattr(AppContext, "from_config_file", classmethod(lambda cls: cls(config={})))

    def _run(self, monkeypatch, *argv):
        monkeypatch.setattr("sys.argv", ["warcraftlogs", "hub", *argv])
        return cli.main()

    def test_link_status_publish_and_unlink(self, fake_hub, monkeypatch, capsys):
        assert self._run(monkeypatch, "status") == 0
        assert "Not linked" in capsys.readouterr().out
        assert self._run(monkeypatch, "link", fake_hub.issue_code(LEIGH, "toadlord", "Leigh")) == 0
        assert "Linked to the Toads Hub as Leigh" in capsys.readouterr().out
        assert self._run(monkeypatch, "status", "--json") == 0
        assert json.loads(capsys.readouterr().out)["member"]["discord_id"] == LEIGH
        assert self._run(monkeypatch, "status") == 0
        assert f"Linked to {HUB} as Leigh." in capsys.readouterr().out
        assert self._run(monkeypatch, "publish") == 0
        assert fake_hub.load(LEIGH) == ProfileSet().to_dict()
        assert self._run(monkeypatch, "unlink") == 0
        assert "Hub link forgotten." in capsys.readouterr().out

    def test_errors_are_explained(self, fake_hub, monkeypatch, capsys):
        assert self._run(monkeypatch) == 1
        assert self._run(monkeypatch, "link", "nope") == 1
        assert "eight letters and digits" in capsys.readouterr().out
        assert self._run(monkeypatch, "publish") == 1
        assert "Link this app" in capsys.readouterr().out
        assert self._run(monkeypatch, "unlink") == 0
        assert capsys.readouterr().out == "Not linked.\n"


class TestWire:
    """The contract's edges: every status the guide allows, the timeout, and what the link file holds."""

    @staticmethod
    def _answering(status, body=None):
        class Answering(FakeHub):
            def _route(self, request):
                return FakeResponse(status, body) if body is not None else FakeResponse(status)

        return Answering(HUB)

    @pytest.mark.parametrize("status", [200, 201])
    def test_redeem_accepts_200_and_201(self, status):
        with self._answering(status, _reply()).install() as fake:
            assert hub.redeem(HUB, "7KQ2-M9XD", "a", "1").app_id == "a"
        assert fake.requests[0].timeout == hub.TIMEOUT == 30

    @pytest.mark.parametrize("status", [400, 404, 410])
    def test_redeem_reads_a_refused_code_as_a_sign_in_failure(self, status):
        with self._answering(status, {}).install(), pytest.raises(AuthenticationError):
            hub.redeem(HUB, "7KQ2-M9XD", "a", "1")

    @pytest.mark.parametrize("status", [200, 204])
    def test_publish_and_revoke_accept_200_and_204(self, status):
        link = HubLink.from_reply(HUB, _reply())
        with self._answering(status).install() as fake:
            hub.publish_profiles(link, {})
            hub.revoke(link)
        assert [r.url for r in fake.requests] == [f"{HUB}/api/apps/profiles", f"{HUB}/api/apps/unlink"]

    def test_revoking_an_app_the_hub_forgot_is_fine(self):
        with self._answering(401).install() as fake:
            hub.revoke(HubLink.from_reply(HUB, _reply()))
        assert len(fake.requests) == 1

    def test_the_link_file_is_written_where_asked_and_readable(self, tmp_path):
        store = HubLinkStore(tmp_path / "nested" / "dir" / "hub_link.json")
        assert store.path == tmp_path / "nested" / "dir" / "hub_link.json"
        store.save(HubLink.from_reply(HUB, _reply()))
        text = store.path.read_text(encoding="utf-8")
        assert text.startswith('{\n  "hub_url"') and json.loads(text)["token"] == "t"
        assert HubLinkStore(store.path).link == store.link
        store.forget()
        store.forget()  # twice is fine
        assert not store.path.exists() and store.link is None

    @pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
    def test_only_the_owner_can_read_the_token(self, tmp_path):
        path = tmp_path / "hub_link.json"
        path.write_text("{}", encoding="utf-8")
        path.chmod(0o644)  # a file an older version left readable
        HubLinkStore(path).save(HubLink.from_reply(HUB, _reply()))
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_a_link_file_that_cannot_be_deleted_stays_linked(self, tmp_path, monkeypatch):
        store = HubLinkStore(tmp_path / "hub_link.json")
        store.save(HubLink.from_reply(HUB, _reply()))

        def refuse(self, missing_ok=False):
            raise PermissionError("read-only disk")

        monkeypatch.setattr(type(store.path), "unlink", refuse)
        with pytest.raises(PermissionError):
            store.forget()
        assert store.link is not None

    def test_links_and_members_are_values(self):
        link = HubLink.from_reply(HUB, _reply())
        with pytest.raises(AttributeError):
            link.app_id = "b"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            link.member.username = "b"  # type: ignore[misc]
        assert link.member.name == "toadlord"

    def test_the_default_store_lives_next_to_the_discord_identity(self, tmp_path, monkeypatch):
        assert paths.get_hub_link_path() == paths.get_discord_identity_path().with_name("hub_link.json")
        monkeypatch.setattr(paths, "get_hub_link_path", lambda: tmp_path / "hub_link.json")
        assert HubLinkStore().path == tmp_path / "hub_link.json"
        assert paths.get_hub_link_path().parent == tmp_path
