"""
Legacy data access functions.

These delegate to WarcraftLogsClient methods but maintain the old
function signatures for backward compatibility with existing analysis modules.
"""


def get_master_data(client, report_id):
    return client.get_master_data(report_id)


def get_report_metadata(client, report_id):
    metadata = client.get_report_metadata(report_id)
    return {
        "title": metadata.title,
        "owner": metadata.owner,
        "start": metadata.start_time,
        "end": metadata.end_time,
        "report_id": metadata.report_id,
    }
