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
        "summary_by_class": healer_summary,
        "dispels_all": {},  # assumed precomputed if needed
        "melee_classes": [],
        "ranged_classes": [],
        "tank_summary": tank_summary,
        "tank_abilities": tank_abilities,
        "tank_damage_summary": tank_damage_summary,
        "spell_names": spell_names,
        "include_healer": True,
        "include_melee": True
    }

    # Populate melee_classes
    for class_name in melee_summary:
        context["melee_classes"].append({
            "class_name": class_name,
            "players": []
        })
        for row in melee_summary[class_name]:
            context["melee_classes"][-1]["players"].append({
                "name": row["name"],
                "damage": f"{row['total']:,}",
                "spells": [
                    {
                        "name": spell,
                        "casts": row["casts"].get(spell, 0),
                        "damage": "-"
                    } for spell in sorted(spell_names[class_name])
                ]
            })

    # Populate ranged_classes
    for class_name in ranged_summary:
        context["ranged_classes"].append({
            "class_name": class_name,
            "players": []
        })
        for row in ranged_summary[class_name]:
            context["ranged_classes"][-1]["players"].append({
                "name": row["name"],
                "damage": f"{row['total']:,}",
                "spells": [
                    {
                        "name": spell,
                        "casts": row["casts"].get(spell, 0),
                        "damage": "-"
                    } for spell in sorted(spell_names[class_name])
                ]
            })

    rendered = template.render(context)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    print(f"\n✅ Markdown summary exported to: {output_path}")
