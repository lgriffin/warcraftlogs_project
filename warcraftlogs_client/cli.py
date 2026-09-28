#!/usr/bin/env python3
"""
Unified CLI for Warcraft Logs Analysis Tool.

This module provides a single entry point for all analysis modes:
- unified: Complete role-based analysis (default)
- healer / tank / melee / ranged: The same analysis, limited to one role
- consumes: Consumables analysis across multiple raids
- history: Query historical character performance
- player: Discover the reports a character is in and collect them on a player page
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import requests
from wcl_core.common.errors import WarcraftLogsError

from .version import __version__

if TYPE_CHECKING:
    from .database import PerformanceDB
    from .services import AppContext, PlayerLog, PlayerRef, Spread


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="warcraftlogs-analyzer",
        description="Analyze Warcraft Logs with focus on spell casts and utility usage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s unified --md                    # Full analysis with markdown export
  %(prog)s unified --save                  # Full analysis + save to database
  %(prog)s healer                          # Healer section of the analysis
  %(prog)s tank                            # Tank mitigation analysis
  %(prog)s melee                           # Melee DPS analysis
  %(prog)s ranged                          # Ranged DPS analysis
  %(prog)s consumes ID1 ID2               # Consumables across raids
  %(prog)s history Hadur                   # Show historical performance for Hadur
  %(prog)s player discover Hadur -s gehennas  # Find reports Hadur is in
  %(prog)s player add Hadur --new          # Import and add every newly found report
  %(prog)s player role Hadur healer         # Always analyse Hadur as a healer
  %(prog)s player lineage Hadur             # Min / mean / max across Hadur's raids
        """,
    )

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output (INFO level logging)")
    parser.add_argument("--debug", action="store_true", help="Enable debug output (DEBUG level logging)")

    subparsers = parser.add_subparsers(dest="command", help="Analysis mode to run", metavar="COMMAND")

    # Unified analysis (default)
    unified_parser = subparsers.add_parser(
        "unified",
        help="Complete role-based analysis (default)",
    )
    unified_parser.add_argument("--md", action="store_true", help="Export results as Markdown report")
    unified_parser.add_argument("--save", action="store_true", help="Save results to local database")
    unified_parser.add_argument("--report-id", type=str, help="Override report ID from config")

    # Role-focused views over the same unified analysis
    role_help = {
        "healer": "Healer-focused analysis",
        "tank": "Tank mitigation analysis",
        "melee": "Melee DPS analysis",
        "ranged": "Ranged DPS analysis",
    }
    for role, help_text in role_help.items():
        role_parser = subparsers.add_parser(role, help=help_text)
        role_parser.add_argument("--md", action="store_true", help="Export this role's analysis as a Markdown report")
        role_parser.add_argument("--save", action="store_true", help="Save results to local database")
        role_parser.add_argument("--report-id", type=str, help="Override report ID from config")
        if role == "healer":
            # Kept so existing scripts don't break; healers are always detected dynamically now.
            role_parser.add_argument("--use-dynamic-roles", action="store_true", help=argparse.SUPPRESS)

    # Consumes analysis
    consumes_parser = subparsers.add_parser("consumes", help="Consumables analysis across raids")
    consumes_parser.add_argument("raid_ids", nargs="+", help="Raid IDs to analyze")
    consumes_parser.add_argument("--csv", type=str, help="Export results to CSV file")
    consumes_parser.add_argument(
        "--md", type=str, nargs="?", const="auto", help="Export results as Markdown report (optional path)"
    )
    consumes_parser.add_argument("--healers", action="store_true", help="Include healer personal buffs")
    consumes_parser.add_argument("--save", action="store_true", help="Save results to local database")

    # History query
    history_parser = subparsers.add_parser("history", help="Query historical character performance")
    history_parser.add_argument("character_name", nargs="?", help="Character name to look up")
    history_parser.add_argument("--all", action="store_true", help="Show all tracked characters")
    history_parser.add_argument("--raids", action="store_true", help="Show imported raid list")
    history_parser.add_argument(
        "--role", type=str, choices=["healer", "tank", "melee", "ranged"], help="Filter trend by role"
    )

    # Player page
    player_parser = subparsers.add_parser("player", help="Discover and collect the reports a character is in")
    player_sub = player_parser.add_subparsers(dest="player_command", metavar="ACTION")

    def _player_args(p: argparse.ArgumentParser, name_required: bool = True) -> None:
        p.add_argument("name", nargs=None if name_required else "?", help="Character name")
        p.add_argument("--server", "-s", help="Server (default: the character's page, else config default_server)")
        p.add_argument("--region", "-r", help="Region (default: the character's page, else config default_region)")
        p.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    discover_parser = player_sub.add_parser("discover", help="List reports the character appears in")
    _player_args(discover_parser)
    discover_parser.add_argument("--limit", type=int, default=50, help="Reports to fetch from Warcraft Logs")
    discover_parser.add_argument("--local", action="store_true", help="Only search the local database (no API)")

    add_parser = player_sub.add_parser("add", help="Add reports (codes or URLs) to the character's page")
    _player_args(add_parser)
    add_parser.add_argument("reports", nargs="*", help="Report codes or Warcraft Logs report URLs")
    add_parser.add_argument("--new", action="store_true", help="Add every newly discovered report")
    add_parser.add_argument("--limit", type=int, default=50, help="Reports to search when using --new")
    add_parser.add_argument("--no-verify", action="store_true", help="Skip checking the character is in the report")

    show_parser = player_sub.add_parser("show", help="Show the character's page")
    _player_args(show_parser)

    remove_parser = player_sub.add_parser("remove", help="Remove reports from the character's page")
    _player_args(remove_parser)
    remove_parser.add_argument("reports", nargs="+", help="Report codes or URLs")

    dismiss_parser = player_sub.add_parser("dismiss", help="Hide reports from discovery without adding them")
    _player_args(dismiss_parser)
    dismiss_parser.add_argument("reports", nargs="+", help="Report codes or URLs")

    role_parser = player_sub.add_parser("role", help="Show or force the role a character is analysed as")
    role_parser.add_argument("name", help="Character name")
    role_parser.add_argument("role", nargs="?", choices=["healer", "tank", "melee", "ranged", "dps"])
    role_parser.add_argument("--report", help="Only for this report (code or URL); default is every raid")
    role_parser.add_argument("--clear", action="store_true", help="Remove the override and let analysis guess again")
    role_parser.add_argument(
        "--no-reanalyze", action="store_true", help="Save the override without re-analysing imported raids"
    )
    role_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    lineage_parser = player_sub.add_parser("lineage", help="Min / mean / max of a character's numbers across raids")
    lineage_parser.add_argument("name", help="Character name")
    lineage_parser.add_argument("--top", type=int, default=15, help="Spells and consumables to list")
    lineage_parser.add_argument("--include-reference", action="store_true", help="Also count reference raids")
    lineage_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    list_parser = player_sub.add_parser("list", help="List player pages")
    list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    return parser


