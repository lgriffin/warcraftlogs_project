"""Tests for path resolution across dev and frozen environments."""

from pathlib import Path
from unittest.mock import patch

import pytest

from warcraftlogs_client import paths


class TestIsFrozen:
    def test_not_frozen_by_default(self):
        assert paths.is_frozen() is False

    def test_frozen_when_set(self, monkeypatch):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        assert paths.is_frozen() is True


class TestGetAppDir:
    def test_dev_returns_project_root(self):
        app_dir = paths.get_app_dir()
        assert app_dir.is_dir()
        assert (app_dir / "warcraftlogs_client").is_dir()

    def test_frozen_uses_meipass(self, monkeypatch, tmp_path):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
        assert paths.get_app_dir() == tmp_path


class TestGetUserDataDir:
    def test_dev_same_as_app_dir(self):
        assert paths.get_user_data_dir() == paths.get_app_dir()


class TestGetCacheDir:
    def test_dev_returns_dot_cache(self):
        cache_dir = paths.get_cache_dir()
        assert cache_dir.name == ".cache"


class TestGetConfigPath:
    def test_ends_with_config_json(self):
        assert paths.get_config_path().name == "config.json"


class TestGetDbPath:
    def test_ends_with_db_file(self):
        assert paths.get_db_path().name == "warcraftlogs_history.db"


class TestGetReportsDir:
    def test_ends_with_reports(self):
        assert paths.get_reports_dir().name == "reports"

    def test_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "warcraftlogs_client.paths.get_user_data_dir", lambda: tmp_path
        )
        reports = paths.get_reports_dir()
        assert reports.exists()


class TestGetSpellDataDir:
    def test_ends_with_spell_data(self):
        assert paths.get_spell_data_dir().name == "spell_data"


class TestGetConsumesConfigPath:
    def test_ends_with_consumes_config(self):
        assert paths.get_consumes_config_path().name == "consumes_config.json"


class TestEnsureFirstRunConfig:
    def test_copies_example_when_missing(self, tmp_path, monkeypatch):
        example = tmp_path / "config.example.json"
        example.write_text('{"test": true}')

        data_dir = tmp_path / "userdata"
        data_dir.mkdir()

        monkeypatch.setattr(
            "warcraftlogs_client.paths.get_app_dir", lambda: tmp_path
        )
        monkeypatch.setattr(
            "warcraftlogs_client.paths.get_config_path",
            lambda: data_dir / "config.json",
        )

        paths.ensure_first_run_config()
        assert (data_dir / "config.json").exists()
        assert (data_dir / "config.json").read_text() == '{"test": true}'

    def test_no_overwrite_existing(self, tmp_path, monkeypatch):
        example = tmp_path / "config.example.json"
        example.write_text('{"new": true}')

        config = tmp_path / "config.json"
        config.write_text('{"existing": true}')

        monkeypatch.setattr(
            "warcraftlogs_client.paths.get_app_dir", lambda: tmp_path
        )
        monkeypatch.setattr(
            "warcraftlogs_client.paths.get_config_path", lambda: config
        )

        paths.ensure_first_run_config()
        assert config.read_text() == '{"existing": true}'
