import json
from .auth import TokenManager
from .client import WarcraftLogsClient
from .loader import load_config

def get_report_time_range(client, report_id):
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
    result = client.run_query(query)
    report = result["data"]["reportData"]["report"]
    return report["startTime"], report["endTime"]

def get_all_healing_events_paginated(client, report_id, start, end):
    print("📡 Beginning paginated healing event fetch...")
    all_events = []
    next_page = start
    page_count = 1

    while next_page is not None:
        print(f"➡️ Fetching page {page_count} starting at {next_page}")
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              events(
                startTime: {next_page},
                endTime: {end},
                dataType: Healing,
                hostilityType: Friendlies
              ) {{
                data
                nextPageTimestamp
              }}
            }}
          }}
        }}
        """
        result = client.run_query(query)
        report_events = result["data"]["reportData"]["report"]["events"]
        events = report_events["data"]
        all_events.extend(events)
        next_page = report_events.get("nextPageTimestamp")
        page_count += 1

    return all_events

def run():
    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    print("📥 Fetching report time range...")
    start, end = get_report_time_range(client, report_id)

    print("📊 Fetching all healing events (paginated)...")
    events = get_all_healing_events_paginated(client, report_id, start, end)

    with open("healing_events_full.json", "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)

    print(f"✅ Dumped {len(events)} healing events to healing_events_full.json")

if __name__ == "__main__":
    run()
