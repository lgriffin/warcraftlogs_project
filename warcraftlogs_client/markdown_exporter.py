import os
from jinja2 import Environment, FileSystemLoader
import datetime

def export_combined_markdown(
    metadata,
    healer_summary,
    melee_summary,
    ranged_summary,
    tank_summary,
    tank_abilities,
    tank_damage_summary,
    spell_names,
    report_title,
    output_path=None
):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(base_dir, "templates")

    env = Environment(loader=FileSystemLoader(template_dir), trim_blocks=True, lstrip_blocks=True)
    template = env.get_template("healing_report.md.j2")

    if not output_path:
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in report_title).strip().replace(" ", "_")
        output_path = os.path.join("reports", f"{safe_title}.md")

    context = {
        "report_title": report_title,
        "log_date": datetime.datetime.fromtimestamp(metadata["start"] / 1000).strftime("%Y-%m-%d"),
        "log_url": f"https://www.warcraftlogs.com/reports/{metadata['report_id']}",
        "summary_by_class": {},
        "dispels_all": {},
        "melee_classes": [],
        "ranged_classes": [],
        "tank_summary": tank_summary,
        "tank_abilities": tank_abilities,
        "tank_damage_summary": tank_damage_summary,
        "spell_names": spell_names,
        "include_healer": True,
        "include_melee": True
    }

    # Populate healer summary_by_class
    for class_type, class_rows in healer_summary.items():
        dispel_set = set()
        for row in class_rows:
            dispel_set.update(row["dispels"].keys())
        context["dispels_all"][class_type] = sorted(dispel_set)
        context["summary_by_class"][class_type] = []

        for row in class_rows:
            context["summary_by_class"][class_type].append({
                "name": row["name"],
                "healing": f"{row['healing']:,}",
                "overhealing": f"{row['overhealing']:,}",
                "spells": row["spells"],
                "dispels": row["dispels"],
                "fear_ward": row.get("fear_ward", "") if class_type == "Priest" else "",
                "mana_potions": row.get("mana_potions") or row.get("resources", {}).get("Major Mana Potion", 0),
                "dark_runes": row.get("dark_runes") or row.get("resources", {}).get("Dark Rune", 0)
            })

    # Populate melee_classes with unified spell headers
    for class_name in melee_summary:
        all_spells = set()
        for row in melee_summary[class_name]:
            all_spells.update(spell for spell, count in row["casts"].items() if count > 0)

        sorted_spells = sorted(all_spells)
        context["melee_classes"].append({
            "class_name": class_name,
            "spells": sorted_spells,
            "players": []
        })

        for row in melee_summary[class_name]:
            context["melee_classes"][-1]["players"].append({
                "name": row["name"],
                "damage": f"{row['total']:,}",
                "spells_map": { spell: row["casts"].get(spell, 0) for spell in sorted_spells }
            })

    # Populate ranged_classes with unified spell headers
    for class_name in ranged_summary:
        all_spells = set()
        for row in ranged_summary[class_name]:
            all_spells.update(spell for spell, count in row["casts"].items() if count > 0)

        sorted_spells = sorted(all_spells)
        context["ranged_classes"].append({
            "class_name": class_name,
            "spells": sorted_spells,
            "players": []
        })

        for row in ranged_summary[class_name]:
            context["ranged_classes"][-1]["players"].append({
                "name": row["name"],
                "damage": f"{row['total']:,}",
                "spells_map": { spell: row["casts"].get(spell, 0) for spell in sorted_spells }
            })

    rendered = template.render(context)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    print(f"\n✅ Markdown summary exported to: {output_path}")
