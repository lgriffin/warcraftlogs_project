from client import get_damage_done_data
from spell_breakdown import SpellBreakdown
from collections import defaultdict

def generate_melee_summary(client, report_id, master_actors):
    print("============================")
    print("📊 Melee Role Breakdown")
    print("============================")

    melee_classes = {"Rogue", "Warrior"}
    grouped_summary = {}
    all_spell_names = {}

    for actor in master_actors:
        if actor["subType"] not in melee_classes:
            continue

        name = actor["name"]
        source_id = actor["id"]
        char_class = actor["subType"]

        try:
            events = get_damage_done_data(client, report_id, source_id)
            spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, source_id)

            total_damage = 0
            damage_by_ability = defaultdict(int)
            casts_by_ability = defaultdict(int)

            for e in events:
                if not isinstance(e, dict):
                    continue
                if e.get("type") != "damage":
                    continue

                amount = e.get("amount", 0)
                spell_id = e.get("abilityGameID")
                ability_name = spell_map.get(spell_id, f"(ID {spell_id})")

                total_damage += amount
                damage_by_ability[ability_name] += amount
                casts_by_ability[ability_name] += 1

            print(f"{name}'s Damage Summary")
            print(f"Total Damage: {total_damage:,}")
            print(f"{'Spell':<30} {'Damage':>15} {'Casts':>10}")
            print("-" * 60)
            for ability in sorted(damage_by_ability, key=damage_by_ability.get, reverse=True):
                dmg = damage_by_ability[ability]
                casts = casts_by_ability[ability]
                print(f"{ability:<30} {dmg:>15,} {casts:>10}")

            summary = {
                "name": name,
                "damage": total_damage,
                "spells": damage_by_ability,
                "casts": casts_by_ability
            }

            if char_class not in grouped_summary:
                grouped_summary[char_class] = []
                all_spell_names[char_class] = set()

            grouped_summary[char_class].append(summary)
            all_spell_names[char_class].update(damage_by_ability.keys())

        except Exception as e:
            print(f"Error processing {name}: {e}")

    return grouped_summary, all_spell_names


def print_melee_table(summary_by_class, all_spell_names):
    print("======== Melee Team ========")
    for class_name, summaries in summary_by_class.items():
        if not summaries:
            continue

        print(f"======= {class_name} Melee Team =======")
        spell_names = sorted(all_spell_names.get(class_name, []))

        header = f"{'Character':<15} {'Total Damage':>15}" + ''.join(f"{spell[:20]:>22}" for spell in spell_names)
        print(header)
        print("-" * len(header))

        for row in sorted(summaries, key=lambda x: x["damage"], reverse=True):
            line = f"{row['name']:<15} {row['damage']:>15,}"
            for spell in spell_names:
                casts = row["casts"].get(spell, 0)
                damage = row["spells"].get(spell, 0)
                if casts:
                    line += f" {damage:,} ({casts})".rjust(22)
                else:
                    line += f"-".rjust(22)
            print(line)
