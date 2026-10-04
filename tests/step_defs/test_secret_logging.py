"""Step definitions for the secret-logging feature (REQ-CORE-SEC-001)."""

import json
import logging
import time

import pytest
from pytest_bdd import given, scenarios, then, when
from wcl_core.testing import FakeWarcraftLogs, grant, status

from tests.test_secret_logging import (
    ACCESS_TOKEN,
    AUTH_CODE,
    CLIENT_SECRET,
    NEW_ACCESS_TOKEN,
    NEW_REFRESH_TOKEN,
    REFRESH_TOKEN,
    assert_no_secret_in_logs,
)
from warcraftlogs_client.auth import TokenManager
from warcraftlogs_client.client import WarcraftLogsClient
from warcraftlogs_client.common.errors import AuthenticationError, handle_error
from warcraftlogs_client.config import load_config
from warcraftlogs_client.user_auth import UserTokenManager

scenarios("secret_logging.feature")


@given("every logger is capturing at DEBUG level", target_fixture="log_capture")
def capture_everything(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


@given("the client secret is supplied through the environment", target_fixture="secret_ctx")
def secret_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WARCRAFTLOGS_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.delenv("WARCRAFTLOGS_CLIENT_ID", raising=False)
    monkeypatch.delenv("WARCRAFTLOGS_REPORT_ID", raising=False)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"client_id": "cid", "report_id": "r1"}))
    config = load_config(str(config_path))
    # user_auth re-reads config for refresh; serve it the same (SecretStr-holding) dict.
    monkeypatch.setattr("warcraftlogs_client.config.load_config", lambda config_file=None: config)
    return {"config": config, "token_path": str(tmp_path / "user_token.json")}


@when("the app authenticates with client credentials and queries the API")
def client_credentials_and_query(secret_ctx):
    config = secret_ctx["config"]
    tm = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(tm, cache_enabled=False)
    wcl = FakeWarcraftLogs().token(grant(ACCESS_TOKEN)).answer("x", {})
    with wcl.install():
        client.run_query("query { x }", use_cache=False)
    assert wcl.queries[-1].headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


@when("the user completes the OAuth flow and the token is later refreshed")
def oauth_then_refresh(secret_ctx):
    config = secret_ctx["config"]
    tm = UserTokenManager(token_path=secret_ctx["token_path"])
    first = {"access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN, "expires_in": 3600}
    second = {"access_token": NEW_ACCESS_TOKEN, "refresh_token": NEW_REFRESH_TOKEN, "expires_in": 3600}
    with FakeWarcraftLogs().token(first, second).install():
        tm.complete_auth(AUTH_CODE, config["client_id"], config["client_secret"])
        tm._expires_at = time.time() - 1
        assert tm.get_token() == NEW_ACCESS_TOKEN


@when("the token server rejects the client credentials and the OAuth code exchange")
def rejected_credentials(secret_ctx):
    config = secret_ctx["config"]
    tm = TokenManager(config["client_id"], config["client_secret"])
    with FakeWarcraftLogs().token(status(401)).install(), pytest.raises(AuthenticationError) as client_err:
        tm.get_token()
    handle_error(client_err.value, context="client credentials", exit_on_critical=False)

    user_tm = UserTokenManager(token_path=secret_ctx["token_path"])
    with FakeWarcraftLogs().token(status(400)).install(), pytest.raises(AuthenticationError) as user_err:
        user_tm.complete_auth(AUTH_CODE, config["client_id"], config["client_secret"])
    handle_error(user_err.value, context="oauth code exchange", exit_on_critical=False)


@then("the credential flows should have logged activity")
def logged_activity(log_capture):
    messages = [r.getMessage() for r in log_capture.records]
    assert any("API request" in m for m in messages)
    assert any("Token exchange" in m for m in messages)


@then("the authentication failures should have been logged")
def failures_logged(log_capture):
    errors = [r for r in log_capture.records if r.levelno >= logging.ERROR]
    assert any("Authentication failed" in r.getMessage() for r in errors)
    assert any("Token exchange failed" in r.getMessage() for r in errors)


@then("no log record at any level should contain a client secret, access token or refresh token")
def no_secret_in_logs(log_capture):
    assert log_capture.records
    assert_no_secret_in_logs(log_capture.records)
