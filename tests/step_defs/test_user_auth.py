"""Step definitions for user authentication feature."""

import json
import time
from unittest.mock import MagicMock, patch

import requests
from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.common.errors import AuthenticationError
from warcraftlogs_client.user_auth import UserTokenManager

scenarios("user_auth.feature")


@given("no token file exists", target_fixture="user_auth_ctx")
def no_token(tmp_path):
    token_path = str(tmp_path / "user_token.json")
    tm = UserTokenManager(token_path=token_path)
    return {"tm": tm, "path": token_path, "post_mock": None}


@given(
    parsers.parse('a saved token file with access_token "{token}" expiring in {seconds:d} seconds'),
    target_fixture="user_auth_ctx",
)
def saved_valid_token(tmp_path, token, seconds):
    token_path = str(tmp_path / "user_token.json")
    data = {
        "access_token": token,
        "refresh_token": "some_refresh",
        "expires_at": time.time() + seconds,
    }
    with open(token_path, "w") as f:
        json.dump(data, f)
    tm = UserTokenManager(token_path=token_path)
    return {"tm": tm, "path": token_path, "post_mock": None}


@given(
    parsers.parse('a saved token file with an expired access_token and refresh_token "{refresh}"'),
    target_fixture="user_auth_ctx",
)
def saved_expired_token(tmp_path, refresh):
    token_path = str(tmp_path / "user_token.json")
    data = {
        "access_token": "expired_token",
        "refresh_token": refresh,
        "expires_at": 0,
    }
    with open(token_path, "w") as f:
        json.dump(data, f)
    tm = UserTokenManager(token_path=token_path)
    return {"tm": tm, "path": token_path, "post_mock": None}


@given("a corrupted token file", target_fixture="user_auth_ctx")
def corrupted_token(tmp_path):
    token_path = str(tmp_path / "user_token.json")
    with open(token_path, "w") as f:
        f.write("{corrupted data not valid json!!!")
    tm = UserTokenManager(token_path=token_path)
    return {"tm": tm, "path": token_path, "post_mock": None}


@given(
    parsers.parse(
        'the token server will respond with access_token "{access}" and refresh_token "{refresh}" expiring in {seconds:d} seconds'
    ),
)
def mock_token_success(user_auth_ctx, access, refresh, seconds):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": seconds,
    }
    user_auth_ctx["post_mock"] = mock_resp


@given(parsers.parse("the token server will return HTTP {status:d} on refresh"))
def mock_refresh_failure(user_auth_ctx, status):
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.text = "Bad Request"
    user_auth_ctx["post_mock"] = mock_resp


@given("the token server is unreachable")
def mock_unreachable(user_auth_ctx):
    user_auth_ctx["post_mock"] = "connection_error"


@when(
    parsers.parse('the auth flow completes with code "{code}"'),
    target_fixture="user_token_result",
)
def complete_auth_flow(user_auth_ctx, code):
    mock = user_auth_ctx["post_mock"]
    if mock == "connection_error":
        with patch("requests.post", side_effect=requests.ConnectionError("unreachable")):
            try:
                user_auth_ctx["tm"].complete_auth(code, "cid", "csec")
                return {"error": None}
            except AuthenticationError as e:
                return {"error": e}

    with patch("requests.post", return_value=mock):
        try:
            user_auth_ctx["tm"].complete_auth(code, "cid", "csec")
            return {"error": None}
        except AuthenticationError as e:
            return {"error": e}


@when("a new token manager loads from the same path", target_fixture="user_auth_ctx")
def reload_token_manager(user_auth_ctx):
    new_tm = UserTokenManager(token_path=user_auth_ctx["path"])
    user_auth_ctx["tm"] = new_tm
    return user_auth_ctx


@when("the user requests a token", target_fixture="user_token_result")
def request_user_token(user_auth_ctx, monkeypatch):
    mock = user_auth_ctx["post_mock"]
    config_mock = {"client_id": "cid", "client_secret": "csec"}
    monkeypatch.setattr("warcraftlogs_client.config.load_config", lambda config_file=None: config_mock)
    with (
        patch("requests.post", return_value=mock),
        patch("warcraftlogs_client.user_auth.get_token_url", return_value="http://fake/oauth/token"),
    ):
        try:
            token = user_auth_ctx["tm"].get_token()
            return {"token": token, "error": None}
        except (AuthenticationError, RuntimeError) as e:
            return {"token": None, "error": e}


@when("the user revokes authentication")
def revoke_auth(user_auth_ctx):
    user_auth_ctx["tm"].revoke()


@then("the user should be authenticated")
def check_authenticated(user_auth_ctx):
    assert user_auth_ctx["tm"].is_authenticated()


@then("the user should not be authenticated")
def check_not_authenticated(user_auth_ctx):
    assert not user_auth_ctx["tm"].is_authenticated()


@then("the token file should exist")
def check_file_exists(user_auth_ctx):
    import os

    assert os.path.exists(user_auth_ctx["path"])


@then("the token file should not exist")
def check_file_not_exists(user_auth_ctx):
    import os

    assert not os.path.exists(user_auth_ctx["path"])


@then(parsers.parse('the token should be "{expected}"'))
def check_user_token(user_token_result, expected):
    assert user_token_result["token"] == expected


@then(parsers.parse('an authentication error should be raised with message containing "{text}"'))
def check_user_auth_error(user_token_result, text):
    assert user_token_result["error"] is not None
    assert text.lower() in str(user_token_result["error"]).lower()


@then("the user should not be authenticated after revocation")
def check_not_authenticated_after_revoke(user_auth_ctx):
    assert not user_auth_ctx["tm"].is_authenticated()
