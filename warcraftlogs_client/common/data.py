def get_master_data(client, report_id):
    query = f"""
    {{
      reportData {{
        report(code: \"{report_id}\") {{
          masterData {{
            actors {{
              id
              name
              type
              subType
            }}
          }}
        }}
      }}
    }}
    """
    result = client.run_query(query)
    return [
        actor for actor in result["data"]["reportData"]["report"]["masterData"]["actors"]
        if actor["type"] == "Player"
    ]

def get_report_metadata(client, report_id):
    query = f"""
    {{
      reportData {{
        report(code: \"{report_id}\") {{
          title
          owner {{ name }}
          startTime
        }}
      }}
    }}
    """
    result = client.run_query(query)
    report = result["data"]["reportData"]["report"]
    return {
        "title": report["title"],
        "owner": report["owner"]["name"],
        "start": report["startTime"]
    }