"""Tests for the JSON cache module."""

import json
import os

import pytest

from warcraftlogs_client.cache import (
    _safe_filename,
    _cache_file,
    load_cached_data,
    save_cache,
    get_cached_actor_data,
    set_cached_actor_data,
)


class TestSafeFilename:
    def test_replaces_slashes(self):
        assert _safe_filename("abc/def") == "abc_def"

    def test_no_slashes(self):
        assert _safe_filename("abc123") == "abc123"

    def test_multiple_slashes(self):
        assert _safe_filename("a/b/c") == "a_b_c"


class TestCacheFile:
    def test_returns_json_path(self):
        path = _cache_file("report123")
        assert path.endswith("report123.json")

    def test_slash_in_id(self):
        path = _cache_file("a/b")
        assert "a_b.json" in path


class TestLoadCachedData:
    def test_returns_none_for_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("warcraftlogs_client.cache.CACHE_DIR", str(tmp_path))
        assert load_cached_data("nonexistent") is None

    def test_loads_valid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("warcraftlogs_client.cache.CACHE_DIR", str(tmp_path))
        data = {"key": "value", "nested": {"a": 1}}
        (tmp_path / "report1.json").write_text(json.dumps(data))
        assert load_cached_data("report1") == data

    def test_returns_none_for_corrupt_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr("warcraftlogs_client.cache.CACHE_DIR", str(tmp_path))
        (tmp_path / "bad.json").write_text("{invalid json")
        assert load_cached_data("bad") is None


class TestSaveCache:
    def test_saves_json_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("warcraftlogs_client.cache.CACHE_DIR", str(tmp_path))
        data = {"healers": ["Priest1"], "count": 42}
        save_cache("raid1", data)
        saved = json.loads((tmp_path / "raid1.json").read_text())
        assert saved == data

    def test_overwrites_existing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("warcraftlogs_client.cache.CACHE_DIR", str(tmp_path))
        save_cache("raid1", {"v": 1})
        save_cache("raid1", {"v": 2})
        saved = json.loads((tmp_path / "raid1.json").read_text())
        assert saved == {"v": 2}


class TestGetCachedActorData:
    def test_returns_data(self):
        cache = {"healing": {"Priest1": [100, 200]}}
        assert get_cached_actor_data(cache, "Priest1", "healing") == [100, 200]

    def test_returns_none_missing_actor(self):
        cache = {"healing": {"Priest1": [100]}}
        assert get_cached_actor_data(cache, "Unknown", "healing") is None

    def test_returns_none_missing_type(self):
        cache = {"healing": {"Priest1": [100]}}
        assert get_cached_actor_data(cache, "Priest1", "damage") is None

    def test_empty_cache(self):
        assert get_cached_actor_data({}, "anyone", "anything") is None


class TestSetCachedActorData:
    def test_sets_new_data(self):
        cache = {}
        set_cached_actor_data(cache, "Priest1", "healing", [100])
        assert cache == {"healing": {"Priest1": [100]}}

    def test_adds_to_existing_type(self):
        cache = {"healing": {"Priest1": [100]}}
        set_cached_actor_data(cache, "Priest2", "healing", [200])
        assert cache["healing"]["Priest2"] == [200]
        assert cache["healing"]["Priest1"] == [100]

    def test_overwrites_actor_data(self):
        cache = {"healing": {"Priest1": [100]}}
        set_cached_actor_data(cache, "Priest1", "healing", [999])
        assert cache["healing"]["Priest1"] == [999]
