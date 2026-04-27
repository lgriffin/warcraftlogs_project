import argparse
import datetime
import json
from collections import defaultdict

import requests

from .auth import TokenManager
from .client import WarcraftLogsClient, get_damage_done_data
from .config import load_config
from .spell_manager import SpellBreakdown
from . import dynamic_role_parser
from .common.data import get_master_data, get_report_metadata

def print_report_metadata(metadata, present_names):
    print("\n========================")
    print("📝 Report Metadata")
    print("========================")
    print(f"📄 Title: {metadata['title']}")
    print(f"👤 Owner: {metadata['owner']}")
    dt = datetime.datetime.fromtimestamp(metadata['start'] / 1000)
    print(f"📆 Date: {dt.strftime('%A, %B %d %Y %H:%M:%S')}")
    print(f"\n🏹 Ranged Characters Present: {', '.join(sorted(present_names))}")

def print_class_summary_table(class_name, class_summaries, all_abilities):
    print(f"\n======= Team {class_name} =======")
    header = f"{'Character':<15} {'Total Damage':>15} " + "".join(f"{a[:14]:>16}" for a in all_abilities)
    print(header)
    print("-" * len(header))

    for summary in sorted(class_summaries, key=lambda x: x['total'], reverse=True):
        row = f"{summary['name']:<15} {summary['total']:>15,}"
        for ability in all_abilities:
            count = summary['casts'].get(ability, 0)
            row += f"{count:>16}"
        print(row)

def run_ranged_report():
    config = load_config()
    report_id = config["report_id"]

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    metadata = get_report_metadata(client, report_id)
    master_actors = get_master_data(client, report_id)

    class_groups = dynamic_role_parser.group_players_by_class(master_actors)
    ranged_classes = {"Mage", "Warlock", "Hunter"}
    ranged_players_by_class = {
        cls: class_groups.get(cls, []) for cls in ranged_classes
    }

    all_ranged_names = [p["name"] for players in ranged_players_by_class.values() for p in players]
    print_report_metadata(metadata, all_ranged_names)

    for ranged_class, players in ranged_players_by_class.items():
        if not players:
            continue

        print(f"\n====== {ranged_class} Ranged Summary ======")
        print(f"{'Character':<15} {'Total Damage':>15}")
        print("-" * 35)

        class_summary = []
        all_abilities = set()

        for player in players:
            name = player["name"]
            source_id = player["id"]

            try:
                events = get_damage_done_data(client, report_id, source_id)
                spell_map, spell_casts, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, source_id)
                alias_map = SpellBreakdown.spell_id_aliases

                total_damage = 0
                damage_by_ability = defaultdict(int)

                for e in events:
                    if not isinstance(e, dict) or e.get("type") != "damage":
                        continue

                    amount = e.get("amount", 0)
                    spell_id = e.get("abilityGameID")
                    canonical_id = alias_map.get(spell_id, spell_id)
                    ability_name = spell_map.get(canonical_id, f"(ID {spell_id})")

                    total_damage += amount
                    damage_by_ability[ability_name] += amount

                # Use actual cast data instead of counting damage events
                casts_by_ability = {}
                for spell_id, cast_count in spell_casts.items():
                    canonical_id = alias_map.get(spell_id, spell_id)
                    ability_name = spell_map.get(canonical_id, f"(ID {spell_id})")
                    casts_by_ability[ability_name] = casts_by_ability.get(ability_name, 0) + cast_count

                print(f"{name:<15} {total_damage:>15,}")
                print(f"{'Ability':<30} {'Damage':>12} {'Casts':>8}")
                print("-" * 55)
                for ability in sorted(damage_by_ability, key=damage_by_ability.get, reverse=True):
                    dmg = damage_by_ability[ability]
                    casts = casts_by_ability.get(ability, 0)
                    print(f"{ability:<30} {dmg:>12,} {casts:>8}")
                print()

                class_summary.append({
                    "name": name,
                    "total": total_damage,
                    "damage": damage_by_ability,
                    "casts": casts_by_ability
                })
                all_abilities.update(damage_by_ability.keys())

            except (requests.RequestException, KeyError, TypeError, ValueError) as e:
                print(f"Error processing {name}: {e}")

        print_class_summary_table(ranged_class, class_summary, sorted(all_abilities))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate ranged damage summary for Mages, Warlocks, and Hunters.")
    args = parser.parse_args()
    run_ranged_report()
