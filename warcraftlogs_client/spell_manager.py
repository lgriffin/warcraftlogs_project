"""
Efficient Spell Management System for Warcraft Logs Analysis Tool.

This module provides a configurable, maintainable way to handle spell ID mappings
and aliases without hardcoding. Non-developers can easily add missing spells
by editing JSON configuration files.
"""

import json
import os
from typing import Dict, Optional, Set, Tuple, Any
from collections import defaultdict
from functools import lru_cache

class SpellManager:
    """
    Manages spell ID to name mappings and spell aliases efficiently.
    
    Features:
    - External JSON configuration files
    - Efficient caching and lookup
    - Easy maintenance by non-developers
    - Backward compatibility with existing code
    """
    
    def __init__(self, spell_data_dir: str = "spell_data"):
        self.spell_data_dir = spell_data_dir
        self._aliases: Optional[Dict[int, int]] = None
        self._names: Optional[Dict[int, str]] = None
        self._reverse_aliases: Optional[Dict[int, Set[int]]] = None
        
    def _load_aliases(self) -> Dict[int, int]:
        """Load spell aliases from JSON configuration."""
        if self._aliases is not None:
            return self._aliases
            
        aliases_file = os.path.join(self.spell_data_dir, "spell_aliases.json")
        self._aliases = {}
        
        if not os.path.exists(aliases_file):
            print(f"⚠️ Spell aliases file not found: {aliases_file}")
            return self._aliases
            
        try:
            with open(aliases_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Flatten all alias groups into a single dictionary
            for group_name, aliases in data.items():
                if group_name.startswith('_'):  # Skip metadata fields
                    continue
                    
                if isinstance(aliases, dict):
                    for source_id, canonical_id in aliases.items():
                        try:
                            # Handle string keys (JSON limitation) and negative IDs
                            source_key = int(source_id)
                            canonical_value = int(canonical_id)
                            self._aliases[source_key] = canonical_value
                        except (ValueError, TypeError) as e:
                            print(f"⚠️ Invalid alias mapping {source_id}:{canonical_id} - {e}")
                            
        except (json.JSONDecodeError, IOError) as e:
            print(f"❌ Error loading spell aliases: {e}")
            
        return self._aliases
    
    def _load_names(self) -> Dict[int, str]:
        """Load spell names from JSON configuration."""
        if self._names is not None:
            return self._names
            
        names_file = os.path.join(self.spell_data_dir, "spell_names.json")
        self._names = {}
        
        if not os.path.exists(names_file):
            print(f"⚠️ Spell names file not found: {names_file}")
            return self._names
            
        try:
            with open(names_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Flatten all name groups into a single dictionary
            for category_name, spells in data.items():
                if category_name.startswith('_'):  # Skip metadata fields
                    continue
                    
                if isinstance(spells, dict):
                    for spell_id, spell_name in spells.items():
                        try:
                            # Handle string keys (JSON limitation)
                            spell_key = int(spell_id)
                            self._names[spell_key] = str(spell_name)
                        except (ValueError, TypeError) as e:
                            print(f"⚠️ Invalid name mapping {spell_id}:{spell_name} - {e}")
                            
        except (json.JSONDecodeError, IOError) as e:
            print(f"❌ Error loading spell names: {e}")
            
        return self._names
    
    def _build_reverse_aliases(self) -> Dict[int, Set[int]]:
        """Build reverse lookup for aliases (canonical -> variants)."""
        if self._reverse_aliases is not None:
            return self._reverse_aliases
            
        aliases = self._load_aliases()
        self._reverse_aliases = defaultdict(set)
        
        # Add the canonical ID itself
        for canonical_id in set(aliases.values()):
            self._reverse_aliases[canonical_id].add(canonical_id)
            
        # Add all variants that map to each canonical ID
        for variant_id, canonical_id in aliases.items():
            self._reverse_aliases[canonical_id].add(variant_id)
            
        return self._reverse_aliases
    
    @lru_cache(maxsize=1024)
    def get_canonical_id(self, spell_id: int) -> int:
        """
        Get the canonical spell ID for a given spell ID.
        
        Args:
            spell_id: The spell ID to look up
            
        Returns:
            The canonical spell ID (or original if no alias exists)
        """
        aliases = self._load_aliases()
        return aliases.get(spell_id, spell_id)
    
    @lru_cache(maxsize=1024)  
    def get_spell_name(self, spell_id: int) -> str:
        """
        Get the display name for a spell ID.
        
        Args:
            spell_id: The spell ID to look up
            
        Returns:
            The spell name or "(ID {spell_id})" if not found
        """
        # First check if we need to use canonical ID
        canonical_id = self.get_canonical_id(spell_id)
        
        names = self._load_names()
        return names.get(canonical_id, f"(ID {canonical_id})")
    
    def get_variant_ids(self, canonical_id: int) -> Set[int]:
        """
        Get all variant IDs that map to a canonical ID.
        
        Args:
            canonical_id: The canonical spell ID
            
        Returns:
            Set of all spell IDs that map to this canonical ID
        """
        reverse_aliases = self._build_reverse_aliases()
        return reverse_aliases.get(canonical_id, {canonical_id})
    
    def process_spell_events(self, events: list, exclude_ids: Optional[Set[int]] = None) -> Dict[int, int]:
        """
        Process spell events and aggregate by canonical spell ID.
        
        Args:
            events: List of spell events from API
            exclude_ids: Set of spell IDs to exclude (e.g., Judgement of Light)
            
        Returns:
            Dictionary mapping canonical spell IDs to total amounts
        """
        if exclude_ids is None:
            exclude_ids = {20343}  # Default: exclude Judgement of Light
            
        spell_totals = defaultdict(int)
        
        for event in events:
            ability_id = event.get("abilityGameID")
            amount = event.get("amount", 0)
            
            if ability_id is None or ability_id in exclude_ids:
                continue
                
            canonical_id = self.get_canonical_id(ability_id)
            spell_totals[canonical_id] += amount
            
        return dict(spell_totals)
    
    def process_cast_entries(self, entries: list) -> Tuple[Dict[int, str], Dict[int, int]]:
        """
        Process cast table entries and aggregate by canonical spell ID.
        
        Args:
            entries: Cast table entries from API
            
        Returns:
            Tuple of (id_to_name, id_to_casts) dictionaries
        """
        id_to_name = {}
        id_to_casts = defaultdict(int)
        
        # Process API entries - always count casts, collect names when available
        for entry in entries:
            spell_id = entry.get("guid")
            spell_name = entry.get("name")
            casts = entry.get("hitCount", entry.get("total", 0))
            
            if spell_id is None or spell_id == 20343:  # Exclude Judgement of Light
                continue
                
            canonical_id = self.get_canonical_id(spell_id)
            
            # Always count the casts
            if canonical_id:
                id_to_casts[canonical_id] += casts
                
                # Use API name if available
                if spell_name:
                    id_to_name[canonical_id] = spell_name
        
        # Add names from our configuration for any missing IDs
        names = self._load_names()
        for canonical_id in id_to_casts:
            if canonical_id not in id_to_name:
                id_to_name[canonical_id] = names.get(canonical_id, f"(ID {canonical_id})")
        
        return dict(id_to_name), dict(id_to_casts)
    
    def get_resources_used(self, cast_entries: list) -> Dict[str, int]:
        """
        Extract resource usage (potions, etc.) from cast entries.
        
        Args:
            cast_entries: Cast table entries from API
            
        Returns:
            Dictionary mapping resource names to usage counts
        """
        resource_ids = {
            17531: "Major Mana Potion",
            27869: "Dark Rune"
        }
        
        resources_used = {}
        for entry in cast_entries:
            spell_id = entry.get("guid")
            if spell_id in resource_ids:
                count = entry.get("hitCount", entry.get("total", 0))
                resources_used[resource_ids[spell_id]] = count
                
        return resources_used
    
    def get_fear_ward_usage(self, cast_entries: list) -> Optional[Dict[str, Any]]:
        """
        Extract Fear Ward usage from cast entries.
        
        Args:
            cast_entries: Cast table entries from API
            
        Returns:
            Dictionary with Fear Ward usage or None if not found
        """
        for entry in cast_entries:
            if entry.get("guid") == 6346:  # Fear Ward
                return {
                    "spell": "Fear Ward",
                    "casts": entry.get("total", entry.get("hitCount", 0))
                }
        return None
    
    def calculate_dispels(self, cast_entries: list, class_type: str) -> Dict[str, int]:
        """
        Calculate dispel usage from cast entries.
        
        Args:
            cast_entries: Cast table entries from API
            class_type: Player class for context
            
        Returns:
            Dictionary mapping dispel names to cast counts
        """
        dispel_ids = {
            988: "Dispel Magic",      # Priest
            552: "Abolish Disease",   # Priest
            4987: "Cleanse",          # Paladin
            2782: "Remove Curse",     # Druid
            2893: "Abolish Poison"    # Druid
        }
        
        dispels = {}
        for entry in cast_entries:
            spell_id = entry.get("guid")
            if spell_id in dispel_ids:
                count = entry.get("total", entry.get("hitCount", 0))
                dispels[dispel_ids[spell_id]] = count
                
        return dispels
    
    def add_spell_mapping(self, spell_id: int, spell_name: str) -> None:
        """
        Add a new spell mapping at runtime (for dynamic discovery).
        
        Args:
            spell_id: The spell ID
            spell_name: The spell name
        """
        names = self._load_names()
        names[spell_id] = spell_name
        
        # Clear cache to force reload
        self.get_spell_name.cache_clear()
    
    def add_spell_alias(self, variant_id: int, canonical_id: int) -> None:
        """
        Add a new spell alias at runtime.
        
        Args:
            variant_id: The variant spell ID
            canonical_id: The canonical spell ID to map to
        """
        aliases = self._load_aliases()
        aliases[variant_id] = canonical_id
        
        # Clear caches to force reload
        self.get_canonical_id.cache_clear()
        self._reverse_aliases = None
    
    def get_legacy_aliases(self) -> Dict[int, int]:
        """
        Get aliases in the format expected by legacy code.
        
        Returns:
            Dictionary mapping variant IDs to canonical IDs
        """
        return self._load_aliases()
    
    def validate_configuration(self) -> bool:
        """
        Validate the spell configuration files.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        try:
            aliases = self._load_aliases()
            names = self._load_names()
            
            print(f"✅ Loaded {len(aliases)} spell aliases")
            print(f"✅ Loaded {len(names)} spell names")
            
            # Check for circular aliases
            visited = set()
            for variant_id, canonical_id in aliases.items():
                if canonical_id in aliases and aliases[canonical_id] != canonical_id:
                    current = canonical_id
                    path = [variant_id, current]
                    
                    while current in aliases and current not in visited:
                        visited.add(current)
                        current = aliases[current]
                        path.append(current)
                        
                        if current in path[:-1]:
                            print(f"⚠️ Circular alias detected: {' -> '.join(map(str, path))}")
                            return False
            
            return True
            
        except Exception as e:
            print(f"❌ Configuration validation failed: {e}")
            return False

# Global instance for backward compatibility
_spell_manager: Optional[SpellManager] = None

def get_spell_manager() -> SpellManager:
    """Get the global spell manager instance."""
    global _spell_manager
    if _spell_manager is None:
        _spell_manager = SpellManager()
    return _spell_manager

def reset_spell_manager() -> None:
    """Reset the global spell manager instance to pick up configuration changes."""
    global _spell_manager
    _spell_manager = None

# Legacy compatibility functions
class SpellBreakdown:
    """
    Legacy compatibility class that wraps the new SpellManager.
    
    This maintains backward compatibility with existing code while
    using the new configurable system under the hood.
    """
    
    @staticmethod
    def calculate(healing_events: list) -> Dict[int, int]:
        """Legacy method for calculating spell totals."""
        manager = get_spell_manager()
        return manager.process_spell_events(healing_events)
    
    @staticmethod
    def get_spell_id_to_name_map(client, report_id: str, source_id: int) -> Tuple[Dict[int, str], Dict[int, int], list]:
        """Legacy method for getting spell mappings."""
        # This method still needs to make API calls, so we keep the original logic
        # but use the new manager for processing the results
        query = f"""
        {{
        reportData {{
            report(code: "{report_id}") {{
                table(dataType: Casts, sourceID: {source_id}, startTime: 0, endTime: 999999999)
            }}
        }}
        }}
        """
        result = client.run_query(query)
        raw_table = result["data"]["reportData"]["report"]["table"]

        entries = []
        if isinstance(raw_table, dict):
            if "data" in raw_table and "entries" in raw_table["data"]:
                entries = raw_table["data"]["entries"]
            elif "entries" in raw_table:
                entries = raw_table["entries"]

        manager = get_spell_manager()
        id_to_name, id_to_casts = manager.process_cast_entries(entries)
        
        # CRITICAL FIX: Merge cast-specific data with complete spell database
        # This ensures spell_map contains ALL known spells, not just ones this player cast
        complete_names = manager._load_names()
        complete_spell_map = {**complete_names, **id_to_name}  # Cast data overrides database
        
        return complete_spell_map, id_to_casts, entries
    
    @staticmethod
    def get_resources_used(cast_entries: list) -> Dict[str, int]:
        """Legacy method for resource usage."""
        return get_spell_manager().get_resources_used(cast_entries)
    
    @staticmethod
    def get_fear_ward_usage(cast_entries: list) -> Optional[Dict[str, Any]]:
        """Legacy method for Fear Ward usage."""
        return get_spell_manager().get_fear_ward_usage(cast_entries)
    
    @staticmethod
    def calculate_dispels(cast_entries: list, class_type: str) -> Dict[str, int]:
        """Legacy method for dispel calculation."""
        return get_spell_manager().calculate_dispels(cast_entries, class_type)
    
    @staticmethod
    def log_cleave_ids(events: list) -> None:
        """Legacy method for cleave ID logging."""
        manager = get_spell_manager()
        print("\n[CLEAVE ID CHECK] Scanning damage taken for known and unknown Cleave IDs:")
        
        cleave_variants = manager.get_variant_ids(15663)  # Get all Cleave variants
        
        for event in events:
            if event.get("type") == "damage":
                spell_id = event.get("abilityGameID")
                
                if spell_id in cleave_variants:
                    canonical_id = manager.get_canonical_id(spell_id)
                    if canonical_id == 15663:
                        print(f"  - Found mapped Cleave ID: {spell_id} -> {canonical_id}")
                elif "cleave" in str(event.get("ability", "")).lower():
                    print(f"  - Potential Cleave variant: {spell_id} — name: {event.get('ability')}")

# Initialize the legacy class attribute
SpellBreakdown.spell_id_aliases = get_spell_manager().get_legacy_aliases() 