def run_unified_analysis(args: argparse.Namespace, role: str | None = None) -> int:
    from wcl_core.spell_manager import reset_spell_manager

    from .renderers.console import render_raid_analysis
    from .services import AppContext, RaidService

    reset_spell_manager()
    ctx = AppContext.from_config_file()
    report_id = args.report_id if hasattr(args, "report_id") and args.report_id else ctx.config["report_id"]
    raids = RaidService(ctx)

    analysis = raids.analyze(report_id)

    render_raid_analysis(analysis, role=role)

    if hasattr(args, "md") and args.md:
        from .renderers.markdown import export_raid_analysis

        path = export_raid_analysis(analysis, role=role)
        print(f"\nMarkdown report exported to: {path}")

    if hasattr(args, "save") and args.save:
        raids.save(analysis)
        print(f"\nResults saved to database for report {report_id}")

    return 0


def run_role_analysis(args: argparse.Namespace) -> int:
    return run_unified_analysis(args, role=args.command)


def run_consumes_analysis(args: argparse.Namespace) -> int:
    try:
        from wcl_core.consumes_analysis import run_consumes_analysis as _run

        md_path = getattr(args, "md", None)
        _run(args.raid_ids, args.csv, include_healers=args.healers, markdown_path=md_path)
        return 0
    except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
        print(f"Error running consumes analysis: {e}")
        return 1


