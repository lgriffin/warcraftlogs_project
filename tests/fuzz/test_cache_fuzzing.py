"""Property-based fuzz testing of cache functions."""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


@pytest.mark.fuzz
class TestCacheFuzzing:
    @settings(max_examples=50)
    @given(report_id=st.text())
    def test_safe_filename_never_crashes(self, report_id):
        """_safe_filename should handle any string and never contain forward slashes."""
        from warcraftlogs_client.cache import _safe_filename

        result = _safe_filename(report_id)
        assert isinstance(result, str)
        assert "/" not in result

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        report_id=st.text(min_size=1, max_size=100).filter(
            lambda s: all(c.isalnum() or c in "-_" for c in s)
        )
    )
    def test_cache_roundtrip(self, report_id, tmp_path, monkeypatch):
        """save_cache followed by load_cached_data should return the same data."""
        monkeypatch.setattr("warcraftlogs_client.cache.CACHE_DIR", str(tmp_path))

        from warcraftlogs_client.cache import load_cached_data, save_cache

        test_data = {"key": "value", "number": 42}
        save_cache(report_id, test_data)
        loaded = load_cached_data(report_id)
        assert loaded == test_data

    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(query=st.text())
    def test_response_cache_arbitrary_queries(self, query, tmp_path, monkeypatch):
        """Response cache should handle arbitrary query strings."""
        monkeypatch.setattr(
            "warcraftlogs_client.cache.QUERY_CACHE_DIR",
            str(tmp_path / "responses"),
        )

        from warcraftlogs_client.cache import get_cached_response, save_response_cache

        test_data = {"result": "ok"}
        save_response_cache(query, test_data)
        loaded = get_cached_response(query)
        assert loaded == test_data

    @settings(max_examples=50)
    @given(report_id=st.text())
    def test_cache_file_path_always_string(self, report_id):
        """_cache_file should always return a string path."""
        from warcraftlogs_client.cache import _cache_file

        result = _cache_file(report_id)
        assert isinstance(result, str)
        assert result.endswith(".json")
