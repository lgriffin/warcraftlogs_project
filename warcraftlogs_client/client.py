import requests

def get_healing_data(client, report_id, source_id):
        query = f"""
        {{
        reportData {{
            report(code: "{report_id}") {{
            events(startTime: 0, endTime: 999999999, sourceID: {source_id}, dataType: Healing, hostilityType: Friendlies) {{
                data
            }}
            }}
        }}
        }}
        """
        return client.run_query(query)

def get_cast_data(client, report_id, source_id):
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          events(startTime: 0, endTime: 999999999, sourceID: {source_id}, dataType: Casts, hostilityType: Friendlies) {{
            data
          }}
        }}
      }}
    }}
    """
    return client.run_query(query)


def get_damage_done_data(client, report_id, source_id):
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          events(startTime: 0, endTime: 999999999, sourceID: {source_id}, dataType: DamageDone, hostilityType: Friendlies) {{
            data
          }}
        }}
      }}
    }}
    """
    result = client.run_query(query)
    # Print the result directly for debugging
   # print("🔍 Raw API response:\n", result)
    return result["data"]["reportData"]["report"]["events"]["data"]

def get_damage_taken_data(client, report_id, source_id):
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          events(startTime: 0, endTime: 999999999, sourceID: {source_id}, dataType: DamageTaken, hostilityType: Friendlies) {{
            data
          }}
        }}
      }}
    }}
    """
    result = client.run_query(query)
    # Print the result directly for debugging
   # print("🔍 Raw API response:\n", result)
    return result["data"]["reportData"]["report"]["events"]["data"]


def get_threat_data(client, report_id, source_id):
    all_data = []
    start_time = 0

    while True:
        query = f"""
        {{
          reportData {{
            report(code: "{report_id}") {{
              events(startTime: {start_time}, endTime: 999999999, sourceID: {source_id}, dataType: Threat) {{
                data
                nextPageTimestamp
              }}
            }}
          }}
        }}
        """
        result = client.run_query(query)
        events_node = result["data"]["reportData"]["report"]["events"]
        all_data.extend(events_node.get("data", []))

        next_page = events_node.get("nextPageTimestamp")
        if not next_page:
            break
        start_time = next_page

    return {"data": {"reportData": {"report": {"events": {"data": all_data}}}}}


class WarcraftLogsClient:
    API_URL = "https://www.warcraftlogs.com/api/v2/client"

    def __init__(self, token_manager):
        self.token_manager = token_manager

    def run_query(self, query: str) -> dict:
        token = self.token_manager.get_token()
        headers = {
            "Authorization": f"Bearer {token}"
        }

        response = requests.post(self.API_URL, headers=headers, json={"query": query})
        response.raise_for_status()
        return response.json()
    
    