def run_history_query(args: argparse.Namespace) -> int:  # noqa: C901
    from .database import PerformanceDB

    with PerformanceDB() as db:
        if hasattr(args, "raids") and args.raids:
            raids = db.get_raid_list()
            if not raids:
                print("No raids imported yet. Use --save when running analysis.")
                return 0
            print(f"\n{'Date':<22} {'Title':<30} {'Report ID':<20}")
            print("-" * 75)
            for r in raids:
                print(f"{r['raid_date']:<22} {r['title']:<30} {r['report_id']:<20}")
            return 0

        if hasattr(args, "all") and args.all:
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
        if history.first_seen and history.last_seen:
            print(f"Active: {history.first_seen.strftime('%Y-%m-%d')} to {history.last_seen.strftime('%Y-%m-%d')}")
        if history.avg_healing is not None:
            print(f"Avg Healing: {history.avg_healing:,.0f}")
        if history.avg_damage is not None:
            print(f"Avg Damage: {history.avg_damage:,.0f}")
        if history.avg_mitigation_percent is not None:
            print(f"Avg Mitigation: {history.avg_mitigation_percent:.1f}%")
        print(f"Total Consumables Used: {history.total_consumables_used}")

        role = args.role if hasattr(args, "role") and args.role else None
        if role == "healer" or (role is None and history.avg_healing is not None):
            trend = db.get_healer_trend(args.character_name)
            if trend:
                print(f"\n{'Date':<22} {'Raid':<25} {'Healing':>12} {'Overheal%':>10}")
                print("-" * 72)
                for row in trend:
                    print(
                        f"{row['raid_date']:<22} {row['title']:<25} "
                        f"{row['total_healing']:>12,} {row['overheal_percent']:>9.1f}%"
                    )

        if role == "tank" or (role is None and history.avg_mitigation_percent is not None):
            trend = db.get_tank_trend(args.character_name)
            if trend:
                print(f"\n{'Date':<22} {'Raid':<25} {'Taken':>12} {'Mitigation%':>12}")
                print("-" * 75)
                for row in trend:
                    print(
                        f"{row['raid_date']:<22} {row['title']:<25} "
                        f"{row['total_damage_taken']:>12,} {row['mitigation_percent']:>11.1f}%"
                    )

        if role in ("melee", "ranged") or (role is None and history.avg_damage is not None):
            trend = db.get_dps_trend(args.character_name)
            if trend:
                print(f"\n{'Date':<22} {'Raid':<25} {'Role':<8} {'Damage':>12}")
                print("-" * 70)
                for row in trend:
                    print(f"{row['raid_date']:<22} {row['title']:<25} {row['role']:<8} {row['total_damage']:>12,}")

    return 0


def _resolve_player(db: "PerformanceDB", args: argparse.Namespace, config: dict[str, Any]) -> "PlayerRef":
    """Build a PlayerRef from args, filling server/region from an existing page or config."""
    from .services.player_page import PlayerRef

    server, region = args.server, args.region
    if not server or not region:
        pages = db.find_player_pages(args.name)
        if len(pages) == 1:
            server = server or pages[0]["server"]
            region = region or pages[0]["region"]
        elif len(pages) > 1 and not server:
            options = ", ".join(f"{p['server']}-{p['region']}" for p in pages)
            raise ValueError(f"{args.name} has pages on several servers ({options}); pass --server")
    if not server or not region:
        server = server or config.get("default_server", "")
        region = region or config.get("default_region", "")
    return PlayerRef.create(args.name, server, region)


def _print_logs(logs: Sequence["PlayerLog"]) -> None:
    if not logs:
        print("No reports found.")
        return
    print(f"\n{'Date':<12} {'Code':<18} {'Status':<10} {'Imported':<9} {'Zone':<22} Title")
    print("-" * 100)
    for log in logs:
        imported = "yes" if log.imported else "no"
        print(f"{log.date_formatted:<12} {log.code:<18} {log.status:<10} {imported:<9} {log.zone[:21]:<22} {log.title}")


def _run_player_role(ctx: "AppContext", db: "PerformanceDB", args: argparse.Namespace) -> int:
    import json

    from .services import RoleOverrideService, parse_report_code

    report = None
    if args.report:
        report = parse_report_code(args.report)
        if report is None:
            print(f"Not a report code or URL: {args.report}")
            return 1
    if args.role is None and not args.clear:
        overrides = RoleOverrideService(db).list_overrides(args.name)
        if args.json:
            print(json.dumps(overrides, indent=2))
        elif not overrides:
            print(f"No role override for {args.name}; roles are detected per raid.")
        else:
            for o in overrides:
                print(f"{o['character_name']:<18} {o['role']:<8} {o['report_id'] or 'all raids'}")
        return 0

    service = RoleOverrideService.from_context(ctx, db, with_api=not args.no_reanalyze)
    progress = None if args.json else print
    reanalyze = not args.no_reanalyze
    if args.clear:
        results = service.clear(args.name, report, reanalyze=reanalyze, progress=progress)
    else:
        results = service.set(args.name, args.role, report, reanalyze=reanalyze, progress=progress)
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        scope = report or "every raid"
        print(f"{args.name}: {'override cleared' if args.clear else args.role} for {scope}.")
        for r in results:
            print(f"  {r.report_id} (was {r.old_role}): {r.message}")
    return 0 if all(r.ok for r in results) else 1


