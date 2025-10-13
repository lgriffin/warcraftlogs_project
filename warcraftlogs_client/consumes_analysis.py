"""
Consumables Analysis Module for Warcraft Logs

This module analyzes consumable usage across multiple raid reports,
providing role-based filtering and detailed reporting.
"""

import json
import csv
import os
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional
from .client import WarcraftLogsClient, get_cast_data
from .common.data import get_master_data, get_report_metadata
from . import dynamic_role_parser


class ConsumesAnalyzer:
    """Analyzes consumable usage across multiple raid reports."""
    
    def __init__(self, config_path: str = "consumes_config.json"):
        """Initialize the analyzer with consumable configuration."""
        self.config = self._load_config(config_path)
        self.consumes_data = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        self.raid_metadata = {}
        self.healers_by_raid = defaultdict(set)  # Store healers per raid
        
    def _load_config(self, config_path: str) -> Dict:
        """Load consumable configuration from JSON file."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Consumable config file not found: {config_path}")
            
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def analyze_raid(self, client: WarcraftLogsClient, report_id: str) -> None:
        """Analyze consumable usage for a single raid report."""
        print(f"[ANALYZING] Analyzing consumables for raid: {report_id}")
        
        # Get raid metadata
        metadata = get_report_metadata(client, report_id)
        self.raid_metadata[report_id] = {
            'title': metadata['title'],
            'date': metadata['start']
        }
        
        # Get all actors in the raid
        master_actors = get_master_data(client, report_id)
        
        # Identify roles using existing logic
        roles = self._identify_roles(client, report_id, master_actors)
        
        # Store healers for this raid
        self.healers_by_raid[report_id] = set(roles['healers'])
        
        # Analyze consumables for each player
        for player in master_actors:
            player_name = player['name']
            player_class = player['subType']
            source_id = player['id']
            
            # Determine player role
            player_role = self._determine_player_role(player_name, player_class, roles)
            
            # Get buff data and cast data for this player
            try:
                from .client import get_auras_data_by_ability, get_cast_events_data
                
                # Query each consumable ability individually for accurate data
                all_events = []
                consumable_ids = list(self.config["personal_buffs"].keys()) + list(self.config["defensive_potions"].keys())
                
                for ability_id_str in consumable_ids:
                    ability_id = int(ability_id_str)
                    try:
                        # Get buff events for this specific ability
                        ability_data = get_auras_data_by_ability(client, report_id, source_id, ability_id)
                        ability_events = ability_data["data"]["reportData"]["report"]["events"]["data"]
                        all_events.extend(ability_events)
                    except Exception:
                        # If individual query fails, skip this ability
                        pass
                
                # Also get cast events for personal buffs (mana potions, dark runes)
                try:
                    cast_data = get_cast_events_data(client, report_id, source_id)
                    cast_events = cast_data["data"]["reportData"]["report"]["events"]["data"]
                    # Filter to only personal buff casts
                    personal_buff_ids = [int(id) for id in self.config["personal_buffs"].keys()]
                    personal_casts = [e for e in cast_events if e.get('abilityGameID') in personal_buff_ids]
                    all_events.extend(personal_casts)
                except Exception:
                    pass
                
                # Count consumables
                self._count_consumables(player_name, player_role, report_id, all_events)
                
            except Exception as e:
                print(f"[WARNING] Error analyzing {player_name}: {e}")
    
    def _identify_roles(self, client: WarcraftLogsClient, report_id: str, master_actors: List[Dict]) -> Dict[str, List[str]]:
        """Identify roles using existing dynamic role parser logic."""
        roles = {
            'tanks': [],
            'healers': [],
            'melee': [],
            'ranged': []
        }
        
        # Identify tanks (simplified version of existing logic)
        for actor in master_actors:
            if actor["subType"] in {"Warrior", "Druid"}:
                # This is a simplified check - in production you'd want the full tank identification logic
                roles['tanks'].append(actor['name'])
        
        # Identify healers
        healing_totals = {}
        for actor in master_actors:
            if actor["subType"] in {"Priest", "Paladin", "Druid", "Shaman"}:
                try:
                    from .client import get_healing_data
                    healing_data = get_healing_data(client, report_id, actor["id"])
                    events = healing_data["data"]["reportData"]["report"]["events"]["data"]
                    total = sum(e.get("amount", 0) for e in events if e.get("type") == "heal")
                    healing_totals[actor["name"]] = total
                except Exception:
                    healing_totals[actor["name"]] = 0
        
        healers = dynamic_role_parser.identify_healers(master_actors, healing_totals, threshold=50000)
        roles['healers'] = [h['name'] for h in healers]
        
        # Identify melee and ranged
        excluded_names = set(roles['tanks']) | set(roles['healers'])
        melee_classes = {"Rogue", "Warrior"}
        ranged_classes = {"Mage", "Warlock", "Hunter"}
        
        for actor in master_actors:
            if actor['name'] not in excluded_names:
                if actor['subType'] in melee_classes:
                    roles['melee'].append(actor['name'])
                elif actor['subType'] in ranged_classes:
                    roles['ranged'].append(actor['name'])
        
        return roles
    
    def _determine_player_role(self, player_name: str, player_class: str, roles: Dict[str, List[str]]) -> str:
        """Determine a player's role based on identified roles."""
        for role, players in roles.items():
            if player_name in players:
                return role
        return "unknown"
    
    
    def _count_consumables(self, player_name: str, player_role: str, report_id: str, events: List[Dict]) -> None:
        """Count consumable usage for a player."""
        # Group events by ability for smarter counting
        ability_events = {}
        
        # First pass: collect and deduplicate events
        seen_events = set()
        for event in events:
            if event.get("type") in ["applybuff", "cast", "begincast", "refreshbuff", "removebuff"]:
                ability_id = event.get("abilityGameID")
                if ability_id is None:
                    continue
                
                timestamp = event.get("timestamp", 0)
                event_type = event.get("type")
                event_key = (ability_id, timestamp, event_type)
                
                # Skip duplicates
                if event_key in seen_events:
                    continue
                seen_events.add(event_key)
                
                # Group by ability
                if ability_id not in ability_events:
                    ability_events[ability_id] = []
                ability_events[ability_id].append({
                    'type': event_type,
                    'timestamp': timestamp
                })
        
        # Second pass: count consumables intelligently
        # Personal buffs (mana potions, dark runes) - count cast events
        for spell_id, spell_name in self.config["personal_buffs"].items():
            spell_id_int = int(spell_id)
            if spell_id_int in ability_events:
                cast_count = sum(1 for e in ability_events[spell_id_int] if e['type'] in ["cast", "begincast"])
                self.consumes_data[player_name][report_id][spell_name] += cast_count
        
        # Defensive potions - count only removebuff and refreshbuff events
        # This matches the Warcraft Logs website behavior most closely
        for spell_id, spell_name in self.config["defensive_potions"].items():
            spell_id_int = int(spell_id)
            if spell_id_int in ability_events:
                ability_event_list = ability_events[spell_id_int]
                
                # Count removebuff events - each removal = 1 potion consumed
                remove_count = sum(1 for e in ability_event_list if e['type'] == 'removebuff')
                
                # Count refreshbuff events - each refresh = 1 new potion used
                refresh_count = sum(1 for e in ability_event_list if e['type'] == 'refreshbuff')
                
                # Total usage = removes + refreshes
                # This is the most reliable method as it counts actual consumption
                count = remove_count + refresh_count
                self.consumes_data[player_name][report_id][spell_name] += count
    
    def generate_report(self, output_csv: Optional[str] = None) -> None:
        """Generate the consumables analysis report."""
        print("\n" + "="*80)
        print("CONSUMABLES ANALYSIS REPORT")
        print("="*80)
        print("\nNOTE: Consumable counts are based on removebuff and refreshbuff events.")
        print("Some discrepancies may exist compared to the Warcraft Logs website due to:")
        print("  - Potions applied out of combat (not always logged)")
        print("  - Buffs that remain active at raid end (no removebuff event)")
        print("  - Differences in how the website processes event data")
        print("="*80)
        
        # Generate defensive potions report (all roles, per raid)
        self._print_defensive_potions_report()
        
        # Generate personal buffs report (healers only, per raid)
        self._print_personal_buffs_report()
        
        # Generate CSV if requested
        if output_csv:
            self._export_to_csv(output_csv)
    
    def _is_healer(self, player_name: str, report_id: str) -> bool:
        """Check if a player is a healer in a specific raid."""
        return player_name in self.healers_by_raid.get(report_id, set())
    
    def _determine_role_from_usage(self, player_name: str) -> str:
        """Determine role based on consumable usage patterns."""
        # This is a simplified approach - in practice you'd want to use the role identification from the analysis
        # For now, we'll use a basic heuristic
        player_data = self.consumes_data[player_name]
        
        # Check if they used mana potions (likely healer)
        for report_data in player_data.values():
            if "Major Mana Potion" in report_data or "Dark Rune" in report_data:
                return "healer"
        
        # Default to unknown if we can't determine
        return "unknown"
    
    def _print_defensive_potions_report(self) -> None:
        """Print defensive potions usage report per raid."""
        print("\nPROTECTION POTIONS USED")
        print("-" * 50)
        
        # Get all defensive potion names and trim "Protection" from the end
        potion_names = [name.replace(" Protection", "") for name in self.config["defensive_potions"].values()]
        
        # Group data by raid
        for report_id in sorted(self.raid_metadata.keys()):
            raid_title = self.raid_metadata[report_id]['title']
            print(f"\nRaid: {raid_title} ({report_id})")
            print("-" * 60)
            
            # Collect defensive potion usage for this raid
            defensive_data = defaultdict(int)
            players_in_raid = set()
            
            # Initialize all players with 0 for all potion types
            for player_name, report_data in self.consumes_data.items():
                if report_id in report_data:
                    players_in_raid.add(player_name)
                    # Initialize all potion types to 0 for this player
                    for potion_name in potion_names:
                        defensive_data[(player_name, potion_name)] = 0
            
            # Now populate with actual data
            for player_name, report_data in self.consumes_data.items():
                if report_id in report_data:
                    for consumable_name, count in report_data[report_id].items():
                        if consumable_name in self.config["defensive_potions"].values():
                            # Trim "Protection" from the name for display
                            display_name = consumable_name.replace(" Protection", "")
                            defensive_data[(player_name, display_name)] = count
            
            if defensive_data:
                # Print header
                header = f"{'Player':<20} " + "".join(f"{potion[:15]:>16}" for potion in potion_names)
                print(header)
                print("-" * len(header))
                
                # Print data for each player in this raid
                for player_name in sorted(players_in_raid):
                    row = f"{player_name:<20}"
                    for potion in potion_names:
                        count = defensive_data.get((player_name, potion), 0)
                        row += f"{count:>16}"
                    print(row)
            else:
                print("No defensive potion usage found in this raid.")
    
    def _print_personal_buffs_report(self) -> None:
        """Print personal buffs usage report for healers only, per raid."""
        print("\nPERSONAL BUFFS USAGE (Healers Only)")
        print("-" * 50)
        
        # Get all personal buff names
        buff_names = list(self.config["personal_buffs"].values())
        
        # Group data by raid
        for report_id in sorted(self.raid_metadata.keys()):
            raid_title = self.raid_metadata[report_id]['title']
            print(f"\nRaid: {raid_title} ({report_id})")
            print("-" * 60)
            
            # Collect personal buff usage for healers in this raid
            personal_data = defaultdict(int)
            healers_in_raid = set()
            
            for player_name, report_data in self.consumes_data.items():
                if report_id in report_data:
                    # Check if this player is a healer by looking at their class and usage patterns
                    if self._is_healer(player_name, report_id):
                        healers_in_raid.add(player_name)
                        for consumable_name, count in report_data[report_id].items():
                            if consumable_name in self.config["personal_buffs"].values():
                                personal_data[(player_name, consumable_name)] = count
            
            if personal_data:
                # Print header
                header = f"{'Healer':<20} " + "".join(f"{buff[:15]:>16}" for buff in buff_names)
                print(header)
                print("-" * len(header))
                
                # Print data for each healer in this raid
                for healer in sorted(healers_in_raid):
                    row = f"{healer:<20}"
                    for buff in buff_names:
                        count = personal_data.get((healer, buff), 0)
                        row += f"{count:>16}"
                    print(row)
            else:
                print("No healer personal buff usage found in this raid.")
    
    def _export_to_csv(self, output_file: str) -> None:
        """Export consumables data to CSV file."""
        print(f"\n[EXPORT] Exporting data to CSV: {output_file}")
        
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow(['Player', 'Raid ID', 'Raid Title', 'Consumable', 'Count'])
            
            # Write data
            for player_name, report_data in self.consumes_data.items():
                for report_id, consumables in report_data.items():
                    raid_title = self.raid_metadata.get(report_id, {}).get('title', 'Unknown')
                    for consumable_name, count in consumables.items():
                        writer.writerow([player_name, report_id, raid_title, consumable_name, count])
        
        print(f"[SUCCESS] CSV export completed: {output_file}")


def run_consumes_analysis(raid_ids: List[str], output_csv: Optional[str] = None) -> None:
    """Run consumables analysis for multiple raid IDs."""
    from .auth import TokenManager
    from .config import load_config
    
    # Load configuration
    config = load_config()
    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)
    
    # Initialize analyzer
    analyzer = ConsumesAnalyzer()
    
    # Analyze each raid
    for raid_id in raid_ids:
        try:
            analyzer.analyze_raid(client, raid_id)
        except Exception as e:
            print(f"[ERROR] Error analyzing raid {raid_id}: {e}")
    
    # Generate report
    analyzer.generate_report(output_csv)
