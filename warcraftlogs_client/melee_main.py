import datetime
import argparse
from .auth import TokenManager
from .client import WarcraftLogsClient
from .loader import load_config
from . import dynamic_role_parser  # uses `subType` to classify
import sys

def get_master_data(client, report_id):
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
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

    if "data" not in result:
        print("❌ Error retrieving master data:")
        print(result)
        raise KeyError("Missing 'data' in response.")
    
    return [
        actor for actor in result["data"]["reportData"]["report"]["masterData"]["actors"]
        if actor["type"] == "Player"
    ]

def get_report_metadata(client, report_id):
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          title
          owner {{ name }}
          startTime
        }}
      }}
    }}
    """
    result = client.run_query(query)

    if "data" not in result:
        print("❌ Error retrieving report metadata:")
        print(result)
        raise KeyError("Missing 'data' in response.")
    
    report = result["data"]["reportData"]["report"]
    return {
        "title": report["title"],
        "owner": report["owner"]["name"],
        "start": report["startTime"]
    }

def get_damage_events(client, report_id, source_id):
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          events(startTime: 0, sourceID: {source_id}, dataType: Damage) {{
            data
          }}
        }}
      }}
    }}
    """
    result = client.run_query(query)
    return result["data"]["reportData"]["report"]["events"]["data"]

def print_report_metadata(metadata, present_names):
    print("\n========================")
    print("📝 Report Metadata")
    print("========================")
    print(f"📄 Title: {metadata['title']}")
    print(f"👤 Owner: {metadata['owner']}")
    dt = datetime.datetime.fromtimestamp(metadata['start'] / 1000)
    print(f"📆 Date: {dt.strftime('%A, %B %d %Y %H:%M:%S')}")
    print(f"\n⚔️ Melee Characters Present: {', '.join(sorted(present_names))}")

def run_melee_report():
    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    metadata = get_report_metadata(client, report_id)
    master_actors = get_master_data(client, report_id)

    # Dynamically infer melee players
    class_groups = dynamic_role_parser.group_players_by_class(master_actors)

    # Only interested in melee classes (starting with Rogue)
    melee_classes = {"Rogue"}  # Expand to Warrior, Enhancement Shaman, etc.
    melee_players = []

    for cls in melee_classes:
        melee_players.extend(class_groups.get(cls, []))

    rogue_players = [p for p in melee_players if p["class"] == "Rogue"]

    if not rogue_players:
        print("❌ No Rogue melee players found.")
        sys.exit(1)

    print_report_metadata(metadata, [p["name"] for p in rogue_players])

    print("\n====== Rogue Melee Summary ======")
    print(f"{'Character':<15} {'Total Damage':>15}")
    print("-" * 35)

    for rogue in rogue_players:
        name = rogue["name"]
        source_id = rogue["id"]

        try:
            events = get_damage_events(client, report_id, source_id)
            total_damage = sum(e.get("amount", 0) for e in events if e.get("type") == "damage")
            print(f"{name:<15} {total_damage:>15,}")

            print(f"\n🔍 Debug: First 10 damage events for {name}")
            for e in events[:10]:
                print(e)

        except Exception as e:
            print(f"❌ Error processing {name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate melee damage summary for Rogues.")
    args = parser.parse_args()
    run_melee_report()
