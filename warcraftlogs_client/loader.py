import json

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

def get_report_time_range(client, report_id):
    """
    Uses the 'fights' query to get the start and end time of the full report.
    """
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          startTime
          endTime
        }}
      }}
    }}
    """
    response = client.run_query(query)

    try:
        report = response["data"]["reportData"]["report"]
        return report["startTime"], report["endTime"]
    except KeyError:
        raise ValueError("Unable to extract start/end time from report.\n" + json.dumps(response, indent=2))

def load_report_table(client, report_id):
    """
    Fetches the raw JSON blob of the healing table using start and end time from the report.
    """
    start_time, end_time = get_report_time_range(client, report_id)

    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          table(dataType: Healing, startTime: {start_time}, endTime: {end_time})
        }}
      }}
    }}
    """
    raw = client.run_query(query)

    try:
        return raw["data"]["reportData"]["report"]["table"]
    except KeyError:
        raise ValueError("Failed to load table from report: invalid response structure.\n" + json.dumps(raw, indent=2))
