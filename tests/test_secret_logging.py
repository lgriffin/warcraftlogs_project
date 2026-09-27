"""REQ-CORE-SEC-001: no client secret, access token or refresh token in any log record, at any level.

Every credential path (config load, client-credentials token, GraphQL call, OAuth code exchange,
refresh, failures and the shared error handler) runs with DEBUG enabled on the root logger, then
each captured record is checked: the rendered message, the raw args, and any traceback text.
"""

import json
import logging
import random
import string
import time
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import SecretStr

from warcraftlogs_client.auth import TokenManager
from warcraftlogs_client.client import WarcraftLogsClient
from warcraftlogs_client.common.errors import AuthenticationError, handle_error
from warcraftlogs_client.config import ConfigManager, load_config
from warcraftlogs_client.user_auth import UserTokenManager

# Random-looking sentinels whose 4-char heads/tails never occur in ordinary log text. They are generated
# rather than written out, so secret scanners (gitleaks, GitGuardian) don't flag this file.
_rng = random.Random(0x5EC)  # fixed seed: the same values on every run
_ALPHABET = string.ascii_letters + string.digits


def _sentinel() -> str:
    return "".join(_rng.choice(_ALPHABET) for _ in range(20))


CLIENT_SECRET = _sentinel()
ACCESS_TOKEN = _sentinel()
REFRESH_TOKEN = _sentinel()
NEW_ACCESS_TOKEN = _sentinel()
NEW_REFRESH_TOKEN = _sentinel()
AUTH_CODE = _sentinel()
SENTINELS = (CLIENT_SECRET, ACCESS_TOKEN, REFRESH_TOKEN, NEW_ACCESS_TOKEN, NEW_REFRESH_TOKEN, AUTH_CODE)


def _record_texts(record: logging.LogRecord) -> list[str]:
    texts = [record.getMessage(), repr(record.msg), repr(record.args)]
    if record.exc_info:
        texts.append(logging.Formatter().formatException(record.exc_info))
    if record.exc_text:
        texts.append(record.exc_text)
    if record.stack_info:
        texts.append(record.stack_info)
    return texts


def assert_no_secret_in_logs(records: list[logging.LogRecord], secrets=SENTINELS) -> None:
    for record in records:
        for text in _record_texts(record):
            for secret in secrets:
                # The full value, and its 4-char head/tail (catches partial "abcd...wxyz" logging).
                assert secret not in text, f"{record.levelname} {record.name}: full secret leaked"
                assert secret[:4] not in text, f"{record.levelname} {record.name}: secret prefix leaked"
                assert secret[-4:] not in text, f"{record.levelname} {record.name}: secret suffix leaked"


def _ok(payload: dict) -> MagicMock:
    resp = MagicMock(status_code=200, text=json.dumps(payload), headers={"Content-Type": "application/json"})
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _fail(status: int, body: str = '{"error": "invalid_grant"}') -> MagicMock:
    resp = MagicMock(status_code=status, text=body)
    resp.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error for url: x", response=resp)
    return resp


@pytest.fixture
def debug_caplog(caplog):
    caplog.set_level(logging.DEBUG)  # root: every logger, every level
    return caplog


