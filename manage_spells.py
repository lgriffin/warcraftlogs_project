#!/usr/bin/env python3
"""
Spell Configuration Management Utility

This script helps users manage spell configurations for the Warcraft Logs analyzer.
It can validate configurations, add new spells, and provide helpful diagnostics.
"""

import argparse
import json
import os
import sys
from typing import Dict, Any, Optional

def load_json_file(filepath: str) -> Optional[Dict[str, Any]]:
    """Load and parse a JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ File not found: {filepath}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ JSON syntax error in {filepath}: {e}")
        return None
    except Exception as e:
        print(f"❌ Error reading {filepath}: {e}")
        return None

def save_json_file(filepath: str, data: Dict[str, Any]) -> bool:
    """Save data to a JSON file with proper formatting."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ Error saving {filepath}: {e}")
        return False

def validate_configurations() -> bool:
    """Validate spell configuration files."""
    print("🔍 Validating spell configurations...")
    
    # Check if spell_data directory exists
    if not os.path.exists("spell_data"):
        print("❌ spell_data directory not found!")
        print("💡 Run this script from the project root directory.")
        return False
    
    aliases_file = "spell_data/spell_aliases.json"
    names_file = "spell_data/spell_names.json"
    
    # Load files
    aliases_data = load_json_file(aliases_file)
    names_data = load_json_file(names_file)
    
    if aliases_data is None or names_data is None:
        return False
    
    # Flatten aliases
    aliases = {}
    for group_name, group_aliases in aliases_data.items():
        if group_name.startswith('_'):
            continue
        if isinstance(group_aliases, dict):
            for source_id, canonical_id in group_aliases.items():
                try:
                    aliases[int(source_id)] = int(canonical_id)
                except (ValueError, TypeError):
                    print(f"⚠️ Invalid alias: {source_id} -> {canonical_id}")
    
    # Flatten names
    names = {}
    for category_name, category_spells in names_data.items():
        if category_name.startswith('_'):
            continue
        if isinstance(category_spells, dict):
            for spell_id, spell_name in category_spells.items():
                try:
                    names[int(spell_id)] = str(spell_name)
                except (ValueError, TypeError):
                    print(f"⚠️ Invalid name mapping: {spell_id} -> {spell_name}")
    
    print(f"✅ Loaded {len(aliases)} spell aliases")
    print(f"✅ Loaded {len(names)} spell names")
    
    # Check for issues
    issues = 0
    
    # Check for circular aliases
    print("\n🔄 Checking for circular aliases...")
    for variant_id, canonical_id in aliases.items():
        visited = set()
        current = canonical_id
        path = [variant_id]
        
        while current in aliases and current not in visited:
            visited.add(current)
            path.append(current)
            current = aliases[current]
            
            if current in path[:-1]:
                print(f"⚠️ Circular alias: {' -> '.join(map(str, path + [current]))}")
                issues += 1
                break
    
    # Check for missing canonical names
    print("\n📝 Checking for missing canonical spell names...")
    missing_names = []
    for canonical_id in set(aliases.values()):
        if canonical_id not in names:
            missing_names.append(canonical_id)
    
    if missing_names:
        print(f"⚠️ {len(missing_names)} canonical IDs missing names:")
        for spell_id in sorted(missing_names)[:10]:  # Show first 10
            print(f"   - {spell_id}")
        if len(missing_names) > 10:
            print(f"   ... and {len(missing_names) - 10} more")
        issues += len(missing_names)
    
    # Summary
    if issues == 0:
        print(f"\n✅ Configuration validation passed! No issues found.")
        return True
    else:
        print(f"\n⚠️ Found {issues} issues in configuration.")
        return False

def add_spell_name(spell_id: int, spell_name: str, category: str) -> bool:
    """Add a new spell name to the configuration."""
    names_file = "spell_data/spell_names.json"
    names_data = load_json_file(names_file)
    
    if names_data is None:
        return False
    
    # Create category if it doesn't exist
    if category not in names_data:
        names_data[category] = {}
    
    # Add the spell
    names_data[category][str(spell_id)] = spell_name
    
    if save_json_file(names_file, names_data):
        print(f"✅ Added spell: {spell_id} -> '{spell_name}' in category '{category}'")
        return True
    return False

