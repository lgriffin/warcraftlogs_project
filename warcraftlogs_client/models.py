"""
Data models for Warcraft Logs Analysis Tool.

These dataclasses represent the results of all analysis operations.
They decouple data from presentation, enabling:
- GUI rendering (Phase 2)
- Database persistence (historical tracking)
- Multiple export formats (console, markdown, CSV)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SpellUsage:
    spell_id: int
    spell_name: str
    casts: int = 0
    total_amount: int = 0


@dataclass
class DispelUsage:
    spell_name: str
    casts: int = 0


@dataclass
class ResourceUsage:
    name: str
    count: int = 0


@dataclass
class HealerPerformance:
    name: str
    player_class: str
    source_id: int
    total_healing: int = 0
    total_overhealing: int = 0
    overheal_percent: float = 0.0
    spells: list[SpellUsage] = field(default_factory=list)
    dispels: list[DispelUsage] = field(default_factory=list)
    resources: list[ResourceUsage] = field(default_factory=list)
    fear_ward_casts: int = 0

    def __post_init__(self):
        total = self.total_healing + self.total_overhealing
        if total > 0:
            self.overheal_percent = round(self.total_overhealing / total * 100, 1)


@dataclass
class TankPerformance:
    name: str
    player_class: str
    source_id: int
    total_damage_taken: int = 0
    total_mitigated: int = 0
    mitigation_percent: float = 0.0
    damage_taken_breakdown: list[SpellUsage] = field(default_factory=list)
    abilities_used: list[SpellUsage] = field(default_factory=list)

    def __post_init__(self):
        total = self.total_damage_taken + self.total_mitigated
        if total > 0:
            self.mitigation_percent = round(self.total_mitigated / total * 100, 2)


@dataclass
class DPSPerformance:
    name: str
    player_class: str
    source_id: int
    role: str  # "melee" or "ranged"
    total_damage: int = 0
    abilities: list[SpellUsage] = field(default_factory=list)


@dataclass
class ConsumableUsage:
    player_name: str
    player_role: str
    report_id: str
    consumable_name: str
    count: int = 0
    timestamps: list[int] = field(default_factory=list)

    @property
    def timestamps_formatted(self) -> str:
        if not self.timestamps:
            return ""
        parts = []
        for ms in self.timestamps:
            total_seconds = ms // 1000
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            parts.append(f"{minutes:02d}:{seconds:02d}")
        return ", ".join(parts)


@dataclass
class PotionSpike:
    timestamp_ms: int
    potion_name: str
    player_count: int
    players: list[str] = field(default_factory=list)
    non_users: list[str] = field(default_factory=list)
    next_boss_name: Optional[str] = None

    @property
    def time_formatted(self) -> str:
        seconds = self.timestamp_ms // 1000
        return f"{seconds // 60:02d}:{seconds % 60:02d}"


@dataclass
class RaidMetadata:
    report_id: str
    title: str
    owner: str
    start_time: int
    end_time: Optional[int] = None

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.start_time / 1000)

    @property
    def date_formatted(self) -> str:
        return self.date.strftime("%A, %B %d %Y %H:%M:%S")

    @property
    def url(self) -> str:
        return f"https://www.warcraftlogs.com/reports/{self.report_id}"


@dataclass
class PlayerIdentity:
    name: str
    player_class: str
    source_id: int
    role: str  # "tank", "healer", "melee", "ranged", "unknown"


@dataclass
class RaidComposition:
    tanks: list[PlayerIdentity] = field(default_factory=list)
    healers: list[PlayerIdentity] = field(default_factory=list)
    melee: list[PlayerIdentity] = field(default_factory=list)
    ranged: list[PlayerIdentity] = field(default_factory=list)

    @property
    def all_players(self) -> list[PlayerIdentity]:
        return self.tanks + self.healers + self.melee + self.ranged

    def get_player(self, name: str) -> Optional[PlayerIdentity]:
        for p in self.all_players:
            if p.name == name:
                return p
        return None


@dataclass
class RaidAnalysis:
    """Complete result of analyzing a single raid report."""
    metadata: RaidMetadata
    composition: RaidComposition
    healers: list[HealerPerformance] = field(default_factory=list)
    tanks: list[TankPerformance] = field(default_factory=list)
    dps: list[DPSPerformance] = field(default_factory=list)
    consumables: list[ConsumableUsage] = field(default_factory=list)


@dataclass
class ConsumesAnalysisResult:
    """Complete result of analyzing consumables across raids."""
    raid_metadata: dict[str, RaidMetadata] = field(default_factory=dict)
    consumable_usage: list[ConsumableUsage] = field(default_factory=list)
    potion_spikes: list[PotionSpike] = field(default_factory=list)


@dataclass
class CharacterHistory:
    """Historical performance summary for a single character."""
    name: str
    player_class: str
    total_raids: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    avg_healing: Optional[float] = None
    avg_damage: Optional[float] = None
    avg_mitigation_percent: Optional[float] = None
    total_consumables_used: int = 0


@dataclass
class RaidGroup:
    """A named group of characters with associated raid days."""
    id: int = 0
    name: str = ""
    raid_days: list[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    members: list[str] = field(default_factory=list)


# ── WCL Character Profile / Gear models ──

GEAR_SLOT_ORDER = [
    "Head", "Neck", "Shoulder", "Shirt", "Chest",
    "Waist", "Legs", "Feet", "Wrist", "Hands",
    "Finger 1", "Finger 2", "Trinket 1", "Trinket 2",
    "Back", "Main Hand", "Off Hand", "Ranged/Relic", "Tabard",
]

GEAR_SLOTS_HIDDEN = {"Shirt", "Tabard"}

QUALITY_NAMES = {0: "Poor", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic", 5: "Legendary"}


@dataclass
class GearItem:
    slot: str
    item_id: int
    item_level: int = 0
    quality: int = 0
    enchant_id: int = 0
    gems: list[int] = field(default_factory=list)

    @property
    def quality_name(self) -> str:
        return QUALITY_NAMES.get(self.quality, "Unknown")

    @property
    def wowhead_url(self) -> str:
        return f"https://www.wowhead.com/classic/item={self.item_id}" if self.item_id else ""

WOW_CLASS_NAMES = {
    1: "Death Knight", 2: "Druid", 3: "Hunter", 4: "Mage",
    5: "Monk", 6: "Paladin", 7: "Priest", 8: "Rogue",
    9: "Shaman", 10: "Warlock", 11: "Warrior",
    12: "Demon Hunter", 13: "Evoker",
}


@dataclass
class EncounterRanking:
    encounter_id: int
    encounter_name: str
    spec: str = ""
    best_percent: float = 0.0
    median_percent: float = 0.0
    total_kills: int = 0
    fastest_kill_ms: int = 0
    locked_in: bool = False

    @property
    def fastest_kill_formatted(self) -> str:
        s = self.fastest_kill_ms // 1000
        return f"{s // 60}:{s % 60:02d}"


@dataclass
class AllStarRanking:
    spec: str
    points: float = 0.0
    possible_points: float = 0.0
    rank: int = 0
    region_rank: int = 0
    server_rank: int = 0
    rank_percent: float = 0.0
    total: int = 0


@dataclass
class ZoneRankingResult:
    zone_id: int = 0
    zone_name: str = ""
    difficulty: int = 0
    metric: str = "dps"
    partition: int = 0
    best_average: float = 0.0
    median_average: float = 0.0
    all_stars: list[AllStarRanking] = field(default_factory=list)
    encounter_rankings: list[EncounterRanking] = field(default_factory=list)


@dataclass
class CharacterReportEntry:
    code: str
    title: str
    start_time: int = 0
    zone_name: str = ""

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.start_time / 1000)

    @property
    def date_formatted(self) -> str:
        return self.date.strftime("%Y-%m-%d %H:%M")


@dataclass
class CharacterProfile:
    """Complete character profile from WCL API."""
    name: str
    server: str
    region: str
    class_id: int = 0
    level: int = 0
    faction: str = ""
    guild_name: str = ""
    zone_rankings: list[ZoneRankingResult] = field(default_factory=list)
    recent_reports: list[CharacterReportEntry] = field(default_factory=list)
    gear_items: list[GearItem] = field(default_factory=list)

    @property
    def class_name(self) -> str:
        return WOW_CLASS_NAMES.get(self.class_id, "Unknown")