@pytest.fixture
def secret_config(tmp_path, monkeypatch):
    monkeypatch.delenv("WARCRAFTLOGS_CLIENT_ID", raising=False)
    monkeypatch.setenv("WARCRAFTLOGS_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.delenv("WARCRAFTLOGS_REPORT_ID", raising=False)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"client_id": "cid", "report_id": "r1"}))
    return str(path)


@pytest.mark.security
@pytest.mark.auth
class TestSecretsNeverLogged:
    def test_config_objects_mask_secret(self, secret_config, debug_caplog):
        cfg = ConfigManager(secret_config).load()
        legacy = load_config(secret_config)
        assert isinstance(cfg.api.client_secret, SecretStr)
        assert cfg.api.client_secret.get_secret_value() == CLIENT_SECRET
        # Anything that stringifies the config (debug dumps, error context) sees only the mask.
        logging.getLogger("test").debug("config=%s legacy=%s", cfg, legacy)
        logging.getLogger("test").debug("repr=%r", cfg.api)
        assert CLIENT_SECRET not in repr(cfg) + str(legacy)
        assert_no_secret_in_logs(debug_caplog.records)

    def test_client_credentials_flow_and_api_call(self, secret_config, debug_caplog):
        config = load_config(secret_config)
        tm = TokenManager(config["client_id"], config["client_secret"])
        with patch("requests.post", return_value=_ok({"access_token": ACCESS_TOKEN, "expires_in": 3600})) as post:
            assert tm.get_token() == ACCESS_TOKEN
        # The secret is actually sent (Basic auth) — it is only kept out of logs.
        assert post.call_args.kwargs["headers"]["Authorization"].startswith("Basic ")
        assert CLIENT_SECRET not in repr(vars(tm))
        assert ACCESS_TOKEN not in repr(vars(tm))

        client = WarcraftLogsClient(tm, cache_enabled=False, api_url="https://example.test/api/v2/client")
        with patch("requests.post", return_value=_ok({"data": {"reportData": {}}})) as post:
            client.run_query("query { x }", use_cache=False, variables={"code": "r1"})
        assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"

        assert debug_caplog.records, "expected the flow to log something at DEBUG/INFO"
        assert_no_secret_in_logs(debug_caplog.records)

    def test_client_credentials_failure_through_error_handler(self, debug_caplog):
        tm = TokenManager("cid", CLIENT_SECRET)
        with patch("requests.post", return_value=_fail(401)), pytest.raises(AuthenticationError) as exc_info:
            tm.get_token()
        handle_error(exc_info.value, context="login", exit_on_critical=False)
        logging.getLogger("test").exception("auth failed", exc_info=exc_info.value)
        assert_no_secret_in_logs(debug_caplog.records)

    def test_oauth_code_exchange_success(self, tmp_path, debug_caplog):
        tm = UserTokenManager(token_path=str(tmp_path / "user_token.json"))
        body = {"access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN, "expires_in": 3600}
        with (
            patch("requests.post", return_value=_ok(body)),
            patch("warcraftlogs_client.user_auth.get_token_url", return_value="https://example.test/oauth/token"),
        ):
            tm.complete_auth(AUTH_CODE, "cid", SecretStr(CLIENT_SECRET))
        assert tm.get_token() == ACCESS_TOKEN
        assert ACCESS_TOKEN not in repr(vars(tm))
        assert REFRESH_TOKEN not in repr(vars(tm))
        assert any("Token exchange" in r.getMessage() for r in debug_caplog.records)
        assert_no_secret_in_logs(debug_caplog.records)

    def test_oauth_code_exchange_failure_through_error_handler(self, tmp_path, debug_caplog):
        tm = UserTokenManager(token_path=str(tmp_path / "user_token.json"))
        with (
            patch("requests.post", return_value=_fail(400)),
            patch("warcraftlogs_client.user_auth.get_token_url", return_value="https://example.test/oauth/token"),
            pytest.raises(AuthenticationError) as exc_info,
        ):
            tm.complete_auth(AUTH_CODE, "cid", CLIENT_SECRET)
        handle_error(exc_info.value, exit_on_critical=False)
        assert_no_secret_in_logs(debug_caplog.records)

    @pytest.mark.parametrize("refresh_status", [200, 401])
    def test_refresh_flow(self, tmp_path, monkeypatch, debug_caplog, refresh_status):
        path = tmp_path / "user_token.json"
        path.write_text(
            json.dumps({"access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN, "expires_at": time.time() - 5})
        )
        monkeypatch.setattr(
            "warcraftlogs_client.config.load_config",
            lambda config_file=None: {"client_id": "cid", "client_secret": SecretStr(CLIENT_SECRET)},
        )
        tm = UserTokenManager(token_path=str(path))
        body = {"access_token": NEW_ACCESS_TOKEN, "refresh_token": NEW_REFRESH_TOKEN, "expires_in": 3600}
        resp = _ok(body) if refresh_status == 200 else _fail(refresh_status)
        with (
            patch("requests.post", return_value=resp) as post,
            patch("warcraftlogs_client.user_auth.get_token_url", return_value="https://example.test/oauth/token"),
        ):
            try:
                assert tm.get_token() == NEW_ACCESS_TOKEN
            except AuthenticationError as e:
                handle_error(e, exit_on_critical=False)
        sent = post.call_args.kwargs["data"]
        assert sent["refresh_token"] == REFRESH_TOKEN
        assert sent["client_secret"] == CLIENT_SECRET
        assert_no_secret_in_logs(debug_caplog.records)

    def test_leak_detector_catches_a_leak(self, debug_caplog):
        """Guard against a vacuous detector: a deliberate leak must be caught."""
        logging.getLogger("test").debug("secret=%s...", CLIENT_SECRET[:4])
        with pytest.raises(AssertionError):
            assert_no_secret_in_logs(debug_caplog.records)