def add_spell_alias(variant_ids: list, canonical_id: int, group_name: str) -> bool:
    """Add new spell aliases to the configuration."""
    aliases_file = "spell_data/spell_aliases.json"
    aliases_data = load_json_file(aliases_file)
    
    if aliases_data is None:
        return False
    
    # Create group if it doesn't exist
    if group_name not in aliases_data:
        aliases_data[group_name] = {}
    
    # Add the aliases
    for variant_id in variant_ids:
        aliases_data[group_name][str(variant_id)] = canonical_id
    
    if save_json_file(aliases_file, aliases_data):
        print(f"✅ Added aliases: {variant_ids} -> {canonical_id} in group '{group_name}'")
        return True
    return False

def list_categories() -> None:
    """List all available categories in spell_names.json."""
    names_file = "spell_data/spell_names.json"
    names_data = load_json_file(names_file)
    
    if names_data is None:
        return
    
    print("\n📋 Available spell name categories:")
    for category in sorted(names_data.keys()):
        if not category.startswith('_'):
            spell_count = len(names_data[category]) if isinstance(names_data[category], dict) else 0
            print(f"   - {category} ({spell_count} spells)")

def list_groups() -> None:
    """List all available groups in spell_aliases.json."""
    aliases_file = "spell_data/spell_aliases.json"
    aliases_data = load_json_file(aliases_file)
    
    if aliases_data is None:
        return
    
    print("\n📋 Available spell alias groups:")
    for group in sorted(aliases_data.keys()):
        if not group.startswith('_'):
            alias_count = len(aliases_data[group]) if isinstance(aliases_data[group], dict) else 0
            print(f"   - {group} ({alias_count} aliases)")

def search_spells(query: str) -> None:
    """Search for spells by name or ID."""
    names_file = "spell_data/spell_names.json"
    names_data = load_json_file(names_file)
    
    if names_data is None:
        return
    
    query_lower = query.lower()
    matches = []
    
    # Search through all spell names
    for category, spells in names_data.items():
        if category.startswith('_'):
            continue
        if isinstance(spells, dict):
            for spell_id, spell_name in spells.items():
                if (query_lower in spell_name.lower() or 
                    query_lower in spell_id or
                    query == spell_id):
                    matches.append((category, spell_id, spell_name))
    
    if matches:
        print(f"\n🔍 Found {len(matches)} matches for '{query}':")
        for category, spell_id, spell_name in matches:
            print(f"   - ID {spell_id}: '{spell_name}' (in {category})")
    else:
        print(f"\n❌ No matches found for '{query}'")

def main():
    parser = argparse.ArgumentParser(
        description="Manage spell configurations for Warcraft Logs analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s validate                                    # Validate configurations
  %(prog)s add-name 12345 "New Spell" warrior_abilities  # Add spell name
  %(prog)s add-alias 12001,12002 12000 new_spell_variants # Add aliases
  %(prog)s search "Flash Heal"                         # Search for spells
  %(prog)s list-categories                             # List name categories
  %(prog)s list-groups                                 # List alias groups
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Validate command
    subparsers.add_parser('validate', help='Validate spell configurations')
    
    # Add spell name command
    add_name_parser = subparsers.add_parser('add-name', help='Add a new spell name')
    add_name_parser.add_argument('spell_id', type=int, help='Spell ID')
    add_name_parser.add_argument('spell_name', help='Spell name')
    add_name_parser.add_argument('category', help='Category to add to')
    
    # Add alias command
    add_alias_parser = subparsers.add_parser('add-alias', help='Add spell aliases')
    add_alias_parser.add_argument('variant_ids', help='Comma-separated variant IDs')
    add_alias_parser.add_argument('canonical_id', type=int, help='Canonical ID')
    add_alias_parser.add_argument('group_name', help='Alias group name')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search for spells')
    search_parser.add_argument('query', help='Search query (name or ID)')
    
    # List commands
    subparsers.add_parser('list-categories', help='List spell name categories')
    subparsers.add_parser('list-groups', help='List spell alias groups')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == 'validate':
        success = validate_configurations()
        sys.exit(0 if success else 1)
        
    elif args.command == 'add-name':
        success = add_spell_name(args.spell_id, args.spell_name, args.category)
        sys.exit(0 if success else 1)
        
    elif args.command == 'add-alias':
        try:
            variant_ids = [int(x.strip()) for x in args.variant_ids.split(',')]
            success = add_spell_alias(variant_ids, args.canonical_id, args.group_name)
            sys.exit(0 if success else 1)
        except ValueError:
            print("❌ Invalid variant IDs. Use comma-separated integers.")
            sys.exit(1)
            
    elif args.command == 'search':
        search_spells(args.query)
        
    elif args.command == 'list-categories':
        list_categories()
        
    elif args.command == 'list-groups':
        list_groups()

if __name__ == '__main__':
    main() 