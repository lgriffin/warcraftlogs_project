"""Tests for configuration loading, validation, and env var overrides."""

import json
import os

import pytest

from warcraftlogs_client.common.errors import ConfigurationError
from warcraftlogs_client.config import (
    AppConfig,
    ConfigManager,
    get_app_config,
    get_config_manager,
    load_config,
)


class TestConfigManagerLoad:
    def test_valid_file(self, config_file):
        mgr = ConfigManager(config_file)
        cfg = mgr.load()
        assert isinstance(cfg, AppConfig)
        assert cfg.api.client_id == "test_id"
        assert cfg.api.client_secret == "test_secret"
        assert cfg.api.report_id == "test_report"

    def test_missing_file(self, tmp_path):
        mgr = ConfigManager(str(tmp_path / "nonexistent.json"))
        with pytest.raises(ConfigurationError):
            mgr.load()

    def test_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        mgr = ConfigManager(str(bad))
        with pytest.raises(ConfigurationError):
            mgr.load()

    def test_missing_credentials(self, tmp_path, monkeypatch):
        monkeypatch.delenv("WARCRAFTLOGS_CLIENT_ID", raising=False)
        monkeypatch.delenv("WARCRAFTLOGS_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("WARCRAFTLOGS_REPORT_ID", raising=False)
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"guild_id": 1}))
        mgr = ConfigManager(str(cfg_path))
        with pytest.raises(ConfigurationError, match="Missing required"):
            mgr.load()

    def test_caching(self, config_file):
        mgr = ConfigManager(config_file)
        c1 = mgr.load()
        c2 = mgr.load()
        assert c1 is c2


class TestEnvVarOverrides:
    def test_env_vars_override_file(self, config_file, monkeypatch):
        monkeypatch.setenv("WARCRAFTLOGS_CLIENT_ID", "env_id")
        monkeypatch.setenv("WARCRAFTLOGS_CLIENT_SECRET", "env_secret")
        monkeypatch.setenv("WARCRAFTLOGS_REPORT_ID", "env_report")
        mgr = ConfigManager(config_file)
        cfg = mgr.load()
        assert cfg.api.client_id == "env_id"
        assert cfg.api.client_secret == "env_secret"
        assert cfg.api.report_id == "env_report"

    def test_env_vars_supply_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WARCRAFTLOGS_CLIENT_ID", "env_id")
        monkeypatch.setenv("WARCRAFTLOGS_CLIENT_SECRET", "env_secret")
        monkeypatch.setenv("WARCRAFTLOGS_REPORT_ID", "env_report")
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({}))
        mgr = ConfigManager(str(cfg_path))
        cfg = mgr.load()
        assert cfg.api.client_id == "env_id"


class TestDefaults:
    def test_default_values(self, config_file):
        mgr = ConfigManager(config_file)
        cfg = mgr.load()
        assert cfg.cache_enabled is True
        assert cfg.cache_dir == ".cache"
        assert cfg.reports_dir == "reports"
        assert cfg.default_region == "EU"

    def test_default_role_thresholds(self, config_file):
        mgr = ConfigManager(config_file)
        cfg = mgr.load()
        assert cfg.role_thresholds.healer_min_healing == 50000
        assert cfg.role_thresholds.tank_min_taken == 150000
        assert cfg.role_thresholds.tank_min_mitigation == 40

    def test_custom_role_thresholds(self, tmp_path):
        cfg_data = {
            "client_id": "x", "client_secret": "y", "report_id": "z",
            "role_thresholds": {"healer_min_healing": 100_000},
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(cfg_data))
        mgr = ConfigManager(str(path))
        cfg = mgr.load()
        assert cfg.role_thresholds.healer_min_healing == 100_000

    def test_guild_id_non_integer_defaults(self, tmp_path):
        cfg_data = {
            "client_id": "x", "client_secret": "y", "report_id": "z",
            "guild_id": "not_a_number",
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(cfg_data))
        mgr = ConfigManager(str(path))
        cfg = mgr.load()
        assert cfg.api.guild_id == 774065

    def test_guild_id_custom(self, config_file):
        mgr = ConfigManager(config_file)
        cfg = mgr.load()
        assert cfg.api.guild_id == 12345


class TestLegacyFormat:
    def test_load_config_returns_dict(self, config_file):
        mgr = get_config_manager(config_file)
        result = load_config(config_file)
        assert isinstance(result, dict)
        assert result["client_id"] == "test_id"
        assert "role_thresholds" in result

    def test_get_role_thresholds(self, config_file):
        mgr = ConfigManager(config_file)
        mgr.load()
        thresholds = mgr.get_role_thresholds()
        assert thresholds["healer_min_healing"] == 50000


class TestSingleton:
    def test_get_config_manager_caches(self, config_file):
        m1 = get_config_manager(config_file)
        m2 = get_config_manager()
        assert m1 is m2

    def test_get_config_manager_new_file_replaces(self, config_file, tmp_path):
        m1 = get_config_manager(config_file)
        other = tmp_path / "other.json"
        other.write_text(json.dumps({
            "client_id": "a", "client_secret": "b", "report_id": "c",
        }))
        m2 = get_config_manager(str(other))
        assert m1 is not m2
