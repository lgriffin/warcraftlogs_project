"""Live API smoke tests (opt-in via WCL_LIVE_TESTS env var).

These tests hit the real WarcraftLogs API and require valid credentials.
Set the following environment variables before running:
    WCL_LIVE_TESTS=true
    WCL_CLIENT_ID=<your client id>
    WCL_CLIENT_SECRET=<your client secret>

Run with: pytest tests/integration/test_live_api.py -m live
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("WCL_LIVE_TESTS"),
    reason="Set WCL_LIVE_TESTS=true to run live API tests",
)


@pytest.mark.live
class TestLiveAPI:
    @pytest.fixture(autouse=True)
    def _require_credentials(self):
        """Skip individual tests if credentials are missing."""
        self.client_id = os.environ.get("WCL_CLIENT_ID", "")
        self.client_secret = os.environ.get("WCL_CLIENT_SECRET", "")
        if not self.client_id or not self.client_secret:
            pytest.skip("WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set")

    def test_auth_token_fetch(self):
        """Verify we can get an OAuth2 token from WarcraftLogs."""
        from warcraftlogs_client.auth import TokenManager

        tm = TokenManager(self.client_id, self.client_secret)
        token = tm.get_token()

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_guild_reports_fetch(self):
        """Fetch guild reports and verify response shape."""
        from warcraftlogs_client.auth import TokenManager
        from warcraftlogs_client.client import WarcraftLogsClient
        from warcraftlogs_client.config import load_config

        config = load_config()
        guild_id = config.get("guild_id")
        if not guild_id:
            pytest.skip("guild_id not configured in config.json")

        tm = TokenManager(self.client_id, self.client_secret)
        client = WarcraftLogsClient(tm, cache_enabled=False)

        reports = client.get_guild_reports(guild_id, total=5)

        assert isinstance(reports, list)
        if reports:
            report = reports[0]
            assert "code" in report or "id" in report

    def test_report_metadata_fetch(self):
        """Fetch metadata for a known report and verify fields."""
        from warcraftlogs_client.auth import TokenManager
        from warcraftlogs_client.client import WarcraftLogsClient
        from warcraftlogs_client.config import load_config

        config = load_config()
        guild_id = config.get("guild_id")
        if not guild_id:
            pytest.skip("guild_id not configured in config.json")

        tm = TokenManager(self.client_id, self.client_secret)
        client = WarcraftLogsClient(tm, cache_enabled=False)

        # Get a report code from guild reports first
        reports = client.get_guild_reports(guild_id, total=1)
        if not reports:
            pytest.skip("No guild reports available")

        report_code = reports[0].get("code", reports[0].get("id"))
        metadata = client.get_report_metadata(report_code)

        assert metadata is not None
        assert metadata.report_id == report_code
        assert isinstance(metadata.title, str)
        assert metadata.start_time > 0
