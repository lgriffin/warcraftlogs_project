import datetime
import argparse
from .auth import TokenManager
from .client import WarcraftLogsClient
from .client import get_damage_done_data
from .loader import load_config
from .spell_breakdown import SpellBreakdown

from . import dynamic_role_parser  # uses `subType` to classify
from collections import defaultdict
import sys
import json

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

    try:
        return result["data"]["reportData"]["report"]["events"]["data"]
    except KeyError:
        print(f"⚠️  Unexpected response for sourceID {source_id} (check if this player had damage events):")
        print(json.dumps(result, indent=2))
        raise


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

    class_groups = dynamic_role_parser.group_players_by_class(master_actors)
    melee_classes = {"Rogue", "Warrior"}
    melee_players_by_class = {
        cls: class_groups.get(cls, []) for cls in melee_classes
    }

    all_melee_names = [p["name"] for players in melee_players_by_class.values() for p in players]
    print_report_metadata(metadata, all_melee_names)

    for melee_class, players in melee_players_by_class.items():
        if not players:
            continue

        print(f"\n====== {melee_class} Melee Summary ======")
        print(f"{'Character':<15} {'Total Damage':>15}")
        print("-" * 35)

        for player in players:
            name = player["name"]
            source_id = player["id"]

            try:
                events = get_damage_done_data(client, report_id, source_id)
                spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, source_id)


                total_damage = 0
                damage_by_ability = defaultdict(int)
                casts_by_ability = defaultdict(int)

                for e in events:
                    if not isinstance(e, dict):
                        continue
                    if e.get("type") != "damage":
                        continue

                    amount = e.get("amount", 0)
                    spell_id = e.get("abilityGameID")
                    ability_name = spell_map.get(spell_id, f"(ID {spell_id})")


                    total_damage += amount
                    damage_by_ability[ability_name] += amount
                    casts_by_ability[ability_name] += 1

                print(f"{name:<15} {total_damage:>15,}")
                print(f"{'Ability':<30} {'Damage':>12} {'Casts':>8}")
                print("-" * 55)
                for ability in sorted(damage_by_ability, key=damage_by_ability.get, reverse=True):
                    dmg = damage_by_ability[ability]
                    casts = casts_by_ability[ability]
                    print(f"{ability:<30} {dmg:>12,} {casts:>8}")
                print()

            except Exception as e:
                print(f"Error processing {name}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate melee damage summary for Rogues.")
    args = parser.parse_args()
    run_melee_report()
