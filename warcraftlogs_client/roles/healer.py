from client import get_healing_data
from ..spell_manager import SpellBreakdown
from healing import OverallHealing
from collections import defaultdict
import dynamic_role_parser

def generate_healer_summary(client, report_id, master_actors):
    grouped_summary = {"Priest": [], "Paladin": [], "Druid": []}
    all_spell_names_by_class = {"Priest": set(), "Paladin": set(), "Druid": set()}
    name_to_id = {actor["name"]: actor["id"] for actor in master_actors}

    for name, source_id in name_to_id.items():
        char_class = next((actor["subType"] for actor in master_actors if actor["name"] == name), "Unknown")
        if char_class not in grouped_summary:
            continue

        try:
            healing_data = get_healing_data(client, report_id, source_id)
            healing_events = healing_data["data"]["reportData"]["report"]["events"]["data"]
            total_healing, total_overhealing = OverallHealing.calculate(healing_events)

            print(f"\n============================")
            print(f"📊 Spell Breakdown for {name}")
            print(f"============================")
            print(f"{name}'s Total Healing: {total_healing:,}")
            print(f"{name}'s Overhealing: {total_overhealing:,}")

            spell_map, spell_casts, cast_entries = SpellBreakdown.get_spell_id_to_name_map(client, report_id, source_id)
            spell_totals = SpellBreakdown.calculate(healing_events)
            spell_totals = {k: v for k, v in spell_totals.items() if v > 0}

            print(f"\n{name}'s Spell Healing Breakdown")
            print(f"{'Spell':<30} {'Healing':>15} {'Casts':>10}")
            print("-" * 60)

            per_character_spells = {}
            for spell_id, amount in sorted(spell_totals.items(), key=lambda x: x[1], reverse=True):
                spell_name = spell_map.get(spell_id, f"(ID {spell_id})")
                casts = spell_casts.get(spell_id, 0)
                cast_display = '-' if spell_id == 17543 and casts == 0 else casts
                print(f"{spell_name:<30} {amount:>15,} {cast_display:>10}")
                per_character_spells[spell_name] = per_character_spells.get(spell_name, 0) + casts
                all_spell_names_by_class[char_class].add(spell_name)

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
                spell_map.get(spell_id, f"(ID {spell_id})"): amount
                for spell_id, amount in spell_totals.items()
            }

            summary = {
                "name": name,
                "healing": total_healing,
                "overhealing": total_overhealing,
                "spells": per_character_spells,
                "dispels": dispels,
                "resources": resources,
                "healing_spells": healing_by_name,
            }

            if char_class == "Priest":
                summary["fear_ward"] = fear_ward["casts"] if fear_ward else 0

            grouped_summary[char_class].append(summary)

        except Exception as e:
            print(f"❌ Error processing {name}: {e}")

    # 🧠 Identify actual healers based on healing output
    healing_totals = {
        summary["name"]: summary["healing"]
        for group in grouped_summary.values()
        for summary in group
    }
    healers = dynamic_role_parser.identify_healers(master_actors, healing_totals)

    # Filter grouped_summary to only include identified healers
    filtered_summary = {"Priest": [], "Paladin": [], "Druid": []}
    for healer in healers:
        for row in grouped_summary.get(healer["class"], []):
            if row["name"] == healer["name"]:
                filtered_summary[healer["class"].capitalize()].append(row)

    grouped_summary = filtered_summary
    return grouped_summary, all_spell_names_by_class


def print_healer_table(summary, spell_names, class_name):
    print(f"\n======= {class_name} Team =======")

    all_dispels = set()
    for row in summary:
        all_dispels.update(row.get("dispels", {}).keys())

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
            f"{row.get('dispels', {}).get(d, 0):>16}" for d in sorted(all_dispels)
        )

        fear_ward = row.get("fear_ward", "-") if class_name == "Priest" else ""
        fear_ward_value = f"{fear_ward:>12}" if class_name == "Priest" else ""
        restore_mana = row.get("resources", {}).get("Major Mana Potion", 0)
        dark_rune = row.get("resources", {}).get("Dark Rune", 0)

        print(
            f"{row['name']:<15} {row['healing']:>12,} {row['overhealing']:>12,}"
            f"{spell_counts}{dispel_counts}{fear_ward_value}{restore_mana:>16}{dark_rune:>12}"
        )
