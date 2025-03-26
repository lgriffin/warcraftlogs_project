import datetime
import argparse
from .auth import TokenManager
from .client import WarcraftLogsClient, get_healing_data
from .characters import Characters
from .loader import load_config
from .spell_breakdown import SpellBreakdown
from .healing import OverallHealing


def get_master_data(client, report_id):
    query = f"""
    {{
      reportData {{
        report(code: "{report_id}") {{
          masterData {{
            actors {{
              id
              name
            }}
          }}
        }}
      }}
    }}
    """
    result = client.run_query(query)
    return result["data"]["reportData"]["report"]["masterData"]["actors"]


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
    header = (
        f"{'Character':<15} {'Healing':>12} {'Overheal':>12} " +
        "".join(f"{spell[:14]:>16}" for spell in spell_names) +
        f"{dispel_headers}{'Fear Ward':>12} {'Restore Mana':>16} {'Dark Rune':>12}"
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
                casts = row["spells"].get(spell, 0)
                spell_counts += f"{casts:>16}"

        dispel_counts = "".join(
            f"{row['dispels'].get(d, 0):>16}" for d in sorted(all_dispels)
        )

        fear_ward = row["fear_ward"]
        restore_mana = row["resources"].get("Major Mana Potion", 0)
        dark_rune = row["resources"].get("Dark Rune", 0)

        output.append(
            f"{row['name']:<15} {row['healing']:>12,} {row['overhealing']:>12,}"
            f"{spell_counts}{dispel_counts}{fear_ward:>12}{restore_mana:>16}{dark_rune:>12}"
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


def run_full_report(markdown=False):
    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    characters = Characters("characters.json")
    metadata = get_report_metadata(client, report_id)
    master_actors = get_master_data(client, report_id)

    name_to_id = {
        actor["name"]: actor["id"]
        for actor in master_actors
        if actor["name"] in characters.get_all_names()
    }

    print_report_metadata(metadata, name_to_id.keys(), characters.get_all())

    grouped_summary = {"Priest": [], "Paladin": [], "Druid": []}
    all_spell_names_by_class = {"Priest": set(), "Paladin": set(), "Druid": set()}

    for name, source_id in name_to_id.items():
        char_class = characters.get_class(name)
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
                per_character_spells[spell_name] = casts
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

            grouped_summary[char_class].append({
                "name": name,
                "healing": total_healing,
                "overhealing": total_overhealing,
                "spells": per_character_spells,
                "dispels": dispels,
                "fear_ward": fear_ward["casts"] if fear_ward else 0,
                "resources": resources,
                "healing_spells": healing_by_name,
            })

        except Exception as e:
            print(f"❌ Error processing {name}: {e}")

    for class_type in ["Priest", "Paladin", "Druid"]:
        if grouped_summary[class_type]:
            new_table_view(grouped_summary[class_type], sorted(all_spell_names_by_class[class_type]), class_type)

    if markdown:
        export_markdown_report(metadata, grouped_summary, all_spell_names_by_class)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--md", action="store_true", help="Export the report as Markdown to report.md")
    args = parser.parse_args()
    run_full_report(markdown=args.md)
