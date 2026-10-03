"""wcl_core.testing: the fake Warcraft Logs and Discord that tests use at the HTTP seam."""

import ast
from pathlib import Path

import pytest
import requests
from pydantic import SecretStr
from wcl_core import discord_auth, http
from wcl_core.common.errors import AuthenticationError
from wcl_core.testing import (
    FakeDiscord,
    FakeResponse,
    FakeWarcraftLogs,
    Request,
    UnexpectedRequest,
    grant,
    invalid_json,
    status,
)

REPORT = {"reportData": {"report": {"title": "Karazhan", "owner": {"name": "Toad"}, "startTime": 1, "zone": None}}}


def test_the_docstring_example_runs():
    wcl = FakeWarcraftLogs()
    wcl.answer("reportData", {"reportData": {"report": {"title": "Kara", "owner": {"name": "Toad"}, "startTime": 0}}})
    with wcl.install():
        raid = wcl.client().get_report_metadata("abc")
    assert raid.title == "Kara"
    assert wcl.queries[0].variables == {"code": "abc"}


def test_the_real_client_gets_a_token_then_queries_with_it():
    wcl = FakeWarcraftLogs().token(grant("t0ad"))
    wcl.answer("reportData", REPORT)
    with wcl.install():
        raid = wcl.client("https://fresh.warcraftlogs.com/api/v2/client").get_report_metadata("abc")
    assert (raid.title, raid.owner, raid.game_version) == ("Karazhan", "Toad", "fresh")
    assert [r.method for r in wcl.requests] == ["POST", "POST"]
    assert len(wcl.token_requests) == 1
    assert wcl.token_requests[0].data == {"grant_type": "client_credentials"}
    assert wcl.queries[0].headers["Authorization"] == "Bearer t0ad"
    assert wcl.queries[0].url == "https://fresh.warcraftlogs.com/api/v2/client"
    assert all(r.timeout for r in wcl.requests)


def test_replies_are_taken_in_order_and_the_last_repeats():
    wcl = FakeWarcraftLogs().answer("guildData", {"n": 1}, {"n": 2})
    with wcl.install():
        client = wcl.client()
        seen = [client.run_query("{ guildData }")["data"]["n"] for _ in range(3)]
    assert seen == [1, 2, 2]


def test_the_first_matching_answer_wins_and_a_callable_sees_the_variables():
    wcl = FakeWarcraftLogs()
    wcl.answer("report(", lambda query, variables: {"code": variables["code"]})
    wcl.answer("report", {"code": "never"})
    with wcl.install():
        result = wcl.client().run_query("{ report(code: $code) }", variables={"code": "xyz"})
    assert result == {"data": {"code": "xyz"}}


def test_a_query_nothing_answers_fails_loudly():
    wcl = FakeWarcraftLogs().answer("guildData", {})
    with wcl.install(), pytest.raises(UnexpectedRequest, match="no answer for query"):
        wcl.client().run_query("{ characterData }")


@pytest.mark.parametrize(
    ("method", "url"),
    [("POST", "https://discord.com/api/oauth2/token"), ("GET", "https://www.warcraftlogs.com/api/v2/client")],
)
def test_a_request_to_anything_else_fails_loudly(method, url):
    wcl = FakeWarcraftLogs()
    send = wcl.post if method == "POST" else wcl.get
    with pytest.raises(UnexpectedRequest):
        send(url, timeout=1)
    assert wcl.requests[0].url == url


def test_a_host_that_only_ends_in_the_name_is_not_warcraft_logs():
    with pytest.raises(UnexpectedRequest, match="not Warcraft Logs"):
        FakeWarcraftLogs().post("https://evilwarcraftlogs.com/oauth/token", timeout=1)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (status(401), "Authentication failed (HTTP 401)"),
        (requests.ConnectionError("down"), "Cannot reach"),
        (requests.Timeout("slow"), "timed out"),
        (invalid_json(), "invalid response"),
    ],
)
def test_scripted_token_failures_reach_the_token_manager(reply, message):
    wcl = FakeWarcraftLogs().token(reply)
    with wcl.install(), pytest.raises(AuthenticationError, match=message.replace("(", r"\(").replace(")", r"\)")):
        wcl.client().run_query("{ anything }")


def test_a_graphql_reply_can_be_a_whole_response():
    wcl = FakeWarcraftLogs().answer("x", FakeResponse(200, {"errors": [{"message": "bad"}]}))
    with wcl.install():
        assert wcl.client().run_query("{ x }") == {"errors": [{"message": "bad"}]}


def test_a_failing_status_raises_http_error_with_the_response():
    response = status(403, "nope")
    with pytest.raises(requests.HTTPError) as err:
        response.raise_for_status()
    assert err.value.response is response
    assert response.text == "nope"
    status(204).raise_for_status()  # below 400: no error
    assert FakeResponse(200, {"a": 1}).text == '{"a": 1}'


