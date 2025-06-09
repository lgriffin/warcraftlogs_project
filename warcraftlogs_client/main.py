import argparse
import datetime
from collections import defaultdict

from .auth import TokenManager
from .client import WarcraftLogsClient, get_healing_data, get_damage_done_data
from .loader import load_config
from .spell_breakdown import SpellBreakdown
from .healing import OverallHealing
from . import dynamic_role_parser
from .markdown_exporter import export_combined_markdown

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
    if "data" not in result:
        print("❌ Error retrieving master data:")
        print(result)
        raise KeyError("Missing 'data' in response.")
    return [a for a in result["data"]["reportData"]["report"]["masterData"]["actors"] if a["type"] == "Player"]


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
    if "data" not in result:
        print("❌ Error retrieving report metadata:")
        print(result)
        raise KeyError("Missing 'data' in response.")
    report = result["data"]["reportData"]["report"]
    if report is None:
        print(f"[ERROR] Report ID '{report_id}' not found or is inaccessible.")
        print("🔍 Please double-check the report ID and try again.")
        exit(1)
        
    return {
    "title": report["title"],
    "owner": report["owner"]["name"],
    "start": report["startTime"],
    "report_id": report_id
}


def print_inferred_raid_makeup(tanks, healers):
    print("\n===== 🧩 Inferred Raid Makeup =====")

    if tanks:
        print("🛡️  Tanks:")
        tanks_by_class = defaultdict(list)
        for tank in tanks:
            tanks_by_class[tank["class"]].append(tank["name"])
        for cls in sorted(tanks_by_class):
            print(f"  {cls}: {', '.join(sorted(tanks_by_class[cls]))}")
    else:
        print("🛡️  Tanks: None identified")

    if healers:
        print("✨ Healers:")
        healers_by_class = defaultdict(list)
        for healer in healers:
            healers_by_class[healer["class"]].append(healer["name"])
        for cls in sorted(healers_by_class):
            print(f"  {cls}: {', '.join(sorted(healers_by_class[cls]))}")
    else:
        print("✨ Healers: None identified")


def print_report_metadata(metadata, present_names):
    print("\n========================")
    print("📝 Report Metadata")
    print("========================")
    print(f"📄 Title: {metadata['title']}")
    print(f"👤 Owner: {metadata['owner']}")
    dt = datetime.datetime.fromtimestamp(metadata['start'] / 1000)
    print(f"📆 Date: {dt.strftime('%A, %B %d %Y %H:%M:%S')}")
    print(f"\n👥 Characters Considered: {', '.join(sorted(present_names))}")


def identify_tanks(client, report_id, master_actors, min_taken, min_mitigation):
    tank_candidates = []
    for actor in master_actors:
        if actor["subType"] not in {"Warrior", "Druid"}:
            continue
        source_id = actor["id"]
        try:
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
            events = result["data"]["reportData"]["report"]["events"]["data"]
            total_taken = sum(e.get("amount", 0) for e in events if e.get("type") == "damage")
            total_mitigated = sum(e.get("mitigated", 0) for e in events if e.get("type") == "damage")
            total_unmitigated = total_taken + total_mitigated
            if total_unmitigated == 0:
                continue
            percent = total_mitigated / total_unmitigated * 100
            if total_taken > min_taken and percent > min_mitigation:
                tank_candidates.append({
                    "name": actor["name"],
                    "class": actor["subType"],
                    "id": actor["id"],
                    "events": events,
                    "mitigated": total_mitigated,
                    "taken": total_taken,
                    "percent": round(percent, 2),
                })
        except Exception as e:
            print(f"⚠️ Error identifying tank {actor['name']}: {e}")
    return tank_candidates


