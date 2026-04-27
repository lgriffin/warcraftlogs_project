"""Tests for WarcraftLogsClient — API response parsing and pagination."""

from unittest.mock import MagicMock, patch

import pytest

from warcraftlogs_client.client import (
    WarcraftLogsClient,
    get_healing_data,
    get_damage_done_data,
    get_damage_taken_data,
)
from warcraftlogs_client.models import RaidMetadata


@pytest.fixture
def client():
    tm = MagicMock()
    tm.get_token.return_value = "test_token"
    return WarcraftLogsClient(tm, cache_enabled=False)


class TestRunQuery:
    @patch("warcraftlogs_client.client.requests.post")
    def test_bearer_token_header(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        client.run_query("{ test }")
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test_token"

    @patch("warcraftlogs_client.client.requests.post")
    def test_json_body(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        client.run_query("{ myQuery }")
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"] == {"query": "{ myQuery }"}


class TestGetReportMetadata:
    @patch("warcraftlogs_client.client.requests.post")
    def test_parses_response(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {"reportData": {"report": {
                "title": "Kara", "owner": {"name": "Guild"},
                "startTime": 1700000000000, "endTime": 1700003600000,
            }}}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        meta = client.get_report_metadata("abc")
        assert isinstance(meta, RaidMetadata)
        assert meta.title == "Kara"
        assert meta.owner == "Guild"
        assert meta.report_id == "abc"

    @patch("warcraftlogs_client.client.requests.post")
    def test_not_found_raises(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {"reportData": {"report": None}}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        with pytest.raises(ValueError, match="not found"):
            client.get_report_metadata("bad_id")


class TestGetMasterData:
    @patch("warcraftlogs_client.client.requests.post")
    def test_filters_player_type(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {"reportData": {"report": {"masterData": {"actors": [
                {"id": 1, "name": "Player1", "type": "Player", "subType": "Priest"},
                {"id": 2, "name": "Boss1", "type": "NPC", "subType": "Boss"},
                {"id": 3, "name": "Player2", "type": "Player", "subType": "Warrior"},
            ]}}}}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        result = client.get_master_data("r1")
        assert len(result) == 2
        assert all(a["type"] == "Player" for a in result)


class TestGetCastTable:
    @patch("warcraftlogs_client.client.requests.post")
    def test_nested_data_format(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {"reportData": {"report": {"table": {
                "data": {"entries": [{"guid": 1, "name": "Melee"}]}
            }}}}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        result = client.get_cast_table("r1", 1)
        assert len(result) == 1
        assert result[0]["guid"] == 1

    @patch("warcraftlogs_client.client.requests.post")
    def test_flat_format(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {"reportData": {"report": {"table": {
                "entries": [{"guid": 2, "name": "Strike"}]
            }}}}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        result = client.get_cast_table("r1", 1)
        assert len(result) == 1

    @patch("warcraftlogs_client.client.requests.post")
    def test_empty_response(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {"reportData": {"report": {"table": ""}}}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        result = client.get_cast_table("r1", 1)
        assert result == []


class TestGetCastEventsPaginated:
    @patch("warcraftlogs_client.client.requests.post")
    def test_single_page(self, mock_post, client):
        mock_post.return_value = MagicMock(
            json=lambda: {"data": {"reportData": {"report": {"events": {
                "data": [{"type": "cast", "abilityGameID": 1}],
                "nextPageTimestamp": None,
            }}}}},
            status_code=200,
            raise_for_status=lambda: None,
        )
        result = client.get_cast_events_paginated("r1", 1)
        assert len(result) == 1

    @patch("warcraftlogs_client.client.requests.post")
    def test_multi_page(self, mock_post, client):
        page1 = {"data": {"reportData": {"report": {"events": {
            "data": [{"id": 1}], "nextPageTimestamp": 5000,
        }}}}}
        page2 = {"data": {"reportData": {"report": {"events": {
            "data": [{"id": 2}], "nextPageTimestamp": None,
        }}}}}
        mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
        mock_post.return_value.json = MagicMock(side_effect=[page1, page2])
        result = client.get_cast_events_paginated("r1", 1)
        assert len(result) == 2


class TestParseZoneRankings:
    def test_parses_all_stars(self, client):
        zr_data = {
            "allStars": [{"spec": "Holy", "points": 90.5, "rank": 100}],
            "rankings": [],
        }
        result = client._parse_zone_rankings(zr_data)
        assert len(result.all_stars) == 1
        assert result.all_stars[0].spec == "Holy"
        assert result.all_stars[0].points == 90.5

    def test_parses_encounter_rankings(self, client):
        zr_data = {
            "allStars": [],
            "rankings": [{
                "encounter": {"id": 1, "name": "Attumen"},
                "spec": "Prot",
                "rankPercent": 85.0,
                "totalKills": 5,
                "fastestKill": 120000,
            }],
        }
        result = client._parse_zone_rankings(zr_data)
        assert len(result.encounter_rankings) == 1
        assert result.encounter_rankings[0].encounter_name == "Attumen"
        assert result.encounter_rankings[0].best_percent == 85.0


class TestLegacyShims:
    def test_get_healing_data_wraps(self):
        mock_client = MagicMock()
        mock_client.get_healing_data.return_value = [{"type": "heal"}]
        result = get_healing_data(mock_client, "r1", 1)
        assert result["data"]["reportData"]["report"]["events"]["data"] == [{"type": "heal"}]

    def test_get_damage_done_delegates(self):
        mock_client = MagicMock()
        mock_client.get_damage_done_data.return_value = [{"type": "damage"}]
        result = get_damage_done_data(mock_client, "r1", 1)
        assert result == [{"type": "damage"}]

    def test_get_damage_taken_delegates(self):
        mock_client = MagicMock()
        mock_client.get_damage_taken_data.return_value = [{"type": "damage"}]
        result = get_damage_taken_data(mock_client, "r1", 1)
        assert result == [{"type": "damage"}]
