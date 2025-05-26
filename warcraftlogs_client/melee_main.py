import datetime
import argparse
from .auth import TokenManager
from .client import WarcraftLogsClient, get_damage_done_data
from .loader import load_config
from .spell_breakdown import SpellBreakdown
from . import dynamic_role_parser

from collections import defaultdict
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

def print_report_metadata(metadata, present_names):
    print("\n========================")
    print("📝 Report Metadata")
    print("========================")
    print(f"📄 Title: {metadata['title']}")
    print(f"👤 Owner: {metadata['owner']}")
    dt = datetime.datetime.fromtimestamp(metadata['start'] / 1000)
    print(f"📆 Date: {dt.strftime('%A, %B %d %Y %H:%M:%S')}")
    print(f"\n⚔️ Melee Characters Present: {', '.join(sorted(present_names))}")

def print_class_summary_table(class_name, class_summaries, all_abilities):
    print(f"\n======= Team {class_name} =======")
    header = f"{'Character':<15} {'Total Damage':>15} " + "".join(f"{a[:14]:>16}" for a in all_abilities)
    print(header)
    print("-" * len(header))

    for summary in sorted(class_summaries, key=lambda x: x['total'], reverse=True):
        row = f"{summary['name']:<15} {summary['total']:>15,}"
        for ability in all_abilities:
            count = summary['casts'].get(ability, 0)
            row += f"{count:>16}"
        print(row)

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

        class_summary = []
        all_abilities = set()

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
                    if not isinstance(e, dict) or e.get("type") != "damage":
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

                class_summary.append({
                    "name": name,
                    "total": total_damage,
                    "casts": casts_by_ability
                })
                all_abilities.update(casts_by_ability.keys())

            except Exception as e:
                print(f"Error processing {name}: {e}")

        print_class_summary_table(melee_class, class_summary, sorted(all_abilities))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate melee damage summary for Rogues and Warriors.")
    args = parser.parse_args()
    run_melee_report()
