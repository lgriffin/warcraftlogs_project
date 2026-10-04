"""Step definitions for API authentication feature, against the fake Warcraft Logs in ``wcl_core.testing``."""

import requests
from pydantic import SecretStr
from pytest_bdd import given, parsers, scenarios, then, when
from wcl_core.testing import FakeWarcraftLogs, grant, invalid_json, status

from warcraftlogs_client.auth import TokenManager
from warcraftlogs_client.common.errors import AuthenticationError

scenarios("auth.feature")


@given(
    parsers.parse('a token manager with client_id "{cid}" and client_secret "{csec}"'),
    target_fixture="auth_ctx",
)
def token_manager(cid, csec):
    return {"tm": TokenManager(cid, csec), "wcl": FakeWarcraftLogs()}


@given(
    parsers.parse('a token manager with an expired token "{token}"'),
    target_fixture="auth_ctx",
)
def expired_token_manager(token):
    tm = TokenManager("test_id", "test_secret")
    tm.access_token = SecretStr(token)
    tm.token_expiry = 0
    return {"tm": tm, "wcl": FakeWarcraftLogs()}


@given(parsers.parse('the auth server will respond with token "{token}" expiring in {seconds:d} seconds'))
def server_grants(auth_ctx, token, seconds):
    auth_ctx["wcl"].token(grant(token, seconds))


@given(parsers.parse("the auth server will return HTTP {code:d}"))
def server_refuses(auth_ctx, code):
    auth_ctx["wcl"].token(status(code))


@given("the auth server is unreachable")
def server_unreachable(auth_ctx):
    auth_ctx["wcl"].token(requests.ConnectionError("unreachable"))


@given("the auth server will time out")
def server_times_out(auth_ctx):
    auth_ctx["wcl"].token(requests.Timeout("timed out"))


@given("the auth server will return invalid JSON")
def server_sends_garbage(auth_ctx):
    auth_ctx["wcl"].token(invalid_json())


def _request(auth_ctx, times):
    with auth_ctx["wcl"].install():
        try:
            tokens = [auth_ctx["tm"].get_token() for _ in range(times)]
        except AuthenticationError as e:
            return {"token": None, "error": e, "wcl": auth_ctx["wcl"]}
    return {"token": tokens[-1], "error": None, "wcl": auth_ctx["wcl"]}


@when("a token is requested", target_fixture="token_result")
def request_token(auth_ctx):
    return _request(auth_ctx, 1)


@when("a token is requested twice", target_fixture="token_result")
def request_token_twice(auth_ctx):
    return _request(auth_ctx, 2)


@then(parsers.parse('the token should be "{expected}"'))
def check_token(token_result, expected):
    assert token_result["token"] == expected


@then("the auth server should have been called once")
def check_called_once(token_result):
    assert len(token_result["wcl"].token_requests) == 1


@then(parsers.parse('an authentication error should be raised with message containing "{text}"'))
def check_auth_error(token_result, text):
    assert token_result["error"] is not None
    assert text.lower() in str(token_result["error"]).lower()
