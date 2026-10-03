"""Discord identity: the PKCE sign-in in ``wcl_core.discord_auth`` and ``wcl_app.identity.IdentityService``."""

import base64
import hashlib
import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import SecretStr
from wcl_core import discord_auth
from wcl_core.common.errors import AuthenticationError
from wcl_core.discord_auth import DiscordIdentity, DiscordIdentityStore, PkcePair

from warcraftlogs_client.services import DiscordNotConfigured, IdentityService

USER = {"id": "123456789", "username": "toadlord", "global_name": "Leigh", "avatar": "abc"}


class TestPkce:
    def test_challenge_is_the_s256_of_the_verifier(self):
        pair = PkcePair.generate()
        digest = hashlib.sha256(pair.verifier.encode()).digest()
        assert pair.challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert pair.verifier != PkcePair.generate().verifier

    def test_authorize_url_carries_pkce_state_and_identify_only(self, monkeypatch):
        monkeypatch.delenv("DISCORD_OAUTH_URL", raising=False)
        url = discord_auth.build_authorize_url("app", "st4te", "ch4llenge", 9000)
        parsed = urlparse(url)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://discord.com/oauth2/authorize"
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        assert q["client_id"] == "app" and q["state"] == "st4te" and q["scope"] == "identify"
        assert q["code_challenge"] == "ch4llenge" and q["code_challenge_method"] == "S256"
        assert q["redirect_uri"] == "http://127.0.0.1:9000/callback"
        assert "client_secret" not in q

    def test_oauth_url_can_point_at_the_fake_discord(self, monkeypatch):
        monkeypatch.setenv("DISCORD_OAUTH_URL", "http://localhost:8099/")
        assert discord_auth.build_authorize_url("app", "s", "c").startswith("http://localhost:8099/oauth2/authorize?")


class TestDiscordIdentity:
    def test_from_api_and_display_name(self):
        identity = DiscordIdentity.from_api(USER)
        assert identity == DiscordIdentity("123456789", "toadlord", "Leigh", "abc")
        assert identity.display_name == "Leigh"
        assert DiscordIdentity.from_api({"id": 1, "username": "x"}).display_name == "x"
        with pytest.raises(AuthenticationError):
            DiscordIdentity.from_api({"username": "no id"})

    def test_client_id_from_env_then_config(self, monkeypatch):
        monkeypatch.delenv("DISCORD_CLIENT_ID", raising=False)
        assert discord_auth.discord_client_id({}) is None
        assert discord_auth.discord_client_id({"discord_client_id": "cfg"}) == "cfg"
        monkeypatch.setenv("DISCORD_CLIENT_ID", "env")
        assert discord_auth.discord_client_id({"discord_client_id": "cfg"}) == "env"


