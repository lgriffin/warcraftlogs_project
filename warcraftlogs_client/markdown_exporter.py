import os
from jinja2 import Environment, FileSystemLoader
import datetime

def export_combined_markdown(metadata, summaries, spell_names, include_healer, include_melee, report_title, output_path):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

    # Set up the environment
    env = Environment(
        loader=FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True
    )

    # Load the template
    template = env.get_template("healing_report.md.j2")
    log_date = datetime.datetime.fromtimestamp(metadata["start"] / 1000).strftime("%Y-%m-%d")

    context = {
        "report_title": report_title,
        "log_date": log_date,
        "log_url": f"https://www.warcraftlogs.com/reports/{metadata['report_id']}",
        "summary_by_class": {},
        "dispels_all": {},
        "melee_classes": [],
        "healers": [],
        "include_healer": include_healer,
        "include_melee": include_melee
    }

    if include_healer:
        for class_type in ["Priest", "Paladin", "Druid"]:
            context["summary_by_class"][class_type] = []
            context["dispels_all"][class_type] = set()
            for row in summaries.get(class_type, []):
                context["dispels_all"][class_type].update(row.get("dispels", {}).keys())

        for class_type in context["dispels_all"]:
            context["dispels_all"][class_type] = sorted(context["dispels_all"][class_type])

        for class_type in ["Priest", "Paladin", "Druid"]:
            for row in summaries.get(class_type, []):
                context["summary_by_class"][class_type].append({
                    "name": row["name"],
                    "healing": f"{row['healing']:,}",
                    "overhealing": f"{row['overhealing']:,}",
                    "spells": {
                        spell: row["spells"].get(spell, "-")
                        for spell in sorted(spell_names.get(class_type, []))
                    },
                    "dispels": {
                        dispel: row["dispels"].get(dispel, "-")
                        for dispel in context["dispels_all"][class_type]
                    },
                    "fear_ward": row.get("fear_ward", None),
                    "mana_potions": row["resources"].get("Major Mana Potion", 0),
                    "dark_runes": row["resources"].get("Dark Rune", 0)
                })

    if include_melee:
        for class_type in summaries:
            if class_type not in ["Rogue", "Warrior"]:
                continue
            context["melee_classes"].append({
                "class_name": class_type,
                "players": []
            })
            for row in summaries[class_type]:
                player_data = {
                    "name": row["name"],
                    "damage": f"{row['damage']:,}",
                    "spells": []
                }
                for spell in sorted(spell_names[class_type]):
                    casts = row["casts"].get(spell, 0)
                    damage = row["spells"].get(spell, 0)
                    player_data["spells"].append({
                        "name": spell,
                        "casts": casts,
                        "damage": f"{damage:,}" if damage else "-"
                    })
                context["melee_classes"][-1]["players"].append(player_data)

    rendered = template.render(context)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    print(f"\n✅ Markdown report exported to: {output_path}")