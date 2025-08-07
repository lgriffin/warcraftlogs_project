#!/usr/bin/env python3
"""
Unified CLI for Warcraft Logs Analysis Tool

This module provides a single entry point for all analysis modes:
- unified: Complete role-based analysis (default)
- healer: Healer-focused analysis  
- tank: Tank mitigation analysis
- melee: Melee DPS analysis
- ranged: Ranged DPS analysis
"""

import argparse
import sys
from typing import Optional

def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog='warcraftlogs-analyzer',
        description='Analyze Warcraft Logs with focus on spell casts and utility usage',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s unified --md                    # Full analysis with markdown export
  %(prog)s healer --use-dynamic-roles     # Healer analysis with auto-detection
  %(prog)s tank                           # Tank mitigation analysis
  %(prog)s melee                          # Melee DPS analysis
  %(prog)s ranged                         # Ranged DPS analysis
        """
    )
    
    # Global arguments
    parser.add_argument('--version', action='version', version='%(prog)s 1.0.0')
    
    # Create subparsers
    subparsers = parser.add_subparsers(
        dest='command',
        help='Analysis mode to run',
        metavar='COMMAND'
    )
    
    # Unified analysis (default)
    unified_parser = subparsers.add_parser(
        'unified',
        help='Complete role-based analysis (default)',
        description='Automatically classify players and generate comprehensive analysis'
    )
    unified_parser.add_argument(
        '--md', 
        action='store_true', 
        help='Export results as Markdown report'
    )
    
    # Healer analysis
    healer_parser = subparsers.add_parser(
        'healer',
        help='Healer-focused analysis',
        description='Analyze healing output, utility usage, and consumables'
    )
    healer_parser.add_argument(
        '--md', 
        action='store_true', 
        help='Export results as Markdown report'
    )
    healer_parser.add_argument(
        '--use-dynamic-roles', 
        action='store_true',
        help='Use dynamic healer classification (ignore characters.json)'
    )
    
    # Tank analysis
    tank_parser = subparsers.add_parser(
        'tank',
        help='Tank mitigation analysis',
        description='Analyze damage taken, mitigation, and defensive abilities'
    )
    
    # Melee analysis
    melee_parser = subparsers.add_parser(
        'melee',
        help='Melee DPS analysis',
        description='Analyze melee damage abilities and cooldown usage'
    )
    
    # Ranged analysis
    ranged_parser = subparsers.add_parser(
        'ranged',
        help='Ranged DPS analysis', 
        description='Analyze ranged damage, rotations, and utility spells'
    )
    
    return parser

def run_unified_analysis(args) -> int:
    """Run the unified role-based analysis."""
    try:
        from .main import run_unified_report
        run_unified_report(args)
        return 0
    except Exception as e:
        print(f"❌ Error running unified analysis: {e}")
        return 1

def run_healer_analysis(args) -> int:
    """Run healer-focused analysis."""
    try:
        from .new_main import run_full_report
        run_full_report(markdown=args.md, use_dynamic_roles=args.use_dynamic_roles)
        return 0
    except Exception as e:
        print(f"❌ Error running healer analysis: {e}")
        return 1

def run_tank_analysis(args) -> int:
    """Run tank mitigation analysis."""
    try:
        from .tank_main import run_tank_report
        run_tank_report()
        return 0
    except Exception as e:
        print(f"❌ Error running tank analysis: {e}")
        return 1

def run_melee_analysis(args) -> int:
    """Run melee DPS analysis."""
    try:
        from .melee_main import run_melee_report
        run_melee_report()
        return 0
    except Exception as e:
        print(f"❌ Error running melee analysis: {e}")
        return 1

def run_ranged_analysis(args) -> int:
    """Run ranged DPS analysis."""
    try:
        from .ranged_main import run_ranged_report
        run_ranged_report()
        return 0
    except Exception as e:
        print(f"❌ Error running ranged analysis: {e}")
        return 1

def main() -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Default to unified analysis if no command specified
    if not args.command:
        args.command = 'unified'
        args.md = False
    
    # Route to appropriate analysis function
    if args.command == 'unified':
        return run_unified_analysis(args)
    elif args.command == 'healer':
        return run_healer_analysis(args)
    elif args.command == 'tank':
        return run_tank_analysis(args)
    elif args.command == 'melee':
        return run_melee_analysis(args)
    elif args.command == 'ranged':
        return run_ranged_analysis(args)
    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    sys.exit(main()) 