#!/usr/bin/env python3
"""
Unified CLI for Warcraft Logs Analysis Tool.

This module provides a single entry point for all analysis modes:
- unified: Complete role-based analysis (default)
- healer: Healer-focused analysis
- tank: Tank mitigation analysis
- melee: Melee DPS analysis
- ranged: Ranged DPS analysis
- consumes: Consumables analysis across multiple raids
- history: Query historical character performance
"""

import argparse
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='warcraftlogs-analyzer',
        description='Analyze Warcraft Logs with focus on spell casts and utility usage',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s unified --md                    # Full analysis with markdown export
  %(prog)s unified --save                  # Full analysis + save to database
  %(prog)s healer --use-dynamic-roles      # Healer analysis with auto-detection
  %(prog)s tank                            # Tank mitigation analysis
  %(prog)s melee                           # Melee DPS analysis
  %(prog)s ranged                          # Ranged DPS analysis
  %(prog)s consumes ID1 ID2               # Consumables across raids
  %(prog)s history Hadur                   # Show historical performance for Hadur
        """
    )

    parser.add_argument('--version', action='version', version='%(prog)s 2.0.0')

    subparsers = parser.add_subparsers(
        dest='command',
        help='Analysis mode to run',
        metavar='COMMAND'
    )

    # Unified analysis (default)
    unified_parser = subparsers.add_parser(
        'unified',
        help='Complete role-based analysis (default)',
    )
    unified_parser.add_argument('--md', action='store_true', help='Export results as Markdown report')
    unified_parser.add_argument('--save', action='store_true', help='Save results to local database')
    unified_parser.add_argument('--report-id', type=str, help='Override report ID from config')

    # Healer analysis
    healer_parser = subparsers.add_parser('healer', help='Healer-focused analysis')
    healer_parser.add_argument('--md', action='store_true', help='Export results as Markdown report')
    healer_parser.add_argument(
        '--use-dynamic-roles', action='store_true',
        help='Use dynamic healer classification (ignore characters.json)'
    )

    # Tank analysis
    subparsers.add_parser('tank', help='Tank mitigation analysis')

    # Melee analysis
    subparsers.add_parser('melee', help='Melee DPS analysis')

    # Ranged analysis
    subparsers.add_parser('ranged', help='Ranged DPS analysis')

    # Consumes analysis
    consumes_parser = subparsers.add_parser('consumes', help='Consumables analysis across raids')
    consumes_parser.add_argument('raid_ids', nargs='+', help='Raid IDs to analyze')
    consumes_parser.add_argument('--csv', type=str, help='Export results to CSV file')
    consumes_parser.add_argument('--healers', action='store_true', help='Include healer personal buffs')
    consumes_parser.add_argument('--save', action='store_true', help='Save results to local database')

    # History query
    history_parser = subparsers.add_parser('history', help='Query historical character performance')
    history_parser.add_argument('character_name', nargs='?', help='Character name to look up')
    history_parser.add_argument('--all', action='store_true', help='Show all tracked characters')
    history_parser.add_argument('--raids', action='store_true', help='Show imported raid list')
    history_parser.add_argument('--role', type=str, choices=['healer', 'tank', 'melee', 'ranged'],
                                help='Filter trend by role')

    return parser


def run_unified_analysis(args) -> int:
    from .auth import TokenManager
    from .config import load_config
    from .client import WarcraftLogsClient
    from .analysis import analyze_raid
    from .renderers.console import render_raid_analysis
    from .spell_manager import reset_spell_manager

    reset_spell_manager()
    config = load_config()
    report_id = args.report_id if hasattr(args, 'report_id') and args.report_id else config["report_id"]
    role_thresholds = config.get("role_thresholds", {})

    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    analysis = analyze_raid(
        client, report_id,
        healer_threshold=role_thresholds.get("healer_min_healing", 50000),
        tank_min_taken=role_thresholds.get("tank_min_taken", 150000),
        tank_min_mitigation=role_thresholds.get("tank_min_mitigation", 40),
    )

    render_raid_analysis(analysis)

    if hasattr(args, 'md') and args.md:
        from .markdown_exporter import export_combined_markdown
        _export_markdown_from_analysis(analysis, config)

    if hasattr(args, 'save') and args.save:
        from .database import PerformanceDB
        with PerformanceDB() as db:
            db.import_raid(analysis)
        print(f"\nResults saved to database for report {report_id}")

    return 0


def run_healer_analysis(args) -> int:
    try:
        from .new_main import run_full_report
        run_full_report(markdown=args.md, use_dynamic_roles=args.use_dynamic_roles)
        return 0
    except Exception as e:
        print(f"Error running healer analysis: {e}")
        return 1


def run_tank_analysis(args) -> int:
    try:
        from .tank_main import run_tank_report
        run_tank_report()
        return 0
    except Exception as e:
        print(f"Error running tank analysis: {e}")
        return 1


def run_melee_analysis(args) -> int:
    try:
        from .melee_main import run_melee_report
        run_melee_report()
        return 0
    except Exception as e:
        print(f"Error running melee analysis: {e}")
        return 1


def run_ranged_analysis(args) -> int:
    try:
        from .ranged_main import run_ranged_report
        run_ranged_report()
        return 0
    except Exception as e:
        print(f"Error running ranged analysis: {e}")
        return 1


def run_consumes_analysis(args) -> int:
    try:
        from .consumes_analysis import run_consumes_analysis as _run
        _run(args.raid_ids, args.csv, include_healers=args.healers)
        return 0
    except Exception as e:
        print(f"Error running consumes analysis: {e}")
        return 1


def run_history_query(args) -> int:
    from .database import PerformanceDB

    with PerformanceDB() as db:
        if hasattr(args, 'raids') and args.raids:
            raids = db.get_raid_list()
            if not raids:
                print("No raids imported yet. Use --save when running analysis.")
                return 0
            print(f"\n{'Date':<22} {'Title':<30} {'Report ID':<20}")
            print("-" * 75)
            for r in raids:
                print(f"{r['raid_date']:<22} {r['title']:<30} {r['report_id']:<20}")
            return 0

        if hasattr(args, 'all') and args.all:
            characters = db.get_all_characters()
            if not characters:
                print("No characters tracked yet. Use --save when running analysis.")
                return 0
            print(f"\n{'Character':<18} {'Class':<12} {'Raids':>6} {'First Seen':<12} {'Last Seen':<12}")
            print("-" * 65)
            for c in characters:
                first = c.first_seen.strftime("%Y-%m-%d") if c.first_seen else "?"
                last = c.last_seen.strftime("%Y-%m-%d") if c.last_seen else "?"
                print(f"{c.name:<18} {c.player_class:<12} {c.total_raids:>6} {first:<12} {last:<12}")
            return 0

        if not args.character_name:
            print("Specify a character name, --all, or --raids.")
            return 1

        history = db.get_character_history(args.character_name)
        if not history:
            print(f"No data found for '{args.character_name}'.")
            return 1

        print(f"\n=== {history.name} ({history.player_class}) ===")
        print(f"Raids tracked: {history.total_raids}")
        if history.first_seen:
            print(f"Active: {history.first_seen.strftime('%Y-%m-%d')} to {history.last_seen.strftime('%Y-%m-%d')}")
        if history.avg_healing is not None:
            print(f"Avg Healing: {history.avg_healing:,.0f}")
        if history.avg_damage is not None:
            print(f"Avg Damage: {history.avg_damage:,.0f}")
        if history.avg_mitigation_percent is not None:
            print(f"Avg Mitigation: {history.avg_mitigation_percent:.1f}%")
        print(f"Total Consumables Used: {history.total_consumables_used}")

        role = args.role if hasattr(args, 'role') and args.role else None
        if role == "healer" or (role is None and history.avg_healing is not None):
            trend = db.get_healer_trend(args.character_name)
            if trend:
                print(f"\n{'Date':<22} {'Raid':<25} {'Healing':>12} {'Overheal%':>10}")
                print("-" * 72)
                for row in trend:
                    print(f"{row['raid_date']:<22} {row['title']:<25} "
                          f"{row['total_healing']:>12,} {row['overheal_percent']:>9.1f}%")

        if role == "tank" or (role is None and history.avg_mitigation_percent is not None):
            trend = db.get_tank_trend(args.character_name)
            if trend:
                print(f"\n{'Date':<22} {'Raid':<25} {'Taken':>12} {'Mitigation%':>12}")
                print("-" * 75)
                for row in trend:
                    print(f"{row['raid_date']:<22} {row['title']:<25} "
                          f"{row['total_damage_taken']:>12,} {row['mitigation_percent']:>11.1f}%")

        if role in ("melee", "ranged") or (role is None and history.avg_damage is not None):
            trend = db.get_dps_trend(args.character_name)
            if trend:
                print(f"\n{'Date':<22} {'Raid':<25} {'Role':<8} {'Damage':>12}")
                print("-" * 70)
                for row in trend:
                    print(f"{row['raid_date']:<22} {row['title']:<25} "
                          f"{row['role']:<8} {row['total_damage']:>12,}")

    return 0


def _export_markdown_from_analysis(analysis, config):
    """Bridge between new analysis model and existing markdown exporter."""
    from collections import defaultdict, OrderedDict

    grouped_summary = {"Priest": [], "Paladin": [], "Druid": [], "Shaman": []}
    all_spell_names_by_class = {"Priest": set(), "Paladin": set(), "Druid": set(), "Shaman": set()}

    for h in analysis.healers:
        per_character_spells = {s.spell_name: s.casts for s in h.spells}
        healing_by_name = {s.spell_name: s.total_amount for s in h.spells}
        dispels_dict = {d.spell_name: d.casts for d in h.dispels}
        resources_dict = {r.name: r.count for r in h.resources}
        all_spell_names_by_class[h.player_class].update(per_character_spells.keys())

        grouped_summary[h.player_class].append({
            "name": h.name,
            "healing": h.total_healing,
            "overhealing": h.total_overhealing,
            "spells": per_character_spells,
            "dispels": dispels_dict,
            "resources": resources_dict,
            "healing_spells": healing_by_name,
        })

    melee_summary = defaultdict(list)
    ranged_summary = defaultdict(list)
    all_melee_spells = defaultdict(set)
    all_ranged_spells = defaultdict(set)

    for d in analysis.dps:
        casts = {a.spell_name: a.casts for a in d.abilities}
        damage = {a.spell_name: a.total_amount for a in d.abilities}
        entry = {"name": d.name, "total": d.total_damage, "damage": damage, "casts": casts}
        if d.role == "melee":
            melee_summary[d.player_class].append(entry)
            all_melee_spells[d.player_class].update(casts.keys())
        else:
            ranged_summary[d.player_class].append(entry)
            all_ranged_spells[d.player_class].update(casts.keys())

    for cls in all_melee_spells:
        all_spell_names_by_class[cls] = sorted(all_melee_spells[cls])
    for cls in all_ranged_spells:
        all_spell_names_by_class[cls] = sorted(all_ranged_spells[cls])

    tank_summary = []
    all_taken_abilities = set()
    for t in analysis.tanks:
        for s in t.damage_taken_breakdown:
            all_taken_abilities.add(s.spell_name)

    taken_names = sorted(all_taken_abilities)
    for t in analysis.tanks:
        lookup = {s.spell_name: s.casts for s in t.damage_taken_breakdown}
        tank_summary.append({
            "name": t.name,
            "abilities": [lookup.get(n, 0) for n in taken_names],
        })

    from .markdown_exporter import export_combined_markdown
    export_combined_markdown(
        metadata={
            "title": analysis.metadata.title,
            "owner": analysis.metadata.owner,
            "start": analysis.metadata.start_time,
            "report_id": analysis.metadata.report_id,
        },
        healer_summary=grouped_summary,
        melee_summary=dict(melee_summary),
        ranged_summary=dict(ranged_summary),
        tank_summary=tank_summary,
        tank_abilities=taken_names,
        tank_damage_summary=[],
        spell_names=all_spell_names_by_class,
        report_title=analysis.metadata.title,
    )


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        args.command = 'unified'
        args.md = False
        args.save = False
        args.report_id = None

    commands = {
        'unified': run_unified_analysis,
        'healer': run_healer_analysis,
        'tank': run_tank_analysis,
        'melee': run_melee_analysis,
        'ranged': run_ranged_analysis,
        'consumes': run_consumes_analysis,
        'history': run_history_query,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            return handler(args)
        except Exception as e:
            print(f"Error: {e}")
            return 1

    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
