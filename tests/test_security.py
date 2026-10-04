"""Security-focused tests: token leakage, SQL injection, and path traversal."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from warcraftlogs_client.common.errors import AuthenticationError


@pytest.mark.security
class TestTokenLeakage:
    def test_secret_not_in_cache_files(self, tmp_path, monkeypatch):
        """Client secrets should never be written to cache files."""
        monkeypatch.setattr("warcraftlogs_client.cache.CACHE_DIR", str(tmp_path))

        from warcraftlogs_client.cache import save_cache

        secret = "super_secret_client_credential_xyz789"
        cache_data = {"healers": [{"name": "TestHealer", "healing": 12345}]}
        save_cache("test_report", cache_data)

        cache_path = tmp_path / "test_report.json"
        assert cache_path.exists()
        content = cache_path.read_text(encoding="utf-8")
        assert secret not in content

    def test_secret_not_in_error_messages(self):
        """Error messages from auth failures should not contain the client secret."""
        from warcraftlogs_client.auth import TokenManager

        secret = "super_secret_credential_abc123"
        tm = TokenManager("test_client_id", secret)

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized", response=mock_response
        )

        with patch("requests.post", return_value=mock_response), pytest.raises(AuthenticationError) as exc_info:
            tm._get_new_token()

        error = exc_info.value
        assert secret not in str(error)
        assert secret not in (error.message or "")
        assert secret not in (error.details or "")

    def test_secret_not_in_markdown_export(self, sample_raid_analysis, tmp_path):
        """Exported markdown should not contain any secrets."""
        from warcraftlogs_client.renderers.markdown import export_raid_analysis

        secrets = ["super_secret_key", "client_secret_value", "oauth_token_xyz"]

        output_path = str(tmp_path / "test_report.md")
        export_raid_analysis(sample_raid_analysis, output_path=output_path)

        content = Path(output_path).read_text(encoding="utf-8")
        for secret in secrets:
            assert secret not in content


@pytest.mark.security
class TestSQLInjection:
    def test_adversarial_character_name(self, db, build_analysis):
        """SQL injection via character names should be safely parameterized."""
        adversarial_name = "'; DROP TABLE raids; --"
        analysis = build_analysis(
            report_id="sqli_test_1",
            healer_name=adversarial_name,
            healer_class="Priest",
        )
        db.import_raid(analysis)

        # Verify DB is intact: raids table still exists and has the row
        conn = db._get_conn()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [r["name"] for r in tables]
        assert "raids" in table_names
        assert "characters" in table_names

        # Verify the adversarial name was stored correctly
        char = conn.execute("SELECT name FROM characters WHERE name = ?", (adversarial_name,)).fetchone()
        assert char is not None
        assert char["name"] == adversarial_name

    def test_adversarial_report_id(self, db, build_analysis):
        """SQL injection via report_id should be safely parameterized."""
        adversarial_id = "abc'; DROP TABLE characters; --"
        analysis = build_analysis(report_id=adversarial_id)
        db.import_raid(analysis)

        conn = db._get_conn()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [r["name"] for r in tables]
        assert "characters" in table_names
        assert "raids" in table_names

        raid = conn.execute(
            "SELECT report_id FROM raids WHERE report_id = ?",
            (adversarial_id,),
        ).fetchone()
        assert raid is not None
        assert raid["report_id"] == adversarial_id

    def test_adversarial_consumable_name(self, db, build_analysis):
        """SQL injection via consumable names should be safely parameterized."""
        from warcraftlogs_client.models import ConsumableUsage

        adversarial_consumable = "Potion'; DELETE FROM consumable_usage; --"
        analysis = build_analysis(
            report_id="sqli_consumes",
            consumables=[
                ConsumableUsage(
                    player_name="HolyPriest",
                    player_role="healer",
                    report_id="sqli_consumes",
                    consumable_name=adversarial_consumable,
                    count=5,
                ),
            ],
        )
        db.import_raid(analysis)

        conn = db._get_conn()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [r["name"] for r in tables]
        assert "consumable_usage" in table_names

        row = conn.execute(
            "SELECT consumable_name FROM consumable_usage WHERE consumable_name = ?",
            (adversarial_consumable,),
        ).fetchone()
        assert row is not None
        assert row["consumable_name"] == adversarial_consumable

    def test_adversarial_raid_title(self, db, build_analysis):
        """SQL injection via raid title should be safely parameterized."""
        adversarial_title = "Raid'; UPDATE raids SET title='hacked'; --"
        analysis = build_analysis(
            report_id="sqli_title",
            title=adversarial_title,
        )
        db.import_raid(analysis)

        conn = db._get_conn()
        raid = conn.execute("SELECT title FROM raids WHERE report_id = ?", ("sqli_title",)).fetchone()
        assert raid is not None
        assert raid["title"] == adversarial_title


@pytest.mark.security
class TestPathTraversal:
    def test_path_traversal_in_report_id(self, tmp_path, monkeypatch):
        """Report IDs with path traversal should not escape cache directory."""
        cache_dir = str(tmp_path / "cache")
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("warcraftlogs_client.cache.CACHE_DIR", cache_dir)

        from warcraftlogs_client.cache import _cache_file, _safe_filename

        dangerous_ids = [
            "../../../etc/passwd",
            "foo/bar/../../../baz",
            "report/../../secret",
        ]
        for rid in dangerous_ids:
            safe = _safe_filename(rid)
            # Forward slashes must be neutralized
            assert "/" not in safe, f"Forward slashes not removed for {rid!r}"
            # The resulting cache file path should stay inside cache_dir
            cache_path = _cache_file(rid)
            resolved = os.path.normpath(cache_path)
            assert resolved.startswith(cache_dir), f"Cache file {resolved} escaped cache dir for report_id={rid!r}"

    def test_safe_filename_neutralizes_slashes(self):
        """_safe_filename must remove all forward slashes."""
        from warcraftlogs_client.cache import _safe_filename

        assert "/" not in _safe_filename("abc/def/ghi")
        assert _safe_filename("a/b") == "a_b"
        assert "/" not in _safe_filename("../../../../etc/shadow")


def _graphql_client():
    from warcraftlogs_client.client import WarcraftLogsClient

    token_mgr = MagicMock()
    token_mgr.get_token.return_value = "fake_token"
    return WarcraftLogsClient(token_mgr, cache_enabled=False)


def _ok(payload):
    return MagicMock(status_code=200, raise_for_status=lambda: None, json=lambda: payload)


@pytest.mark.security
class TestGraphQLInjection:
    """User- and report-supplied values must travel as GraphQL variables, never in the query text."""

    HOSTILE = 'x") { __typename } hack: reportData { report(code: "y'

    def test_report_code_sent_as_variable(self):
        client = _graphql_client()
        response = _ok({"data": {"reportData": {"report": {"title": "t", "owner": {"name": "o"}, "startTime": 1}}}})
        with patch("wcl_core.http.requests.post", return_value=response) as mock_post:
            client.get_report_metadata(self.HOSTILE)
        payload = mock_post.call_args[1]["json"]
        assert self.HOSTILE not in payload["query"]
        assert payload["variables"]["code"] == self.HOSTILE

    def test_character_name_sent_as_variable(self):
        client = _graphql_client()
        response = _ok({"data": {"characterData": {"character": None}}})
        with (
            patch("wcl_core.http.requests.post", return_value=response) as mock_post,
            pytest.raises(ValueError, match="not found"),
        ):
            client.get_character_profile(self.HOSTILE, "server", "EU")
        payload = mock_post.call_args[1]["json"]
        assert self.HOSTILE not in payload["query"]
        assert payload["variables"]["name"] == self.HOSTILE

    def test_event_filters_sent_as_variables(self):
        client = _graphql_client()
        response = _ok({"data": {"reportData": {"report": {"events": {"data": []}}}}})
        with patch("wcl_core.http.requests.post", return_value=response) as mock_post:
            client.get_cast_events_for_encounter("abc", 7, 1000, 2000)
        payload = mock_post.call_args[1]["json"]
        assert payload["variables"] == {
            "code": "abc",
            "startTime": 1000,
            "endTime": 2000,
            "sourceID": 7,
            "limit": 10000,
        }
        assert "sourceID: $sourceID" in payload["query"]

    @pytest.mark.parametrize("bad", ["DamageDone) { x }", "Healing, sourceID: 1", "healing"])
    def test_data_type_enum_is_allow_listed(self, bad):
        client = _graphql_client()
        with patch("wcl_core.http.requests.post") as mock_post, pytest.raises(ValueError):
            client.get_encounter_table("abc", 0, 1, bad)
        mock_post.assert_not_called()

    def test_ranking_metric_is_allow_listed(self):
        client = _graphql_client()
        with patch("wcl_core.http.requests.post") as mock_post, pytest.raises(ValueError):
            client.get_character_zone_rankings("n", "s", "EU", 1, metric="dps) { x }")
        mock_post.assert_not_called()

    def test_response_cache_key_includes_variables(self, tmp_path, monkeypatch):
        from warcraftlogs_client import cache
        from warcraftlogs_client.client import WarcraftLogsClient

        monkeypatch.setattr(cache, "QUERY_CACHE_DIR", str(tmp_path))
        token_mgr = MagicMock()
        token_mgr.get_token.return_value = "fake_token"
        client = WarcraftLogsClient(token_mgr, cache_enabled=True)

        def reply(code):
            return _ok({"data": {"reportData": {"report": {"title": code, "owner": {"name": "o"}, "startTime": 1}}}})

        with patch("wcl_core.http.requests.post", side_effect=[reply("A"), reply("B")]):
            assert client.get_report_metadata("A").title == "A"
            assert client.get_report_metadata("B").title == "B"
