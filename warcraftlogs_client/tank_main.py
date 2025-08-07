import datetime
import argparse
from collections import defaultdict
from .auth import TokenManager
from .client import WarcraftLogsClient, get_damage_done_data
from .config import load_config
from .spell_breakdown import SpellBreakdown
from .common.data import get_master_data, get_report_metadata
import json


def get_damage_taken_data(client, report_id, source_id):
    query = f"""
    {{
      reportData {{
        report(code: \"{report_id}\") {{
          events(startTime: 0, endTime: 999999999, sourceID: {source_id}, dataType: DamageTaken, hostilityType: Friendlies) {{
            data
          }}
        }}
      }}
    }}
    """
    result = client.run_query(query)
    return result["data"]["reportData"]["report"]["events"]["data"]


def run_tank_report():
    print("👋 Running tank report...")
    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    metadata = get_report_metadata(client, report_id)
    master_actors = get_master_data(client, report_id)

    print(f"📄 Report Title: {metadata['title']}")
    print(f"👥 Players Found: {len(master_actors)}")

    # Phase 1: Identify tanks based on thresholds
    tank_candidates = []
    per_tank_events = {}

    for actor in master_actors:
        if actor["type"] != "Player" or actor["subType"] not in {"Warrior", "Druid"}:
            continue

        name = actor["name"]
        source_id = actor["id"]
        char_class = actor["subType"]

        try:
            events = get_damage_taken_data(client, report_id, source_id)
            total_taken = sum(e.get("amount", 0) for e in events if e.get("type") == "damage")
            total_mitigated = sum(e.get("mitigated", 0) for e in events if e.get("type") == "damage")
            total_unmitigated = total_taken + total_mitigated

            if total_unmitigated == 0:
                continue

            percent = total_mitigated / total_unmitigated * 100
            if total_taken > 150000 and percent > 40:
                tank_candidates.append({
                    "name": name,
                    "class": char_class,
                    "id": source_id,
                    "taken": total_taken,
                    "mitigated": total_mitigated,
                    "percent": round(percent, 2)
                })
                per_tank_events[name] = events

        except Exception as e:
            print(f"❌ Error evaluating {name}: {e}")

    

    print("============================")
    print("📊 Individual Tank Reports")
    print("============================")
    for tank in tank_candidates:
        print(f"{tank['name']} ({tank['class']})")
        print(f"✅ Total Taken: {tank['taken']:,}")
        print(f"🛡️  Total Mitigated: {tank['mitigated']:,} ({tank['percent']}%)")

        # Damage Taken Abilities
        damage_taken_counts = defaultdict(int)
        spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, tank['id'])

        for e in per_tank_events[tank['name']]:
            if e.get("type") == "damage":
                spell_id = e.get("abilityGameID")
                damage_taken_counts[spell_id] += 1

        print("💥 Damage Taken Breakdown:")
        for spell_id, count in sorted(damage_taken_counts.items(), key=lambda x: -x[1]):
            print(f"  - {spell_map.get(spell_id, f'(ID {spell_id})')}: {count} hits")

        # Abilities Used by Tank
        print("⚔️  Abilities Used:")
        try:
            damage_done_events = get_damage_done_data(client, report_id, tank['id'])
        except Exception as e:
            print(f"  ⚠️ Error fetching damage done for {tank['name']}: {e}")
            damage_done_events = []

        used_counts = defaultdict(int)
        for e in damage_done_events:
            if e.get("type") == "damage":
                spell_id = e.get("abilityGameID")
                used_counts[spell_id] += 1

        for spell_id, count in sorted(used_counts.items(), key=lambda x: -x[1]):
            print(f"  - {spell_map.get(spell_id, f'(ID {spell_id})')}: {count} uses")

        
    print("============================")
    print("📊 Tank Comparison Summary")

    # 📊 All Tanks - Damage Taken Summary Table
    print("============================")
    print("📊 All Tanks - Damage Taken Summary")
    print("============================")

    damage_taken_table = defaultdict(dict)
    all_taken_abilities = set()

    for tank in tank_candidates:
        name = tank['name']
        damage_counts = defaultdict(int)
        for e in per_tank_events[name]:
            if e.get("type") == "damage":
                ability_id = e.get("abilityGameID")
                damage_counts[ability_id] += 1
        for ability_id, count in damage_counts.items():
            damage_taken_table[name][ability_id] = count
            all_taken_abilities.add(ability_id)

    sample_id = tank_candidates[0]['id']
    spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, sample_id)

    header = f"{'Character':<15}" + "".join(
        f"{spell_map.get(spell_id, f'(ID {spell_id})')[:14]:>16}"
        for spell_id in sorted(all_taken_abilities)
    )
    print(header)
    print("-" * len(header))

    for name in damage_taken_table:
        row = f"{name:<15}"
        for spell_id in sorted(all_taken_abilities):
            row += f"{damage_taken_table[name].get(spell_id, 0):>16}"
        print(row)

    print("============================")
    for tank in sorted(tank_candidates, key=lambda x: (x["class"], -x["percent"])):
        print(f"- {tank['name']} ({tank['class']}): {tank['percent']}% mitigated ({tank['mitigated']:,} of {tank['taken'] + tank['mitigated']:,})")
        


# 📊 Class-Based Ability Usage Table
    print("============================")
    print("📊 Class-Based Tank Ability Summary")
    print("============================")

    class_tables = defaultdict(list)
    all_abilities_by_class = defaultdict(set)

    for tank in tank_candidates:
        name = tank["name"]
        class_name = tank["class"]
        source_id = tank["id"]
        ability_counts = defaultdict(int)

        try:
            damage_done_events = get_damage_done_data(client, report_id, source_id)
            for e in damage_done_events:
                if e.get("type") == "damage":
                    ability_counts[e.get("abilityGameID")] += 1
            class_tables[class_name].append({
                "name": name,
                "casts": ability_counts
            })
            all_abilities_by_class[class_name].update(ability_counts.keys())
        except Exception as e:
            print(f"⚠️ Could not fetch abilities for {name}: {e}")

    for class_name in class_tables:
        print(f"======= Team {class_name} =======")
        sample_id = next((t['id'] for t in tank_candidates if t['class'] == class_name), None)
        spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, sample_id)

        header = f"{'Character':<15}" + "".join(
            f"{spell_map.get(ability, f'(ID {ability})')[:14]:>16}"
            for ability in sorted(all_abilities_by_class[class_name])
        )
        print(header)
        print("-" * len(header))

        for row in class_tables[class_name]:
            line = f"{row['name']:<15}"
            for ability in sorted(all_abilities_by_class[class_name]):
                line += f"{row['casts'].get(ability, 0):>16}"
            print(line)


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Generate mitigation-based tank summary.")
  args = parser.parse_args()
  run_tank_report()