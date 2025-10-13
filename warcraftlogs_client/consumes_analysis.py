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
    
    def __init__(self, config_path: str = "consumes_config.json", include_healers: bool = False):
        """Initialize the analyzer with consumable configuration."""
        self.config = self._load_config(config_path)
        self.consumes_data = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        self.raid_metadata = {}
        self.healers_by_raid = defaultdict(set)  # Store healers per raid
        self.include_healers = include_healers  # Whether to analyze healer personal buffs
        self.timestamp_data = defaultdict(lambda: defaultdict(list))  # Store (timestamp, player, potion) for spike analysis
        self.boss_kills = defaultdict(list)  # Store boss kill timestamps per raid
        
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
        
        # Fetch boss kill timestamps
        self._fetch_boss_kills(client, report_id)
        
        # Analyze consumables for each player using efficient table queries
        from .client import get_buffs_table, get_cast_events_data
        
        for player in master_actors:
            player_name = player['name']
            player_class = player['subType']
            source_id = player['id']
            
            # Determine player role
            player_role = self._determine_player_role(player_name, player_class, roles)
            
            # Get buff data using efficient table query (ONE API call instead of 5-7!)
            try:
                # Get table data for this player - includes ALL buffs
                table_result = get_buffs_table(client, report_id, source_id)
                table_data = table_result["data"]["reportData"]["report"]["table"]
                
                # Parse the JSON string if needed
                if isinstance(table_data, str):
                    table_data = json.loads(table_data)
                
                # Also get cast events for personal buffs (mana potions, dark runes) - only if healers flag is set
                cast_events = []
                if self.include_healers:
                    try:
                        cast_data = get_cast_events_data(client, report_id, source_id)
                        cast_events = cast_data["data"]["reportData"]["report"]["events"]["data"]
                        # Filter to only personal buff casts
                        personal_buff_ids = [int(id) for id in self.config["personal_buffs"].keys()]
                        cast_events = [e for e in cast_events if e.get('abilityGameID') in personal_buff_ids]
                    except Exception:
                        pass
                
                # Count consumables from table data
                self._count_consumables_from_table(player_name, player_role, report_id, table_data, cast_events)
                
            except Exception as e:
                print(f"[WARNING] Error analyzing {player_name}: {e}")
    
    def _fetch_boss_kills(self, client: WarcraftLogsClient, report_id: str) -> None:
        """Fetch boss kill timestamps from the raid."""
        try:
            query = f"""
            {{
              reportData {{
                report(code: "{report_id}") {{
                  fights {{
                    id
                    name
                    startTime
                    endTime
                    kill
                    encounterID
                  }}
                }}
              }}
            }}
            """
            result = client.run_query(query)
            fights = result["data"]["reportData"]["report"]["fights"]
            
            # Store only boss kills (kills with encounterID)
            for fight in fights:
                if fight.get("kill") and fight.get("encounterID"):
                    self.boss_kills[report_id].append({
                        'name': fight['name'],
                        'timestamp': fight['endTime'],  # Kill time
                        'start_time': fight['startTime'],
                        'encounter_id': fight['encounterID']
                    })
            
            # Sort by timestamp
            self.boss_kills[report_id].sort(key=lambda x: x['timestamp'])
            
        except Exception as e:
            print(f"[WARNING] Could not fetch boss kills: {e}")
            self.boss_kills[report_id] = []
    
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
    
    def _count_consumables_from_table(self, player_name: str, player_role: str, report_id: str, 
                                       table_data: Dict, cast_events: List[Dict]) -> None:
        """
        Count consumable usage from table data (buffBands).
        This is MUCH more efficient than individual event queries!
        
        Table data structure:
        {
          "data": {
            "auras": [
              {
                "guid": <ability_id>,
                "name": "<ability name>",
                "totalUses": <count>,
                "bands": [{"startTime": ..., "endTime": ...}, ...]
              },
              ...
            ]
          }
        }
        """
        # Build lookup for our consumables
        all_consumables = {}
        for spell_id, spell_name in self.config["defensive_potions"].items():
            all_consumables[int(spell_id)] = spell_name
        for spell_id, spell_name in self.config.get("lesser_protection_potions", {}).items():
            all_consumables[int(spell_id)] = spell_name
        
        # Extract auras from table data
        auras = table_data.get("data", {}).get("auras", [])
        
        # Count protection potions from table data
        for aura in auras:
            ability_id = aura.get("guid")
            if ability_id in all_consumables:
                potion_name = all_consumables[ability_id]
                # totalUses is the count of times the buff was applied
                count = aura.get("totalUses", 0)
                self.consumes_data[player_name][report_id][potion_name] += count
                
                # Store timestamps for spike analysis (use band start times)
                bands = aura.get("bands", [])
                for band in bands:
                    self.timestamp_data[report_id][potion_name].append({
                        'timestamp': band.get('startTime', 0),
                        'player': player_name,
                        'type': 'applybuff'  # Treat as applybuff for spike detection
                    })
        
        # Count personal buffs (mana potions, dark runes) from cast events
        if cast_events:
            for event in cast_events:
                ability_id = event.get('abilityGameID')
                if ability_id:
                    for spell_id, spell_name in self.config["personal_buffs"].items():
                        if int(spell_id) == ability_id and event.get('type') in ['cast', 'begincast']:
                            self.consumes_data[player_name][report_id][spell_name] += 1
                            # Store timestamp for spike analysis
                            self.timestamp_data[report_id][spell_name].append({
                                'timestamp': event.get('timestamp', 0),
                                'player': player_name,
                                'type': event.get('type')
                            })
    
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
                
                # Track timestamps for spike analysis (use applybuff for when potion was used)
                for event in ability_event_list:
                    if event['type'] in ['applybuff', 'refreshbuff']:
                        self.timestamp_data[report_id][spell_name].append({
                            'timestamp': event['timestamp'],
                            'player': player_name,
                            'type': event['type']
                        })
                
                # Count removebuff events - each removal = 1 potion consumed
                remove_count = sum(1 for e in ability_event_list if e['type'] == 'removebuff')
                
                # Count refreshbuff events - each refresh = 1 new potion used
                refresh_count = sum(1 for e in ability_event_list if e['type'] == 'refreshbuff')
                
                # Total usage = removes + refreshes
                # This is the most reliable method as it counts actual consumption
                count = remove_count + refresh_count
                self.consumes_data[player_name][report_id][spell_name] += count
        
        # Lesser protection potions - same logic as defensive potions
        for spell_id, spell_name in self.config.get("lesser_protection_potions", {}).items():
            spell_id_int = int(spell_id)
            if spell_id_int in ability_events:
                ability_event_list = ability_events[spell_id_int]
                
                # Track timestamps for spike analysis
                for event in ability_event_list:
                    if event['type'] in ['applybuff', 'refreshbuff']:
                        self.timestamp_data[report_id][spell_name].append({
                            'timestamp': event['timestamp'],
                            'player': player_name,
                            'type': event['type']
                        })
                
                remove_count = sum(1 for e in ability_event_list if e['type'] == 'removebuff')
                refresh_count = sum(1 for e in ability_event_list if e['type'] == 'refreshbuff')
                
                count = remove_count + refresh_count
                self.consumes_data[player_name][report_id][spell_name] += count
    
    def generate_report(self, output_csv: Optional[str] = None, include_healers: bool = False) -> None:
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
        
        # Generate lesser protection potions report (all roles, per raid)
        self._print_lesser_protection_potions_report()
        
        # Generate personal buffs report (healers only, per raid) - only if requested
        if include_healers:
            self._print_personal_buffs_report()
        
        # Generate group-wide buff behavior analysis
        self._print_group_buff_behavior()
        
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
    
    def _print_lesser_protection_potions_report(self) -> None:
        """Print lesser protection potions usage report per raid."""
        # Check if config has this category
        if "lesser_protection_potions" not in self.config or not self.config["lesser_protection_potions"]:
            return
            
        print("\nLESSER PROTECTION POTIONS USED")
        print("-" * 50)
        
        # Get all lesser protection potion names and trim "Protection" from the end
        potion_names = [name.replace(" Protection", "") for name in self.config["lesser_protection_potions"].values()]
        
        # Group data by raid
        for report_id in sorted(self.raid_metadata.keys()):
            raid_title = self.raid_metadata[report_id]['title']
            print(f"\nRaid: {raid_title} ({report_id})")
            print("-" * 60)
            
            # Collect lesser protection potion usage for this raid
            lesser_data = defaultdict(int)
            players_in_raid = set()
            
            # Initialize all players with 0 for all potion types
            for player_name, report_data in self.consumes_data.items():
                if report_id in report_data:
                    players_in_raid.add(player_name)
                    # Initialize all potion types to 0 for this player
                    for potion_name in potion_names:
                        lesser_data[(player_name, potion_name)] = 0
            
            # Now populate with actual data
            for player_name, report_data in self.consumes_data.items():
                if report_id in report_data:
                    for consumable_name, count in report_data[report_id].items():
                        if consumable_name in self.config["lesser_protection_potions"].values():
                            # Trim "Protection" from the name for display
                            display_name = consumable_name.replace(" Protection", "")
                            lesser_data[(player_name, display_name)] = count
            
            if lesser_data and any(count > 0 for count in lesser_data.values()):
                # Print header
                header = f"{'Player':<20} " + "".join(f"{potion[:20]:>20}" for potion in potion_names)
                print(header)
                print("-" * len(header))
                
                # Print data for each player in this raid
                for player_name in sorted(players_in_raid):
                    row = f"{player_name:<20}"
                    for potion in potion_names:
                        count = lesser_data.get((player_name, potion), 0)
                        row += f"{count:>20}"
                    print(row)
            else:
                print("No lesser protection potion usage found in this raid.")
    
    def _print_group_buff_behavior(self) -> None:
        """Analyze and print coordinated potion usage patterns."""
        print("\nGROUP-WIDE BUFF BEHAVIOR")
        print("-" * 80)
        print("Analyzing coordinated potion usage (60-second windows)...")
        
        # Analyze each raid
        for report_id in sorted(self.raid_metadata.keys()):
            raid_title = self.raid_metadata[report_id]['title']
            print(f"\nRaid: {raid_title} ({report_id})")
            print("-" * 80)
            
            # Detect spikes for each potion type
            spikes_found = False
            for potion_name, events in self.timestamp_data[report_id].items():
                if not events:
                    continue
                
                # Sort by timestamp
                sorted_events = sorted(events, key=lambda x: x['timestamp'])
                
                # Find windows with 10+ players using the same potion within 60 seconds
                spike_windows = self._detect_spikes(sorted_events, window_size=60000, min_players=10)
                
                if spike_windows:
                    spikes_found = True
                    for window in spike_windows:
                        # Format timestamp (convert milliseconds to MM:SS)
                        time_seconds = window['start_time'] // 1000
                        minutes = time_seconds // 60
                        seconds = time_seconds % 60
                        
                        print(f"\n  [{minutes:02d}:{seconds:02d}] {potion_name}")
                        print(f"    {window['player_count']} players used this potion")
                        
                        # Find the next boss kill after this timestamp
                        next_boss = self._find_next_boss_kill(report_id, window['start_time'])
                        if next_boss:
                            print(f"    Next boss killed: {next_boss['name']}")
                        
                        print(f"    Used by: {', '.join(sorted(window['players']))}")
                        
                        # Show who didn't use it (if there are any non-users)
                        all_players = set(self.consumes_data.keys())
                        if window['non_users']:
                            print(f"    Did NOT use: {', '.join(sorted(window['non_users']))}")
            
            if not spikes_found:
                print("  No coordinated potion usage detected (minimum 10 players within 60 seconds)")
    
    def _find_next_boss_kill(self, report_id: str, timestamp: int) -> Optional[Dict]:
        """Find the next boss kill after a given timestamp."""
        for boss in self.boss_kills[report_id]:
            if boss['timestamp'] > timestamp:
                return boss
        return None
    
    def _detect_spikes(self, events: List[Dict], window_size: int = 60000, min_players: int = 10) -> List[Dict]:
        """
        Detect spikes in potion usage.
        
        Args:
            events: List of events with 'timestamp' and 'player' keys
            window_size: Time window in milliseconds (default 60000ms = 60 seconds)
            min_players: Minimum number of players to consider it a spike
            
        Returns:
            List of spike windows with player information
        """
        if len(events) < min_players:
            return []
        
        spikes = []
        processed_timestamps = set()
        
        for i, event in enumerate(events):
            timestamp = event['timestamp']
            
            # Skip if we've already processed this timestamp area
            if timestamp in processed_timestamps:
                continue
            
            # Find all events within the window
            window_end = timestamp + window_size
            players_in_window = set()
            timestamps_in_window = []
            
            for j in range(i, len(events)):
                if events[j]['timestamp'] <= window_end:
                    players_in_window.add(events[j]['player'])
                    timestamps_in_window.append(events[j]['timestamp'])
                else:
                    break
            
            # If enough players used the potion in this window, record it
            if len(players_in_window) >= min_players:
                # Get all players in this specific raid for comparison
                all_players_in_raid = set(self.consumes_data.keys())
                
                non_users = all_players_in_raid - players_in_window
                
                spikes.append({
                    'start_time': timestamp,
                    'end_time': window_end,
                    'player_count': len(players_in_window),
                    'players': list(players_in_window),
                    'non_users': list(non_users) if len(non_users) < len(players_in_window) else []
                })
                
                # Mark these timestamps as processed
                for ts in timestamps_in_window:
                    processed_timestamps.add(ts)
        
        return spikes
    
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


def run_consumes_analysis(raid_ids: List[str], output_csv: Optional[str] = None, include_healers: bool = False) -> None:
    """Run consumables analysis for multiple raid IDs."""
    from .auth import TokenManager
    from .config import load_config
    
    # Load configuration
    config = load_config()
    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)
    
    # Initialize analyzer with healer flag
    analyzer = ConsumesAnalyzer(include_healers=include_healers)
    
    # Analyze each raid
    for raid_id in raid_ids:
        try:
            analyzer.analyze_raid(client, raid_id)
        except Exception as e:
            print(f"[ERROR] Error analyzing raid {raid_id}: {e}")
    
    # Generate report
    analyzer.generate_report(output_csv, include_healers=include_healers)