def run_unified_report(args):
    config = load_config()
    # This allows us adjust thresholds for dynamic identification of tanks and healers
    role_thresholds = config.get("role_thresholds", {})
    healer_threshold = role_thresholds.get("healer_min_healing", 50000)
    tank_min_taken = role_thresholds.get("tank_min_taken", 150000)
    tank_min_mitigation = role_thresholds.get("tank_min_mitigation", 40)

    report_id = config["report_id"]
    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    metadata = get_report_metadata(client, report_id)
    master_actors = get_master_data(client, report_id)

    tanks = identify_tanks(client, report_id, master_actors, tank_min_taken, tank_min_mitigation)

    # Identify Healers
    healing_totals = {}
    for actor in master_actors:
        if actor["subType"] not in {"Priest", "Paladin", "Druid", "Shaman"}:
            continue
        try:
            healing_data = get_healing_data(client, report_id, actor["id"])
            events = healing_data["data"]["reportData"]["report"]["events"]["data"]
            total = sum(e.get("amount", 0) for e in events if e.get("type") == "heal")
            healing_totals[actor["name"]] = total
        except Exception as e:
            print(f"⚠️ Skipping {actor['name']} for healer check: {e}")

    healers = dynamic_role_parser.identify_healers(master_actors, healing_totals, threshold=healer_threshold)
    excluded_names = {t["name"] for t in tanks} | {h["name"] for h in healers}
    present_names = [a["name"] for a in master_actors if a["name"] not in excluded_names]
    print_report_metadata(metadata, present_names)
    print(f"📐 Using thresholds → Healer: {healer_threshold:,} healing | Tank: {tank_min_taken:,} taken & {tank_min_mitigation}% mitigation")
    print_inferred_raid_makeup(tanks, healers)
    print("Somenthing wrong? It might be a meme hybrid spec")


    # ========================= TANK REPORT
    print("\n===== 🛡️ Individual Tank Reports =====")
    for tank in tanks:
        name, tank_id = tank["name"], tank["id"]
        print(f"{name} ({tank['class']})")
        print(f"✅ Total Taken: {tank['taken']:,}")
        print(f"🛡️  Total Mitigated: {tank['mitigated']:,} ({tank['percent']}%)")
        spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, tank_id)

        # Damage Taken
        damage_taken_counts = defaultdict(int)
        for e in tank["events"]:
            if e.get("type") == "damage":
                spell_id = e.get("abilityGameID")
                damage_taken_counts[spell_id] += 1

        print("💥 Damage Taken Breakdown:")
        for spell_id, count in sorted(damage_taken_counts.items(), key=lambda x: -x[1]):
            print(f"  - {spell_map.get(spell_id, f'(ID {spell_id})')}: {count} hits")

        print("⚔️  Abilities Used:")
        try:
            done_events = get_damage_done_data(client, report_id, tank_id)
            used_counts = defaultdict(int)
            for e in done_events:
                if e.get("type") == "damage":
                    used_counts[e["abilityGameID"]] += 1
            for spell_id, count in sorted(used_counts.items(), key=lambda x: -x[1]):
                print(f"  - {spell_map.get(spell_id, f'(ID {spell_id})')}: {count} uses")
        except Exception as e:
            print(f"⚠️ Could not fetch damage done for {name}: {e}")

    # ========================= HEALER REPORT
    print("\n===== ✨ Individual Healer Reports =====")
    grouped_summary = {"Priest": [], "Paladin": [], "Druid": [], "Shaman": []}
    all_spell_names_by_class = {"Priest": set(), "Paladin": set(), "Druid": set(), "Shaman": set()}
    for healer in healers:
        name, class_type, source_id = healer["name"], healer["class"], healer["id"]
        try:
            healing_data = get_healing_data(client, report_id, source_id)
            healing_events = healing_data["data"]["reportData"]["report"]["events"]["data"]
            print(f"\n{name:<15} ({class_type})")
            print(f"Total healing events received: {len(healing_events)}")

            total_healing, total_overhealing = OverallHealing.calculate(healing_events)
            spell_map, spell_casts, cast_entries = SpellBreakdown.get_spell_id_to_name_map(client, report_id, source_id)
            spell_totals = SpellBreakdown.calculate(healing_events)
            spell_totals = {k: v for k, v in spell_totals.items() if v > 0}

            print(f"{'Spell':<30} {'Healing':>15} {'Casts':>10}")
            print("-" * 60)
            per_character_spells = {}
            for spell_id, amount in sorted(spell_totals.items(), key=lambda x: x[1], reverse=True):
                spell_name = str(spell_map.get(spell_id, f"(ID {spell_id})"))
                casts = spell_casts.get(spell_id, 0)
                per_character_spells[spell_name] = per_character_spells.get(spell_name, 0) + casts
                all_spell_names_by_class[class_type].add(spell_name)
                print(f"{spell_name:<30} {amount:>15,} {casts:>10}")

            print(f"✅ Total Healing: {total_healing:,}")
            print(f"💤 Total Overhealing: {total_overhealing:,}")

            fear_ward = SpellBreakdown.get_fear_ward_usage(cast_entries)
            if fear_ward and fear_ward["casts"] > 0:
                print(f"🛡️  Fear Ward Casts: {fear_ward['casts']}")

            dispels = SpellBreakdown.calculate_dispels(cast_entries, class_type)
            if any(dispels.values()):
                print("🧹 Dispels:")
                for k, v in dispels.items():
                    print(f"  - {k}: {v} casts")

            resources = SpellBreakdown.get_resources_used(cast_entries)
            if resources:
                print("🔋 Resources Used:")
                for r, v in resources.items():
                    print(f"  - {r}: {v}")

            grouped_summary[class_type].append({
                "name": name,
                "healing": total_healing,
                "overhealing": total_overhealing,
                "spells": per_character_spells,
                "dispels": dispels,
                "resources": resources,
                "healing_spells": {
                    str(spell_map.get(sid, f"(ID {sid})")): amt for sid, amt in spell_totals.items()
                },
                "fear_ward": fear_ward["casts"] if class_type == "Priest" and fear_ward else 0,
            })
        except Exception as e:
            print(f"❌ Error processing {name}: {e}")

    # ========================= MELEE & RANGED REPORT
    print("\n===== ⚔️ Individual Melee Reports =====")
    melee_classes = {"Rogue", "Warrior"}
    ranged_classes = {"Mage", "Warlock", "Hunter"}
    class_groups = dynamic_role_parser.group_players_by_class(master_actors)

    melee_summary = {}
    ranged_summary = {}
    all_melee_spells = {}
    all_ranged_spells = {}

    for role, allowed_classes, summary_store, spell_store in [
        ("Melee", melee_classes, melee_summary, all_melee_spells),
        ("Ranged", ranged_classes, ranged_summary, all_ranged_spells),
    ]:
        print(f"\n===== {role} Role =====")
        for class_name in allowed_classes:
            players = class_groups.get(class_name, [])
            players = [p for p in players if p["name"] not in excluded_names]
            summary = []
            all_spells = set()

            for player in players:
                name = player["name"]
                source_id = player["id"]
                try:
                    events = get_damage_done_data(client, report_id, source_id)
                    spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, source_id)

                    total_damage = 0
                    casts_by_ability = defaultdict(int)
                    for e in events:
                        if e.get("type") == "damage":
                            amount = e.get("amount", 0)
                            spell_id = e.get("abilityGameID")
                            ability = spell_map.get(spell_id, f"(ID {spell_id})")
                            total_damage += amount
                            casts_by_ability[ability] += 1
                            all_spells.add(ability)

                    print(f"{name:<15} {total_damage:>15,}")
                    print(f"{'Ability':<30} {'Casts':>10}")
                    print("-" * 45)
                    for spell in sorted(casts_by_ability, key=casts_by_ability.get, reverse=True):
                        print(f"{spell:<30} {casts_by_ability[spell]:>10}")
                    print()

                    summary.append({
                        "name": name,
                        "total": total_damage,
                        "casts": casts_by_ability
                    })
                except Exception as e:
                    print(f"❌ Error processing {name}: {e}")

            summary_store[class_name] = summary
            spell_store[class_name] = all_spells

    # ========================= SUMMARY TABLES
    def print_class_summary_table(label, summary_store, all_spells_store):
        for cls in sorted(summary_store):
            summaries = summary_store[cls]
            if not summaries:
                continue
            spells = sorted(all_spells_store.get(cls, []))
            print(f"\n📊 {label} Summary: {cls}")
            header = f"{'Character':<15} {'Total Damage':>15}" + "".join(f"{s[:14]:>16}" for s in spells)
            print(header)
            print("-" * len(header))
            for row in sorted(summaries, key=lambda x: x['total'], reverse=True):
                line = f"{row['name']:<15} {row['total']:>15,}"
                for spell in spells:
                    line += f"{row['casts'].get(spell, 0):>16}"
                print(line)

    print_class_summary_table("Melee", melee_summary, all_melee_spells)
    print_class_summary_table("Ranged", ranged_summary, all_ranged_spells)

    # ========================= HEALER SUMMARY TABLES
    def print_healer_table(summary, spell_names, class_name):
        print(f"\n📊 Healer Summary: {class_name}")

        all_dispels = set()
        for row in summary:
            all_dispels.update(row["dispels"].keys())

        dispel_headers = "".join(f"{dispel[:16]:>16}" for dispel in sorted(all_dispels))
        fear_ward_header = f"{'Fear Ward':>12}" if class_name == "Priest" else ""
        header = (
            f"{'Character':<15} {'Healing':>12} {'Overheal':>12} " +
            "".join(f"{spell[:14]:>16}" for spell in spell_names) +
            f"{dispel_headers}{fear_ward_header}{'Restore Mana':>16} {'Dark Rune':>12}"
        )
        print(header)
        print("-" * len(header))

        for row in sorted(summary, key=lambda x: x["healing"], reverse=True):
            spell_counts = ""
            for spell in spell_names:
                if spell == "Fire Protection":
                    healing = row.get("healing_spells", {}).get("Fire Protection", 0)
                    spell_counts += f"{healing:>16,}"
                else:
                    cast_total = sum(
                        count for name, count in row["spells"].items()
                        if name == spell
                    )
                    spell_counts += f"{cast_total:>16}"

            dispel_counts = "".join(
                f"{row['dispels'].get(d, 0):>16}" for d in sorted(all_dispels)
            )

            fear_ward = row.get("fear_ward", "-") if class_name == "Priest" else ""
            fear_ward_value = f"{fear_ward:>12}" if class_name == "Priest" else ""
            restore_mana = row["resources"].get("Major Mana Potion", 0)
            dark_rune = row["resources"].get("Dark Rune", 0)

            print(
                f"{row['name']:<15} {row['healing']:>12,} {row['overhealing']:>12,}"
                f"{spell_counts}{dispel_counts}{fear_ward_value}{restore_mana:>16}{dark_rune:>12}"
            )


    for class_name in ["Priest", "Paladin", "Druid", "Shaman"]:
        summary = grouped_summary.get(class_name, [])
        spell_names = sorted(all_spell_names_by_class.get(class_name, []))
        if summary:
            print_healer_table(summary, spell_names, class_name)

    # ========================= TANK SUMMARY TABLE
    print("\n📊 Tank Summary: Damage Taken by Ability")
    tank_rows = []
    all_taken_abilities = set()
    for tank in tanks:
        damage_counts = defaultdict(int)
        for e in tank["events"]:
            if e.get("type") == "damage":
                spell_id = e.get("abilityGameID")
                damage_counts[spell_id] += 1
                all_taken_abilities.add(spell_id)
        tank_rows.append((tank["name"], tank["id"], damage_counts))

    if tank_rows:
        sample_id = tank_rows[0][1]
        spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, sample_id)
        spell_names = [spell_map.get(sid, f"(ID {sid})") for sid in sorted(all_taken_abilities)]
        header = f"{'Character':<15}" + "".join(f"{spell[:14]:>16}" for spell in spell_names)
        print(header)
        print("-" * len(header))
        for name, _, dmg_dict in tank_rows:
            row = f"{name:<15}"
            for sid in sorted(all_taken_abilities):
                row += f"{dmg_dict.get(sid, 0):>16}"
            print(row)

    # ========================= TANK DAMAGE DONE SUMMARY TABLE
    print("\n📊 Tank Summary: Damage Done by Ability")

    class_tables = defaultdict(list)
    all_abilities_by_class = defaultdict(set)

    for tank in tanks:
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
        print(f"\n======= Team {class_name} (Tanks - Damage Done) =======")
        sample_id = next((t['id'] for t in tanks if t['class'] == class_name), None)
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
    if args.md:
        # Add melee and ranged spell names to the global spell_names dictionary
        for cls in all_melee_spells:
            all_spell_names_by_class[cls] = sorted(all_melee_spells[cls])
        for cls in all_ranged_spells:
            all_spell_names_by_class[cls] = sorted(all_ranged_spells[cls])

        export_combined_markdown(
            metadata=metadata,
            healer_summary=grouped_summary,
            melee_summary=melee_summary,
            ranged_summary=ranged_summary,
            tank_summary=[{"name": name, "abilities": [dmg_dict.get(sid, 0) for sid in sorted(all_taken_abilities)]} for name, _, dmg_dict in tank_rows],
            tank_abilities=[spell_map.get(sid, f"(ID {sid})") for sid in sorted(all_taken_abilities)],
            tank_damage_summary=[
                {
                    "class_name": cls,
                    "abilities": [spell_map.get(ability, f"(ID {ability})") for ability in sorted(all_abilities_by_class[cls])],
                    "players": [
                        {
                            "name": row["name"],
                            "casts": [row["casts"].get(ability, 0) for ability in sorted(all_abilities_by_class[cls])]
                        } for row in class_tables[cls]
                    ]
                }
                for cls in class_tables
            ],
            spell_names=all_spell_names_by_class,
            report_title=metadata["title"]
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Warcraft Logs Role Classifier")
    parser.add_argument("--md", action="store_true", help="Export summary markdown report")
    args = parser.parse_args()
    print("Pulling data from the report")
    print("Initially going to try identify roles dynamically")
    run_unified_report(args)


 
