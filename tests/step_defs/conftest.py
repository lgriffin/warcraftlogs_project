"""Shared BDD fixtures and step definitions for all feature files."""

from unittest.mock import MagicMock

import pytest
from pytest_bdd import given, parsers

from warcraftlogs_client.database import PerformanceDB
from warcraftlogs_client.models import RaidMetadata


@given("a fresh test database", target_fixture="db_ctx")
def fresh_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = PerformanceDB(db_path)
    database.initialize()
    return {"db": database}


@given(
    parsers.parse('a raid analysis for report "{report_id}"'),
    target_fixture="analysis_ctx",
)
def analysis_for_report(build_analysis, report_id):
    return {"analysis": build_analysis(report_id=report_id), "report_id": report_id}


@given("a mock WCL client", target_fixture="wcl_client")
def mock_wcl_client():
    client = MagicMock()
    client.run_query.return_value = {"data": {"reportData": {"report": {}}}}
    client.get_healing_data.return_value = []
    client.get_damage_taken_data.return_value = []
    client.get_damage_done_data.return_value = []
    client.get_cast_events_paginated.return_value = []
    client.get_buffs_table.return_value = {"data": {"auras": []}}
    client.get_cast_table.return_value = []
    client.get_damage_taken_table.return_value = []
    client.get_damage_done_table.return_value = []
    client.get_master_data.return_value = []
    client.get_fights.return_value = []
    client.get_encounter_table.return_value = []
    return client