class TestDiscordIdentityStore:
    def test_nothing_linked_without_a_file(self, tmp_path):
        store = DiscordIdentityStore(tmp_path / "id.json")
        assert not store.is_linked() and store.identity is None

    def test_save_load_and_unlink(self, tmp_path):
        path = tmp_path / "nested" / "id.json"
        store = DiscordIdentityStore(path)
        store.identity = DiscordIdentity.from_api(USER)
        store._access_token = SecretStr("tok")
        store.save()
        again = DiscordIdentityStore(path)
        assert again.is_linked() and again.identity.username == "toadlord"
        assert json.loads(path.read_text())["access_token"] == "tok"
        again.unlink()
        assert not again.is_linked() and not path.exists()
        again.unlink()  # idempotent

    def test_broken_file_means_nothing_linked(self, tmp_path):
        path = tmp_path / "id.json"
        path.write_text("{nope", encoding="utf-8")
        assert not DiscordIdentityStore(path).is_linked()
        path.write_text('{"user": {"username": "no id"}}', encoding="utf-8")
        assert not DiscordIdentityStore(path).is_linked()

    @patch("wcl_core.discord_auth.requests.get")
    @patch("wcl_core.discord_auth.requests.post")
    def test_complete_auth_exchanges_the_code_with_the_verifier_and_reads_who(self, post, get, tmp_path, monkeypatch):
        monkeypatch.delenv("DISCORD_OAUTH_URL", raising=False)
        post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "acc", "refresh_token": "ref"})
        get.return_value = MagicMock(status_code=200, json=lambda: USER)
        store = DiscordIdentityStore(tmp_path / "id.json")

        identity = store.complete_auth("c0de", "app", "verifier", 9000)

        assert identity.id == "123456789" and store.is_linked()
        sent = post.call_args.kwargs["data"]
        assert sent == {
            "grant_type": "authorization_code",
            "code": "c0de",
            "redirect_uri": "http://127.0.0.1:9000/callback",
            "client_id": "app",
            "code_verifier": "verifier",
        }
        assert post.call_args.args[0] == "https://discord.com/api/oauth2/token"
        assert get.call_args.args[0] == "https://discord.com/api/users/@me"
        assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer acc"}
        assert json.loads(store.path.read_text())["user"]["id"] == "123456789"

    @patch("wcl_core.discord_auth.requests.post")
    def test_refused_exchange_links_nothing(self, post, tmp_path):
        post.return_value = MagicMock(status_code=400, json=lambda: {})
        store = DiscordIdentityStore(tmp_path / "id.json")
        with pytest.raises(AuthenticationError, match="HTTP 400"):
            store.complete_auth("c0de", "app", "verifier")
        assert not store.is_linked() and not store.path.exists()

    @patch("wcl_core.discord_auth.requests.get")
    @patch("wcl_core.discord_auth.requests.post")
    def test_refused_identity_links_nothing(self, post, get, tmp_path):
        post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "acc"})
        get.return_value = MagicMock(status_code=401, json=lambda: {})
        store = DiscordIdentityStore(tmp_path / "id.json")
        with pytest.raises(AuthenticationError, match="HTTP 401"):
            store.complete_auth("c0de", "app", "verifier")
        assert not store.is_linked()


class FakeServer:
    def __init__(self, result):
        self._result = result
        self.shut = False

    def wait(self, timeout=None):
        return self._result

    def shutdown(self):
        self.shut = True


def _flow(result):
    """A flow starter whose browser callback already answered with ``result`` (a dict builder on the state)."""
    started = {}

    def start(client_id, port, open_browser):
        started.update(client_id=client_id, port=port, open_browser=open_browser)
        pkce = PkcePair.generate()
        server = FakeServer(result("st4te") if callable(result) else result)
        started["server"] = server
        started["verifier"] = pkce.verifier
        return server, "st4te", pkce

    start.started = started
    return start


class TestIdentityService:
    def test_needs_a_client_id(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DISCORD_CLIENT_ID", raising=False)
        service = IdentityService(DiscordIdentityStore(tmp_path / "id.json"), config={})
        assert service.current() is None and not service.is_linked()
        with pytest.raises(DiscordNotConfigured):
            service.link()

    def test_link_checks_the_state_and_completes_with_the_verifier(self, tmp_path):
        store = DiscordIdentityStore(tmp_path / "id.json")
        flow = _flow(lambda state: {"code": "c0de", "state": state})
        service = IdentityService(store, config={"discord_client_id": "app"}, flow=flow, redirect_port=9001)
        with patch.object(store, "complete_auth", return_value=DiscordIdentity.from_api(USER)) as complete:
            identity = service.link(open_browser=False)
        assert identity.username == "toadlord"
        complete.assert_called_once_with("c0de", "app", flow.started["verifier"], 9001)
        assert flow.started["open_browser"] is False and flow.started["port"] == 9001
        assert flow.started["server"].shut

    @pytest.mark.parametrize(
        ("result", "message"),
        [
            (None, "timed out"),
            ({"error": "access_denied"}, "access_denied"),
            ({"code": "c0de", "state": "forged"}, "wrong state"),
        ],
    )
    def test_link_refuses_a_bad_callback(self, tmp_path, result, message):
        store = DiscordIdentityStore(tmp_path / "id.json")
        service = IdentityService(store, config={"discord_client_id": "app"}, flow=_flow(result))
        with pytest.raises(AuthenticationError, match=message):
            service.link(open_browser=False)
        assert not store.is_linked()

    def test_unlink(self, tmp_path):
        store = DiscordIdentityStore(tmp_path / "id.json")
        store.identity = DiscordIdentity.from_api(USER)
        store.save()
        service = IdentityService(store)
        assert service.is_linked()
        service.unlink()
        assert not service.is_linked() and not store.path.exists()
