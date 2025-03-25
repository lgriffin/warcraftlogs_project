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
    
    

