from .auth import TokenManager
from .client import WarcraftLogsClient, get_healing_data
from .characters import Characters
from .loader import load_config
from .spell_breakdown import SpellBreakdown
from .healing import OverallHealing
from collections import defaultdict

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

def run_full_report():
    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    characters = Characters("characters.json")
    master_actors = get_master_data(client, report_id)
    name_to_id = {
        actor["name"]: actor["id"]
        for actor in master_actors
        if actor["name"] in characters.get_names()
    }

    summary = []
    class_spell_names = defaultdict(set)

    for name, source_id in name_to_id.items():
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
            healing_by_name = {}

            for spell_id, amount in sorted(spell_totals.items(), key=lambda x: x[1], reverse=True):
                spell_name = str(spell_map.get(spell_id, f"(ID {spell_id})"))
                casts = spell_casts.get(spell_id, 0)
                cast_display = "-" if spell_id == 17543 and casts == 0 else casts
                print(f"{spell_name:<30} {amount:>15,} {cast_display:>10}")
                per_character_spells[spell_name] = casts
                healing_by_name[spell_name] = amount
                class_spell_names[characters.get_class(name)].add(spell_name)

            print(f"\n✅ Total Healing: {total_healing:,}")
            print(f"💤 Total Overhealing: {total_overhealing:,}")

            fear_ward = SpellBreakdown.get_fear_ward_usage(cast_entries)
            if fear_ward and fear_ward["casts"] > 0:
                print(f"\n🛡️  Fear Ward Casts: {fear_ward['casts']}")

            dispels = SpellBreakdown.calculate_dispels(cast_entries)
            if any(dispels.values()):
                print(f"\n🧹 Dispels:")
                for spell_name, count in dispels.items():
                    print(f"  - {spell_name}: {count} casts")

            resources = SpellBreakdown.get_resources_used(cast_entries)
            if resources:
                print(f"\n🔋 Resources Used:")
                for r_name, count in resources.items():
                    print(f"  - {r_name}: {count}")

            summary.append({
                "name": name,
                "class": characters.get_class(name),
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

    priest_view(summary, sorted(class_spell_names["Priest"]))
    paladin_view(summary, sorted(class_spell_names["Paladin"]))
    druid_view(summary, sorted(class_spell_names["Druid"]))

def priest_view(summary, spell_names):
    print("\n======= Priest Team =======")
    print_table(summary, spell_names, "Priest", ["Dispel Magic", "Abolish Disease"], True)

def paladin_view(summary, spell_names):
    print("\n======= Paladin Team =======")
    print_table(summary, spell_names, "Paladin", ["Cleanse"], False)

def druid_view(summary, spell_names):
    print("\n======= Druid Team =======")
    print_table(summary, spell_names, "Druid", ["Remove Curse", "Abolish Poison"], False)

def print_table(summary, spell_names, class_name, dispel_keys, show_fear_ward):
    header = (
        f"{'Character':<15} {'Healing':>12} {'Overheal':>12} " +
        "".join(f"{spell[:14]:>16}" for spell in spell_names) +
        "".join(f"{key:>16}" for key in dispel_keys)
    )
    if show_fear_ward:
        header += f"{'Fear Ward':>12}"
    header += f"{'Restore Mana':>16} {'Dark Rune':>12}"
    print(header)
    print("-" * len(header))

    for row in sorted(summary, key=lambda x: x["healing"], reverse=True):
        if row["class"] != class_name:
            continue

        spell_counts = ""
        for spell in spell_names:
            if spell == "Fire Protection":
                healing = row.get("healing_spells", {}).get("Fire Protection", 0)
                spell_counts += f"{healing:>16,}"
            else:
                spell_counts += f"{row['spells'].get(spell, 0):>16}"

        dispel_values = "".join(f"{row['dispels'].get(d, 0):>16}" for d in dispel_keys)
        fear_ward_val = f"{row['fear_ward']:>12}" if show_fear_ward else ""
        restore_mana = row["resources"].get("Restore Mana", 0)
        dark_rune = row["resources"].get("Dark Rune", 0)

        print(
            f"{row['name']:<15} {row['healing']:>12,} {row['overhealing']:>12,}"
            f"{spell_counts}{dispel_values}{fear_ward_val}{restore_mana:>16}{dark_rune:>12}"
        )

if __name__ == "__main__":
    run_full_report()
