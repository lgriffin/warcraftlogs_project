"""Step definitions for configuration management feature."""

import json

from pytest_bdd import given, parsers, scenarios, then, when

from warcraftlogs_client.config import ConfigManager

scenarios("configuration.feature")


@given(
    parsers.parse('a config file with client_id "{cid}" and client_secret "{csec}"'),
    target_fixture="config_ctx",
)
def config_with_creds(tmp_path, cid, csec):
    cfg = {"client_id": cid, "client_secret": csec, "report_id": "r1", "guild_id": 1}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    return {"path": str(path)}


@given("a config file with minimal required fields", target_fixture="config_ctx")
def config_minimal(tmp_path):
    cfg = {"client_id": "id", "client_secret": "secret", "report_id": "r1", "guild_id": 1}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    return {"path": str(path)}


@given(
    parsers.parse("a config file with healer_min_healing set to {value:d}"),
    target_fixture="config_ctx",
)
def config_with_threshold(tmp_path, value):
    cfg = {
        "client_id": "id",
        "client_secret": "secret",
        "report_id": "r1",
        "guild_id": 1,
        "role_thresholds": {"healer_min_healing": value},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    return {"path": str(path)}


@given("a nonexistent config file path", target_fixture="config_ctx")
def config_nonexistent(tmp_path):
    return {"path": str(tmp_path / "nonexistent.json")}


@given(parsers.parse('environment variable "{var}" is set to "{val}"'))
def set_env_var(monkeypatch, var, val):
    monkeypatch.setenv(var, val)


@when("the configuration is loaded", target_fixture="load_result")
def load_config(config_ctx):
    mgr = ConfigManager(config_ctx["path"])
    try:
        cfg = mgr.load()
        return {"config": cfg, "manager": mgr, "error": None}
    except Exception as e:
        return {"config": None, "manager": mgr, "error": e}


@when("the configuration is loaded twice", target_fixture="load_result")
def load_config_twice(config_ctx):
    mgr = ConfigManager(config_ctx["path"])
    cfg1 = mgr.load()
    cfg2 = mgr.load()
    return {"config": cfg1, "config2": cfg2, "error": None}


@then(parsers.parse('the API client_id should be "{expected}"'))
def check_client_id(load_result, expected):
    assert load_result["config"] is not None
    assert load_result["config"].api.client_id == expected


@then(parsers.parse('the API client_secret should be "{expected}"'))
def check_client_secret(load_result, expected):
    assert load_result["config"].api.client_secret == expected


@then(parsers.parse("healer_min_healing should be {value:d}"))
def check_healer_threshold(load_result, value):
    assert load_result["config"].role_thresholds.healer_min_healing == value


@then(parsers.parse("tank_min_taken should be {value:d}"))
def check_tank_taken(load_result, value):
    assert load_result["config"].role_thresholds.tank_min_taken == value


@then(parsers.parse("tank_min_mitigation should be {value:d}"))
def check_tank_mitigation(load_result, value):
    assert load_result["config"].role_thresholds.tank_min_mitigation == value


@then("both loads should return valid config")
def check_both_valid(load_result):
    assert load_result["config"] is not None
    assert load_result["config2"] is not None


@then("a configuration error should be raised")
def check_error(load_result):
    assert load_result["error"] is not None
