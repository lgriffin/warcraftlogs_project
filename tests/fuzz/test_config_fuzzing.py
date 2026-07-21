"""Property-based fuzz testing of configuration validation."""

import json

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from warcraftlogs_client.common.errors import ConfigurationError


@pytest.mark.fuzz
class TestConfigFuzzing:
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(random_dict=st.dictionaries(st.text(), st.text()))
    def test_load_config_with_random_dict(self, random_dict, tmp_path, monkeypatch):
        """load_config should never crash on arbitrary input, only raise known errors."""
        import warcraftlogs_client.config as cfg

        cfg._config_manager = None

        monkeypatch.delenv("WARCRAFTLOGS_CLIENT_ID", raising=False)
        monkeypatch.delenv("WARCRAFTLOGS_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("WARCRAFTLOGS_REPORT_ID", raising=False)

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(random_dict), encoding="utf-8")

        try:
            cfg.load_config(str(config_path))
        except ConfigurationError:
            pass  # Expected for missing required keys

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(text=st.text())
    def test_client_id_arbitrary_strings(self, text, tmp_path, monkeypatch):
        """Arbitrary strings as client_id should not cause crashes downstream."""
        import warcraftlogs_client.config as cfg

        cfg._config_manager = None

        monkeypatch.delenv("WARCRAFTLOGS_CLIENT_ID", raising=False)
        monkeypatch.delenv("WARCRAFTLOGS_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("WARCRAFTLOGS_REPORT_ID", raising=False)

        config_data = {
            "client_id": text,
            "client_secret": "test_secret",
            "report_id": "test_report",
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        try:
            result = cfg.load_config(str(config_path))
            assert result["client_id"] == text
        except ConfigurationError:
            pass  # Empty string is treated as missing

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(value=st.integers() | st.none() | st.floats(allow_nan=False, allow_infinity=False) | st.text())
    def test_guild_id_arbitrary_types(self, value, tmp_path, monkeypatch):
        """guild_id should handle any type without crashing."""
        import warcraftlogs_client.config as cfg

        cfg._config_manager = None

        monkeypatch.delenv("WARCRAFTLOGS_CLIENT_ID", raising=False)
        monkeypatch.delenv("WARCRAFTLOGS_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("WARCRAFTLOGS_REPORT_ID", raising=False)

        config_data = {
            "client_id": "test_id",
            "client_secret": "test_secret",
            "report_id": "test_report",
            "guild_id": value,
        }
        config_path = tmp_path / "config.json"

        try:
            config_path.write_text(json.dumps(config_data), encoding="utf-8")
        except (ValueError, TypeError):
            return  # Value not JSON-serializable, skip

        result = cfg.load_config(str(config_path))
        assert isinstance(result["guild_id"], int)
