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

import requests

from .client import WarcraftLogsClient, get_cast_data
from .common.data import get_master_data, get_report_metadata
from . import dynamic_role_parser


class ConsumesAnalyzer:
    """Analyzes consumable usage across multiple raid reports."""
    
    def __init__(self, config_path: str | None = None, include_healers: bool = False):
        """Initialize the analyzer with consumable configuration."""
        from . import paths
        self.config = self._load_config(config_path or str(paths.get_consumes_config_path()))
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
                
                cast_events = []
                try:
                    cast_data = get_cast_events_data(client, report_id, source_id)
                    cast_events = cast_data["data"]["reportData"]["report"]["events"]["data"]
                    cast_ids = [int(sid) for sid in self.config.get("cast_consumables", {}).keys()]
                    cast_events = [e for e in cast_events if e.get('abilityGameID') in cast_ids]
                except (requests.RequestException, KeyError, TypeError, ValueError):
                    pass
                
                # Count consumables from table data
                self._count_consumables_from_table(player_name, player_role, report_id, table_data, cast_events)
                
            except (requests.RequestException, KeyError, TypeError, ValueError) as e:
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
            
        except (requests.RequestException, KeyError, TypeError) as e:
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
                except (requests.RequestException, KeyError, TypeError):
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
        all_consumables = {}
        for spell_id, spell_name in self.config.get("buff_consumables", {}).items():
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
                    for spell_id, spell_name in self.config.get("cast_consumables", {}).items():
                        if int(spell_id) == ability_id and event.get('type') in ['cast', 'begincast']:
                            self.consumes_data[player_name][report_id][spell_name] += 1
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
        for spell_id, spell_name in self.config.get("cast_consumables", {}).items():
            spell_id_int = int(spell_id)
            if spell_id_int in ability_events:
                cast_count = sum(1 for e in ability_events[spell_id_int] if e['type'] in ["cast", "begincast"])
                self.consumes_data[player_name][report_id][spell_name] += cast_count

        for spell_id, spell_name in self.config.get("buff_consumables", {}).items():
            spell_id_int = int(spell_id)
            if spell_id_int in ability_events:
                ability_event_list = ability_events[spell_id_int]

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

        self._print_consumables_report()
        self._print_group_buff_behavior()

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
            if "Super Mana Potion" in report_data or "Dark Rune" in report_data:
                return "healer"
        
        # Default to unknown if we can't determine
        return "unknown"
    
    def _print_consumables_report(self) -> None:
        """Print consumable usage per raid, showing only consumables that appeared."""
        for report_id in sorted(self.raid_metadata.keys()):
            raid_title = self.raid_metadata[report_id]['title']
            print(f"\nRaid: {raid_title} ({report_id})")
            print("-" * 60)

            present_consumables: set[str] = set()
            players_in_raid: set[str] = set()
            usage_data: dict[tuple[str, str], int] = defaultdict(int)

            for player_name, report_data in self.consumes_data.items():
                if report_id in report_data:
                    players_in_raid.add(player_name)
                    for consumable_name, count in report_data[report_id].items():
                        if count > 0:
                            present_consumables.add(consumable_name)
                            usage_data[(player_name, consumable_name)] = count

            if not present_consumables:
                print("No consumable usage found in this raid.")
                continue

            col_names = sorted(present_consumables)
            col_width = 20
            header = f"{'Player':<20} " + "".join(f"{name[:col_width-2]:>{col_width}}" for name in col_names)
            print(header)
            print("-" * len(header))

            for player_name in sorted(players_in_raid):
                has_any = any(usage_data.get((player_name, c), 0) > 0 for c in col_names)
                if not has_any:
                    continue
                row = f"{player_name:<20}"
                for c in col_names:
                    count = usage_data.get((player_name, c), 0)
                    row += f"{count:>{col_width}}" if count > 0 else f"{'':>{col_width}}"
                print(row)
    
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

    def export_to_markdown(self, output_path: Optional[str] = None) -> str:
        """Export consumables data to a markdown file. Returns path written."""
        lines = ["# Consumables Analysis Report", ""]

        for report_id in sorted(self.raid_metadata.keys()):
            raid_title = self.raid_metadata[report_id]['title']
            lines.append(f"## {raid_title}")
            lines.append(f"[View on WarcraftLogs](https://www.warcraftlogs.com/reports/{report_id})")
            lines.append("")

            present_consumables: set = set()
            players_in_raid: set = set()
            usage_data: dict = defaultdict(int)

            for player_name, report_data in self.consumes_data.items():
                if report_id in report_data:
                    players_in_raid.add(player_name)
                    for consumable_name, count in report_data[report_id].items():
                        if count > 0:
                            present_consumables.add(consumable_name)
                            usage_data[(player_name, consumable_name)] = count

            if not present_consumables:
                lines.append("No consumable usage found in this raid.")
                lines.append("")
                continue

            col_names = sorted(present_consumables)
            headers = ["Player"] + col_names
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join("---" for _ in headers) + " |")

            for player_name in sorted(players_in_raid):
                has_any = any(usage_data.get((player_name, c), 0) > 0 for c in col_names)
                if not has_any:
                    continue
                cells = [player_name]
                for c in col_names:
                    count = usage_data.get((player_name, c), 0)
                    cells.append(str(count) if count > 0 else "")
                lines.append("| " + " | ".join(cells) + " |")

            lines.append("")

        if not output_path:
            titles = [m['title'] for m in self.raid_metadata.values()]
            safe_title = "".join(
                c if c.isalnum() or c in " _-" else "_"
                for c in (titles[0] if titles else "consumes")
            ).strip().replace(" ", "_")
            from . import paths
            output_path = os.path.join(str(paths.get_reports_dir()), f"{safe_title}_consumes.md")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return output_path


def run_consumes_analysis(raid_ids: List[str], output_csv: Optional[str] = None,
                          include_healers: bool = False, markdown_path: Optional[str] = None) -> None:
    """Run consumables analysis for multiple raid IDs."""
    from .auth import TokenManager
    from .config import load_config

    config = load_config()
    token_mgr = TokenManager(config["client_id"], config["client_secret"])
    client = WarcraftLogsClient(token_mgr)

    analyzer = ConsumesAnalyzer(include_healers=include_healers)

    for raid_id in raid_ids:
        try:
            analyzer.analyze_raid(client, raid_id)
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            print(f"[ERROR] Error analyzing raid {raid_id}: {e}")

    analyzer.generate_report(output_csv, include_healers=include_healers)

    if markdown_path:
        path = analyzer.export_to_markdown(
            None if markdown_path == "auto" else markdown_path
        )
        print(f"\nMarkdown report exported to: {path}")
