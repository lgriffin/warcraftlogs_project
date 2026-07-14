"""Step definitions for API authentication feature."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.auth import TokenManager
from warcraftlogs_client.common.errors import AuthenticationError

scenarios("auth.feature")


@given(
    parsers.parse('a token manager with client_id "{cid}" and client_secret "{csec}"'),
    target_fixture="auth_ctx",
)
def token_manager(cid, csec):
    return {"tm": TokenManager(cid, csec), "post_mock": None}


@given(
    parsers.parse('a token manager with an expired token "{token}"'),
    target_fixture="auth_ctx",
)
def expired_token_manager(token):
    tm = TokenManager("test_id", "test_secret")
    tm.access_token = token
    tm.token_expiry = 0
    return {"tm": tm, "post_mock": None}


@given(
    parsers.parse('the auth server will respond with token "{token}" expiring in {seconds:d} seconds'),
)
def mock_success_response(auth_ctx, token, seconds):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": token, "expires_in": seconds}
    mock_resp.raise_for_status.return_value = None
    auth_ctx["post_mock"] = mock_resp


@given(parsers.parse("the auth server will return HTTP {status:d}"))
def mock_http_error(auth_ctx, status):
    mock_resp = MagicMock()
    mock_resp.status_code = status
    http_error = requests.HTTPError(response=mock_resp)
    mock_resp.raise_for_status.side_effect = http_error
    auth_ctx["post_mock"] = mock_resp


@given("the auth server is unreachable")
def mock_connection_error(auth_ctx):
    auth_ctx["post_mock"] = "connection_error"


@given("the auth server will time out")
def mock_timeout(auth_ctx):
    auth_ctx["post_mock"] = "timeout"


@given("the auth server will return invalid JSON")
def mock_invalid_json(auth_ctx):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.side_effect = ValueError("Invalid JSON")
    auth_ctx["post_mock"] = mock_resp


@when("a token is requested", target_fixture="token_result")
def request_token(auth_ctx):
    mock = auth_ctx["post_mock"]
    if mock == "connection_error":
        side_effect = requests.ConnectionError("unreachable")
    elif mock == "timeout":
        side_effect = requests.Timeout("timed out")
    else:
        side_effect = None

    with patch("requests.post", return_value=mock, side_effect=side_effect) as patched:
        try:
            token = auth_ctx["tm"].get_token()
            return {"token": token, "error": None, "mock": patched}
        except AuthenticationError as e:
            return {"token": None, "error": e, "mock": patched}


@when("a token is requested twice", target_fixture="token_result")
def request_token_twice(auth_ctx):
    with patch("requests.post", return_value=auth_ctx["post_mock"]) as patched:
        auth_ctx["tm"].get_token()
        auth_ctx["tm"].get_token()
        return {"token": None, "error": None, "mock": patched}


@then(parsers.parse('the token should be "{expected}"'))
def check_token(token_result, expected):
    assert token_result["token"] == expected


@then("the auth server should have been called once")
def check_called_once(token_result):
    assert token_result["mock"].call_count == 1


@then(parsers.parse('an authentication error should be raised with message containing "{text}"'))
def check_auth_error(token_result, text):
    assert token_result["error"] is not None
    assert text.lower() in str(token_result["error"]).lower()