def test_a_script_needs_a_reply():
    with pytest.raises(ValueError, match="at least one reply"):
        FakeWarcraftLogs().token()


def test_install_puts_back_the_transport_it_found():
    outer, inner = FakeWarcraftLogs(), FakeWarcraftLogs()
    with outer.install():
        with inner.install():
            assert http._transport is inner
        assert http._transport is outer
    assert http._transport is None


def test_fake_and_real_responses_both_satisfy_the_seam_response():
    assert isinstance(FakeResponse(200, {}), http.Response)
    assert isinstance(requests.Response(), http.Response)
    assert not isinstance(object(), http.Response)


def test_each_request_is_recorded_with_what_was_sent():
    wcl = FakeWarcraftLogs().answer("x", {})
    with wcl.install():
        wcl.client().run_query("{ x }", variables={"a": 1})
    [token, query] = wcl.requests
    assert isinstance(query, Request) and (query.method, query.timeout) == ("POST", 30)
    assert (query.query, query.variables) == ("{ x }", {"a": 1})
    assert token.json is None and token.data == {"grant_type": "client_credentials"}


def test_any_transport_can_be_installed():
    """Hosts can install their own transport (a recording proxy, say), not only the shipped fakes."""

    class Echo:
        def post(self, url, *, timeout, **kwargs):
            return FakeResponse(200, {"url": url, "timeout": timeout})

        def get(self, url, *, timeout, **kwargs):
            return FakeResponse(204)

    transport: http.Transport = Echo()
    with http.use(transport):
        assert http.post("https://a", timeout=3).json() == {"url": "https://a", "timeout": 3}
        assert http.get("https://b", timeout=3).status_code == 204


def test_the_seam_without_a_transport_calls_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "post", lambda url, **kw: calls.append(("post", url, kw)) or "p")
    monkeypatch.setattr(requests, "get", lambda url, **kw: calls.append(("get", url, kw)) or "g")
    assert http.post("https://a", timeout=5, json={}) == "p"
    assert http.get("https://b", timeout=6) == "g"
    assert calls == [("post", "https://a", {"timeout": 5, "json": {}}), ("get", "https://b", {"timeout": 6})]


def test_fake_discord_answers_the_identity_with_the_bearer_token(monkeypatch):
    monkeypatch.delenv("DISCORD_OAUTH_URL", raising=False)
    discord = FakeDiscord().user({"id": "42", "username": "toadlord", "global_name": "Toad Lord"})
    with discord.install():
        who = discord_auth.fetch_identity(SecretStr("acc"))
    assert (who.id, who.username, who.global_name) == ("42", "toadlord", "Toad Lord")
    assert discord.requests[0].url == "https://discord.com/api/users/@me"
    assert discord.requests[0].headers["Authorization"] == "Bearer acc"


def test_fake_discord_follows_discord_oauth_url_and_scripts_the_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_OAUTH_URL", "http://localhost:8099/")
    discord = FakeDiscord().token(status(400))
    store = discord_auth.DiscordIdentityStore(tmp_path / "identity.json")
    with discord.install(), pytest.raises(AuthenticationError, match=r"HTTP 400"):
        store.complete_auth("c0de", "app", "verifier")
    assert discord.requests[0].url == "http://localhost:8099/api/oauth2/token"
    assert discord.requests[0].data["code"] == "c0de"


def test_fake_discord_grants_and_links_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("DISCORD_OAUTH_URL", raising=False)
    store = discord_auth.DiscordIdentityStore(tmp_path / "identity.json")
    with FakeDiscord().install():
        who = store.complete_auth("c0de", "app", "verifier")
    assert (who.id, who.username) == ("123456789", "toad")
    assert store.is_linked()


def test_fake_discord_refuses_anything_else(monkeypatch):
    monkeypatch.delenv("DISCORD_OAUTH_URL", raising=False)
    with pytest.raises(UnexpectedRequest, match="no such Discord endpoint"):
        FakeDiscord().get("https://discord.com/api/oauth2/token", timeout=1)


def test_the_shared_packages_reach_http_only_through_the_seam():
    """So a fake installed with ``http.use`` sees every request wcl-core, wcl-store and wcl-app make."""
    packages = Path(__file__).resolve().parent.parent / "packages"
    direct = [
        f"{path.relative_to(packages)}:{node.lineno}"
        for path in sorted(packages.glob("*/src/**/*.py"))
        if path.name != "http.py" or path.parent.name != "wcl_core"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "requests"
        if node.attr in {"get", "post", "put", "patch", "delete", "head", "request", "Session"}
    ]
    assert direct == [], "call wcl_core.http.post/get instead: " + ", ".join(direct)
