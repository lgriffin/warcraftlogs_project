"""
Legacy data access functions.

These delegate to WarcraftLogsClient methods but maintain the old
function signatures for backward compatibility with existing analysis modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import WarcraftLogsClient


def get_master_data(client: WarcraftLogsClient, report_id: str) -> list[dict[str, Any]]:
    return client.get_master_data(report_id)


def get_report_metadata(client: WarcraftLogsClient, report_id: str) -> dict[str, Any]:
    metadata = client.get_report_metadata(report_id)
    return {
        "title": metadata.title,
        "owner": metadata.owner,
        "start": metadata.start_time,
        "end": metadata.end_time,
        "report_id": metadata.report_id,
    }
