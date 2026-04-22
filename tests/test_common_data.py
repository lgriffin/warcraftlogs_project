"""Tests for legacy compatibility shims in common.data."""

from unittest.mock import MagicMock

from warcraftlogs_client.common.data import get_master_data, get_report_metadata
from warcraftlogs_client.models import RaidMetadata


class TestGetMasterData:
    def test_delegates_to_client(self):
        client = MagicMock()
        client.get_master_data.return_value = [{"name": "P1", "id": 1}]
        result = get_master_data(client, "r1")
        client.get_master_data.assert_called_once_with("r1")
        assert result == [{"name": "P1", "id": 1}]


class TestGetReportMetadata:
    def test_converts_to_dict(self):
        client = MagicMock()
        client.get_report_metadata.return_value = RaidMetadata(
            report_id="r1", title="Kara", owner="Guild",
            start_time=1700000000000, end_time=1700003600000,
        )
        result = get_report_metadata(client, "r1")
        assert isinstance(result, dict)
        assert result["title"] == "Kara"
        assert result["owner"] == "Guild"
        assert result["start"] == 1700000000000
        assert result["end"] == 1700003600000
        assert result["report_id"] == "r1"