def _run_player_lineage(db: "PerformanceDB", args: argparse.Namespace) -> int:
    import json

    from .services import character_lineage

    sources = ("guild", "reference") if args.include_reference else ("guild",)
    lineage = character_lineage(db, args.name, sources)
    if lineage is None:
        print(f"No raids stored for '{args.name}'.")
        return 1
    if args.json:
        print(json.dumps(lineage.to_dict(), indent=2))
        return 0

    roles = ", ".join(f"{n} {r}" for r, n in lineage.role_counts.items())
    print(f"=== {lineage.character}: {lineage.raids} raids ({roles}), {lineage.first_raid} to {lineage.last_raid} ===")

    def table(title: str, spreads: Sequence["Spread"]) -> None:
        if not spreads:
            return
        print(f"\n{title:<34} {'Role':<7} {'Min':>11} {'Mean':>11} {'Max':>11} {'Raids':>6}")
        print("-" * 84)
        for sp in spreads:
            label = sp.name if len(sp.name) <= 33 else sp.name[:32] + "…"
            print(
                f"{label:<34} {sp.role or 'all':<7} {sp.min:>11,.1f} {sp.mean:>11,.1f} {sp.max:>11,.1f} {sp.raids:>6}"
            )

    table("Per raid", lineage.metrics)
    table("Casts per raid", lineage.casts[: args.top])
    table("Consumables per raid", lineage.consumables[: args.top])
    return 0


def run_player_command(args: argparse.Namespace) -> int:  # noqa: C901
    import json

    from .services import AppContext, PlayerPageService

    action = getattr(args, "player_command", None)
    if not action:
        print("Specify an action: discover, add, show, remove, dismiss, role, lineage or list.")
        return 1

    ctx = AppContext.from_config_file()
    with ctx.db() as db:
        if action == "list":
            pages = PlayerPageService(db).list_pages()
            if args.json:
                print(json.dumps(pages, indent=2))
            elif not pages:
                print("No player pages yet. Use 'player discover NAME' to start one.")
            else:
                for p in pages:
                    print(f"{p['name']:<18} {p['server']:<20} {p['region'].upper():<4} {p['log_count']:>4} reports")
            return 0

        if action == "role":
            return _run_player_role(ctx, db, args)
        if action == "lineage":
            return _run_player_lineage(db, args)

        player = _resolve_player(db, args, ctx.config)
        needs_api = action in ("add",) or (action == "discover" and not args.local)
        service = PlayerPageService.from_context(ctx, db, with_api=needs_api)

        if action == "discover":
            logs = service.discover_reports(player, limit=args.limit)
            if args.json:
                print(json.dumps([log.to_dict() for log in logs], indent=2))
            else:
                print(f"Reports for {player.label}:")
                _print_logs(logs)
                new = sum(1 for log in logs if log.status == "new")
                if new:
                    print(f"\n{new} new. Add them with: player add {player.name} --new")
            return 0

        if action == "add":
            refs = list(args.reports)
            known = {}
            if args.new:
                found = [log for log in service.discover_reports(player, limit=args.limit) if log.status == "new"]
                known = {log.code: log for log in found}
                refs.extend(known)
            if not refs:
                print("Nothing to add. Pass report codes/URLs or --new.")
                return 1
            results = service.add_reports(
                player, refs, verify=not args.no_verify, known=known, progress=None if args.json else print
            )
            if args.json:
                print(json.dumps([r.to_dict() for r in results], indent=2))
            else:
                for r in results:
                    print(f"{r.code:<18} {r.outcome:<16} {r.message}")
            return 0 if all(r.ok for r in results) else 1

        if action == "show":
            page = service.get_page(player)
            if args.json:
                print(json.dumps(page.to_dict(), indent=2))
                return 0
            print(f"=== {player.label} ===")
            if page.history:
                h = page.history
                print(f"{h['player_class']}, {h['total_raids']} raids tracked ({h['first_seen']} to {h['last_seen']})")
            _print_logs(page.logs)
            return 0

        if action == "remove":
            print(f"Removed {service.remove(player, args.reports)} report(s) from {player.label}.")
            return 0

        if action == "dismiss":
            print(f"Dismissed {service.dismiss(player, args.reports)} report(s) for {player.label}.")
            return 0

    return 1


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    level = logging.WARNING
    if getattr(args, "verbose", False):
        level = logging.INFO
    if getattr(args, "debug", False):
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(name)s %(levelname)s: %(message)s")

    if not args.command:
        args.command = "unified"
        args.md = False
        args.save = False
        args.report_id = None

    commands: dict[str, Callable[[argparse.Namespace], int]] = {
        "unified": run_unified_analysis,
        "healer": run_role_analysis,
        "tank": run_role_analysis,
        "melee": run_role_analysis,
        "ranged": run_role_analysis,
        "consumes": run_consumes_analysis,
        "history": run_history_query,
        "player": run_player_command,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            return handler(args)
        except (WarcraftLogsError, requests.RequestException, KeyError, ValueError, TypeError, OSError) as e:
            print(f"Error: {e}")
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
