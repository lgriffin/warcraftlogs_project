import datetime
import argparse
from .auth import TokenManager
from .client import WarcraftLogsClient, get_healing_data
from .characters import Characters
from .loader import load_config
from .spell_breakdown import SpellBreakdown
from .healing import OverallHealing
from . import dynamic_role_parser
from jinja2 import Environment, FileSystemLoader
import os
import datetime


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
          owner {{
            name
          }}
          startTime
        }}
      }}
    }}
    """
    result = client.run_query(query)

    if "data" not in result:
        print("❌ Error retrieving report metadata:")
        print(result)
        raise KeyError("Missing 'data' in response. Check if the report ID is valid or if the token has expired.")

    report = result["data"]["reportData"]["report"]
    return {
        "title": report["title"],
        "owner": report["owner"]["name"],
        "start": report["startTime"]
    }


def print_report_metadata(metadata, present, all_characters):
    print("\n========================")
    print("📝 Report Metadata")
    print("========================")
    print(f"📄 Title: {metadata['title']}")
    print(f"👤 Owner: {metadata['owner']}")
    dt = datetime.datetime.fromtimestamp(metadata['start'] / 1000)
    print(f"📆 Date: {dt.strftime('%A, %d %B %Y %H:%M:%S')}")
    print(f"\n👥 Characters Present: {', '.join(present)}")
    absent = [char["name"] for char in all_characters if char["name"] not in present]
    print(f"🚫 Absent Characters: {', '.join(absent)}")


def new_table_view(summary, spell_names, class_name, output_lines=None):
    header_line = f"\n======= {class_name} Team ======="
    output = [header_line]

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
    output.append(header)
    output.append("-" * len(header))

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

        output.append(
            f"{row['name']:<15} {row['healing']:>12,} {row['overhealing']:>12,}"
            f"{spell_counts}{dispel_counts}{fear_ward_value}{restore_mana:>16}{dark_rune:>12}"
        )

    if output_lines is not None:
        output_lines.extend(output)
    else:
        print("\n".join(output))
def export_markdown_report(metadata, grouped_summary, all_spell_names_by_class, output_path="report.md"):
    lines = [
        f"# 📝 Report Metadata",
        f"- **Title**: {metadata['title']}",
        f"- **Owner**: {metadata['owner']}",
        f"- **Date**: {datetime.datetime.fromtimestamp(metadata['start'] / 1000).strftime('%A, %d %B %Y %H:%M:%S')}",
        "",
    ]

    for class_type in ["Priest", "Paladin", "Druid"]:
        if grouped_summary[class_type]:
            new_table_view(grouped_summary[class_type], sorted(all_spell_names_by_class[class_type]), class_type, lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n✅ Markdown report saved to: {output_path}")


def export_markdown_report_v2(metadata, grouped_summary, all_spell_names_by_class, output_path="reports/healing_report.md"):
    # Use absolute path to the template directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(base_dir, "templates")

    env = Environment(loader=FileSystemLoader(template_dir), trim_blocks=True, lstrip_blocks=True)
    template = env.get_template("healing_report.md.j2")

    context = {
        "log_date": datetime.datetime.fromtimestamp(metadata["start"] / 1000).strftime("%Y-%m-%d"),
        "version": "2.0",
        "log_url": f"https://www.warcraftlogs.com/reports/{load_config()['report_id']}",
        "summary_by_class": {},
        "dispels_all": {},
        "priests": [],
        "paladins": [],
        "druids": []
    }

    for class_type in ["Priest", "Paladin", "Druid"]:
        context["summary_by_class"][class_type] = []
        context["dispels_all"][class_type] = set()

        for row in grouped_summary.get(class_type, []):
            # Track all dispel names seen
            context["dispels_all"][class_type].update(row["dispels"].keys())

    for cls in context["dispels_all"]:
        context["dispels_all"][cls] = sorted(context["dispels_all"][cls])

    for class_type in ["Priest", "Paladin", "Druid"]:
        for row in grouped_summary.get(class_type, []):
            # Prepare spells
            spells = {
                spell: row["spells"].get(spell, "-")
                for spell in sorted(all_spell_names_by_class[class_type])
            }

            # Prepare dispels for all known types
            dispels = {
                dispel: row["dispels"].get(dispel, "-")
                for dispel in context["dispels_all"][class_type]
            }

            summary_row = {
                "name": row["name"],
                "healing": f"{row['healing']:,}",
                "overhealing": f"{row['overhealing']:,}",
                "spells": spells,
                "dispels": dispels,
                "fear_ward": row.get("fear_ward", "-") if class_type == "Priest" else None,
                "mana_potions": row["resources"].get("Major Mana Potion", 0),
                "dark_runes": row["resources"].get("Dark Rune", 0),
            }

            context["summary_by_class"][class_type].append(summary_row)

            spell_table = "\n".join(
                f"| {spell} | {count} | {row['healing_spells'].get(spell, 0):,} |"
                for spell, count in sorted(row["spells"].items())
            )

            char_row = {
                "name": row["name"],
                "total_healing": f"{row['healing']:,}",
                "overhealing": f"{row['overhealing']:,}",
                "spell_table": spell_table,
                "mana_potions": row["resources"].get("Major Mana Potion", 0),
                "dark_runes": row["resources"].get("Dark Rune", 0),
            }

            if class_type == "Priest":
                context["priests"].append(char_row)
            elif class_type == "Paladin":
                context["paladins"].append(char_row)
            elif class_type == "Druid":
                context["druids"].append(char_row)

    # Render and write output
    rendered = template.render(context)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    print(f"\n✅ Markdown report exported to: {output_path}")



# new_main.py

# ... (imports remain unchanged)

def run_full_report(markdown=False, use_dynamic_roles=False):
    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    metadata = get_report_metadata(client, report_id)
    master_actors = get_master_data(client, report_id)

    if not use_dynamic_roles:
        characters = Characters("characters.json")
        name_to_id = {
            actor["name"]: actor["id"]
            for actor in master_actors
            if actor["name"] in characters.get_all_names()
        }
        all_characters = characters.get_all()
        print("📦 Using pre-defined characters in characters.json.")
        print("⚠️  Please ensure all relevant characters are added or they will be skipped.\n")
    else:
        characters = None
        name_to_id = {actor["name"]: actor["id"] for actor in master_actors}
        all_characters = [{"name": name} for name in name_to_id.keys()]

    print_report_metadata(metadata, name_to_id.keys(), all_characters)

    # ✅ Shaman added here
    grouped_summary = {"Priest": [], "Paladin": [], "Druid": [], "Shaman": []}
    all_spell_names_by_class = {"Priest": set(), "Paladin": set(), "Druid": set(), "Shaman": set()}

    for name, source_id in name_to_id.items():
        char_class = next((actor["subType"] for actor in master_actors if actor["name"] == name), "Unknown")

        if char_class not in {"Priest", "Paladin", "Druid", "Shaman"}:
            continue

        print(f"\n============================")
        print(f"📊 Spell Breakdown for {name}")
        print(f"============================")

        try:
            healing_data = get_healing_data(client, report_id, source_id)
            healing_events = healing_data["data"]["reportData"]["report"]["events"]["data"]

            print(f"Total healing events received: {len(healing_events)}")

            total_healing, total_overhealing = OverallHealing.calculate(healing_events)

            spell_map, spell_casts, cast_entries = SpellBreakdown.get_spell_id_to_name_map(client, report_id, source_id)
            spell_totals = SpellBreakdown.calculate(healing_events)
            spell_totals = {k: v for k, v in spell_totals.items() if v > 0}

            print(f"\n{name}'s Spell Healing Breakdown")
            print(f"{'Spell':<30} {'Healing':>15} {'Casts':>10}")
            print("-" * 60)
            per_character_spells = {}
            for spell_id, amount in sorted(spell_totals.items(), key=lambda x: x[1], reverse=True):
                spell_name = str(spell_map.get(spell_id, f"(ID {spell_id})"))
                casts = spell_casts.get(spell_id, 0)
                cast_display = "-" if spell_id == 17543 and casts == 0 else casts
                all_spell_names_by_class[char_class].add(spell_name)
                per_character_spells[spell_name] = per_character_spells.get(spell_name, 0) + casts
                print(f"{spell_name:<30} {amount:>15,} {cast_display:>10}")

            print(f"\n✅ Total Healing: {total_healing:,}")
            print(f"💤 Total Overhealing: {total_overhealing:,}")

            fear_ward = SpellBreakdown.get_fear_ward_usage(cast_entries)
            if fear_ward and fear_ward["casts"] > 0:
                print(f"\n🛡️  Fear Ward Casts: {fear_ward['casts']}")

            dispels = SpellBreakdown.calculate_dispels(cast_entries, char_class)
            if any(dispels.values()):
                print(f"\n🧹 Dispels:")
                for spell_name, count in dispels.items():
                    print(f"  - {spell_name}: {count} casts")

            resources = SpellBreakdown.get_resources_used(cast_entries)
            if resources:
                print(f"\n🔋 Resources Used:")
                for r_name, count in resources.items():
                    print(f"  - {r_name}: {count}")

            healing_by_name = {
                str(spell_map.get(spell_id, f"(ID {spell_id})")): amount
                for spell_id, amount in spell_totals.items()
            }

            character_summary = {
                "name": name,
                "healing": total_healing,
                "overhealing": total_overhealing,
                "spells": per_character_spells,
                "dispels": dispels,
                "resources": resources,
                "healing_spells": healing_by_name,
            }
            if char_class == "Priest":
                character_summary["fear_ward"] = fear_ward["casts"] if fear_ward else 0

            grouped_summary[char_class].append(character_summary)

        except Exception as e:
            print(f"❌ Error processing {name}: {e}")

    if use_dynamic_roles:
        healing_totals = {
            summary["name"]: summary["healing"]
            for group in grouped_summary.values()
            for summary in group
        }
        healers = dynamic_role_parser.identify_healers(master_actors, healing_totals)

        filtered_summary = {"Priest": [], "Paladin": [], "Druid": [], "Shaman": []}
        for healer in healers:
            for row in grouped_summary.get(healer["class"], []):
                if row["name"] == healer["name"]:
                    filtered_summary[healer["class"]].append(row)

        grouped_summary = filtered_summary

    for class_type in grouped_summary:
        if grouped_summary[class_type]:
            spell_names = sorted(all_spell_names_by_class.get(class_type, []))
            new_table_view(grouped_summary[class_type], spell_names, class_type)

    if markdown:
        export_markdown_report_v2(metadata, grouped_summary, all_spell_names_by_class)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--md", action="store_true", help="Export the report as Markdown to report.md")
    parser.add_argument("--use-dynamic-roles", action="store_true", help="Use dynamic healer classification (ignore characters.json)")
    args = parser.parse_args()
    run_full_report(markdown=args.md, use_dynamic_roles=args.use_dynamic_roles)
