def get_master_data(client, report_id):
    from .errors import validate_api_response, ApiError, ErrorSeverity
    
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
    
    # Validate response structure
    validate_api_response(
        result, 
        ["data", "reportData", "report", "masterData", "actors"],
        "master data response"
    )
    
    actors = result["data"]["reportData"]["report"]["masterData"]["actors"]
    players = [actor for actor in actors if actor["type"] == "Player"]
    
    if not players:
        raise ApiError("No players found in report", severity=ErrorSeverity.WARNING)
    
    return players

def get_report_metadata(client, report_id):
    from .errors import validate_api_response, ApiError, ErrorSeverity
    
    query = f"""
    {{
      reportData {{
        report(code: \"{report_id}\") {{
          title
          owner {{ name }}
          startTime
          endTime
        }}
      }}
    }}
    """
    result = client.run_query(query)
    
    # Validate response structure
    validate_api_response(
        result,
        ["data", "reportData", "report"],
        "report metadata response"
    )
    
    report = result["data"]["reportData"]["report"]
    if report is None:
        raise ApiError(
            f"Report ID '{report_id}' not found or is inaccessible",
            severity=ErrorSeverity.CRITICAL,
            details="Please double-check the report ID and try again"
        )
        
    return {
        "title": report["title"],
        "owner": report["owner"]["name"],
        "start": report["startTime"],
        "end": report.get("endTime"),
        "report_id": report_id
    }