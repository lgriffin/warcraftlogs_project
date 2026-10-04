"""
Toads badges: small awards for turning up to raids and for coming prepared.

Every badge counts one thing across every stored guild raid: raids attended, raids come prepared with a flask or a
battle and guardian elixir pair, or consumables used from one family (mana potions, combat potions, drums, ...).
Each badge has up to four tiers, named after WoW item quality (uncommon, rare, epic, legendary), and a badge is
earned at its first tier. ``stacks`` says how many times the first tier has been reached, so 200 mana potions
against a first tier of 10 reads as "x20".

Default thresholds are in ``DEFAULT_RULES``. A host changes them with a ``badges`` section in its config::

    "badges": {
        "thresholds": {"attendance": [5, 15, 40, 100], "mana_potions": [20, 100]},
        "disabled": ["explosives"]
    }

``thresholds`` gives 1 to 4 ascending whole numbers per badge id; anything malformed keeps the default.
``Badge.to_dict()`` and ``PlayerBadges.to_dict()`` are the JSON shapes the Toads Hub serves, documented in
``guides/badges.md``. Badges are worked out from storage on demand; nothing is stored.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from wcl_core.common.log import get_logger
from wcl_core.flasks import FlaskCatalog, load_catalog, preparation
from wcl_store import RaidScope, narrowed

from wcl_app.context import AppContext, ScopeSource, StorageFactory, resolve_scope

if TYPE_CHECKING:
    from wcl_store import RaidRepository

logger = get_logger(__name__)

BADGES_SCHEMA_VERSION = 1

# What a badge counts.
RAIDS = "raids"  # raids attended
CONSUMABLES = "consumables"  # consumables used; ``items`` narrows it to one family
FLASKED = "flasked"  # raids with a flask, or a battle and a guardian elixir (``wcl_core.flasks``)

# Tier n (1-based) has quality QUALITIES[n - 1]; tier 0 means not earned yet.
QUALITIES = ("uncommon", "rare", "epic", "legendary")
MAX_TIERS = len(QUALITIES)

GUILD_SOURCES = ("guild",)


# ── Rules ──


@dataclass(frozen=True)
class BadgeRule:
    """One badge: what it counts and the count each tier needs."""

    id: str
    name: str
    description: str
    icon: str  # stable icon id a frontend maps to its own artwork
    glyph: str  # an emoji a frontend without artwork can draw
    unit: str  # plural noun for the count, "raids" or "potions"
    thresholds: tuple[int, ...]
    metric: str = CONSUMABLES
    items: frozenset[str] = frozenset()  # lower-case consumable names; empty counts every consumable
    exclude: frozenset[str] = frozenset()  # lower-case names an empty ``items`` leaves out

    def count(self, stats: PlayerStats) -> int:
        if self.metric == RAIDS:
            return stats.raids
        if self.metric == FLASKED:
            return stats.flasked_raids
        if not self.items:
            return sum(n for name, n in stats.consumables.items() if name.lower() not in self.exclude)
        return sum(n for name, n in stats.consumables.items() if name.lower() in self.items)

    def award(self, stats: PlayerStats) -> Badge:
        """This badge for one player, earned or not, with progress towards the next tier."""
        value = self.count(stats)
        tier = sum(1 for at in self.thresholds if value >= at)
        next_at = self.thresholds[tier] if tier < len(self.thresholds) else None
        floor = self.thresholds[tier - 1] if tier else 0
        progress = 1.0 if next_at is None else round((value - floor) / (next_at - floor), 3)
        return Badge(
            id=self.id,
            name=self.name,
            description=self.description,
            icon=self.icon,
            glyph=self.glyph,
            tier=tier,
            quality=_quality(tier),
            tier_name=_quality(tier).capitalize(),
            value=value,
            display=f"{value:,} {self.unit if value != 1 else _singular(self.unit)}",
            stacks=value // self.thresholds[0],
            next_at=next_at,
            next_tier=_quality(tier + 1).capitalize() if next_at is not None else "",
            progress=progress,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "glyph": self.glyph,
            "unit": self.unit,
            "tiers": [
                {"tier": n, "quality": _quality(n), "name": _quality(n).capitalize(), "at": at}
                for n, at in enumerate(self.thresholds, 1)
            ],
        }


def _quality(tier: int) -> str:
    return QUALITIES[tier - 1] if 1 <= tier <= MAX_TIERS else ""


def _singular(unit: str) -> str:
    return unit[:-1] if unit.endswith("s") else unit


def _items(*names: str) -> frozenset[str]:
    return frozenset(n.lower() for n in names)


# Consumable names as ``wcl_core/data/consumes_config.json`` records them.
MANA_POTIONS = _items(
    "Super Mana Potion",
    "Fel Mana Potion",
    "Crystal Mana Potion",
    "Unstable Mana Potion",
    "Auchenai Mana Potion",
    "Bottled Nethergon Energy",
    "Major Dreamless Sleep Potion",
)
HEALING_POTIONS = _items(
    "Super Healing Potion",
    "Volatile Healing Potion",
    "Auchenai Healing Potion",
    "Crystal Healing Potion",
    "Bottled Nethergon Vapor",
    "Super Rejuvenation Potion",
    "Master Healthstone",
    "Nightmare Seed",
)
COMBAT_POTIONS = _items(
    "Destruction Potion",
    "Haste Potion",
    "Heroic Potion",
    "Insane Strength Potion",
    "Ironshield Potion",
    "Mad Alchemist's Potion",
    "Mighty Rage Potion",
)
RUNES = _items("Dark Rune", "Demonic Rune")
DRUMS = _items("Drums of Battle")
EXPLOSIVES = _items(
    "Super Sapper Charge",
    "Goblin Sapper Charge",
    "Adamantite Grenade",
    "Fel Iron Bomb",
    "Gnomish Flame Turret",
)
WEAPON_ENHANCEMENTS = _items(
    "Superior Wizard Oil",
    "Superior Mana Oil",
    "Adamantite Sharpening Stone",
    "Adamantite Weightstone",
)
# Flasks and elixirs have their own badge, and a flask's aura can be applied many times a raid, so Well Stocked
# leaves them out.
FLASKS_AND_ELIXIRS = _items(*load_catalog().names)
SCROLLS = _items("Scroll of Agility V", "Scroll of Agility IV", "Scroll of Strength V", "Scroll of Strength IV")

DEFAULT_RULES: tuple[BadgeRule, ...] = (
    BadgeRule("attendance", "Loyal Toad", "Raids attended", "attendance", "🐸", "raids", (5, 15, 40, 100), RAIDS),
    BadgeRule(
        "well_stocked",
        "Well Stocked",
        "Consumables used, not counting flasks and elixirs",
        "consumables",
        "🎒",
        "consumables",
        (50, 250, 750, 2000),
        exclude=FLASKS_AND_ELIXIRS,
    ),
    BadgeRule(
        "mana_potions",
        "Mana Guzzler",
        "Mana potions",
        "mana_potion",
        "🧪",
        "potions",
        (10, 50, 150, 400),
        items=MANA_POTIONS,
    ),
    BadgeRule(
        "healing_potions",
        "Survivor",
        "Healing potions and healthstones",
        "healing_potion",
        "💗",
        "potions",
        (10, 40, 100, 250),
        items=HEALING_POTIONS,
    ),
    BadgeRule(
        "combat_potions",
        "Liquid Courage",
        "Destruction, Haste and other combat potions",
        "combat_potion",
        "🔥",
        "potions",
        (10, 50, 150, 400),
        items=COMBAT_POTIONS,
    ),
    BadgeRule("runes", "Rune Eater", "Dark and Demonic Runes", "rune", "🔮", "runes", (10, 40, 100, 250), items=RUNES),
    BadgeRule("drums", "Drummer", "Drums of Battle", "drums", "🥁", "drums", (10, 50, 150, 400), items=DRUMS),
    BadgeRule(
        "explosives",
        "Sapper",
        "Sapper charges, grenades and bombs",
        "explosive",
        "💣",
        "explosives",
        (10, 50, 150, 400),
        items=EXPLOSIVES,
    ),
    BadgeRule(
        "weapon_enhancements",
        "Sharpened",
        "Weapon oils and stones",
        "weapon_enhancement",
        "✨",
        "applications",
        (5, 20, 50, 120),
        items=WEAPON_ENHANCEMENTS,
    ),
    BadgeRule(
        "scrolls",
        "Scholar",
        "Scrolls of Agility and Strength",
        "scroll",
        "📜",
        "scrolls",
        (5, 20, 50, 120),
        items=SCROLLS,
    ),
    BadgeRule(
        "flasked",
        "Flask Bearer",
        "Raids with a flask, or a battle and a guardian elixir",
        "flask",
        "⚗️",
        "raids",
        (5, 15, 40, 100),
        FLASKED,
    ),
)


def _thresholds(value: object) -> tuple[int, ...] | None:
    """1 to ``MAX_TIERS`` ascending positive whole numbers, else None."""
    if not isinstance(value, list | tuple) or not 1 <= len(value) <= MAX_TIERS:
        return None
    if not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in value):
        return None
    if any(a >= b for a, b in pairwise(value)):
        return None
    return tuple(value)


def _override(rule: BadgeRule, overrides: Mapping[str, Any]) -> BadgeRule:
    if rule.id not in overrides:
        return rule
    thresholds = _thresholds(overrides[rule.id])
    if thresholds is None:
        logger.warning("Ignoring badge thresholds for %s: %r", rule.id, overrides[rule.id])
        return rule
    return replace(rule, thresholds=thresholds)


@dataclass(frozen=True)
class BadgeRules:
    """The badges in play and their thresholds."""

    rules: tuple[BadgeRule, ...] = DEFAULT_RULES

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> BadgeRules:
        """Defaults with the config's ``badges`` section applied; malformed entries keep the default."""
        section = config.get("badges")
        if not isinstance(section, Mapping):
            return cls()
        disabled = section.get("disabled")
        off = {i for i in disabled if isinstance(i, str)} if isinstance(disabled, list) else set()
        overrides = section.get("thresholds")
        overrides = overrides if isinstance(overrides, Mapping) else {}
        return cls(tuple(_override(rule, overrides) for rule in DEFAULT_RULES if rule.id not in off))

    def award(self, stats: PlayerStats) -> PlayerBadges:
        return PlayerBadges(stats.name, stats.player_class, [rule.award(stats) for rule in self.rules])

    def to_dict(self) -> dict[str, Any]:
        return {"version": BADGES_SCHEMA_VERSION, "badges": [r.to_dict() for r in self.rules]}


# ── Payloads ──


@dataclass
class Badge:
    """One badge for one player. ``tier`` 0 means not earned yet; ``progress`` runs 0 to 1 to the next tier."""

    id: str
    name: str
    description: str
    icon: str
    glyph: str
    tier: int
    quality: str  # "uncommon", "rare", "epic", "legendary", or "" when not earned
    tier_name: str
    value: int
    display: str
    stacks: int
    next_at: int | None
    next_tier: str
    progress: float

    @property
    def earned(self) -> bool:
        return self.tier > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlayerStats:
    """What badges count for one player: raids attended, raids prepared (``flasked_raids``) and consumables used, by
    consumable name."""

    name: str
    player_class: str = ""
    raids: int = 0
    consumables: dict[str, int] = field(default_factory=dict)
    flasked_raids: int = 0


@dataclass
class PlayerBadges:
    """Every badge in play for one player, earned or not, in rule order."""

    name: str
    player_class: str
    badges: list[Badge]

    @property
    def earned(self) -> list[Badge]:
        return [b for b in self.badges if b.earned]

    @property
    def score(self) -> int:
        """Tiers earned across every badge: how a roster is ranked."""
        return sum(b.tier for b in self.badges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "player_class": self.player_class,
            "score": self.score,
            "badges": [b.to_dict() for b in self.badges],
        }


# ── Reading storage ──


def _prepared_raids(rows: Iterable[Mapping[str, Any]], catalog: FlaskCatalog) -> int:
    """Raids with a flask or an elixir pair, from rows with ``raid_id`` and ``consumable_name``."""
    names_by_raid: dict[Any, set[str]] = {}
    for row in rows:
        names_by_raid.setdefault(row["raid_id"], set()).add(row["consumable_name"])
    return sum(1 for names in names_by_raid.values() if preparation(names, catalog))


def character_stats(
    repo: RaidRepository, name: str, sources: tuple[str, ...] = GUILD_SOURCES, scope: RaidScope | None = None
) -> PlayerStats:
    """One character's counts, matched case-insensitively, over the raids inside ``scope`` when given."""
    scope = narrowed(scope, sources)
    raids = {r["raid_id"] for r in repo.get_character_raid_roles(name, sources, scope=scope)}
    rows = repo.get_character_consumable_counts(name, sources, scope=scope)
    consumables: dict[str, int] = {}
    for row in rows:
        consumables[row["consumable_name"]] = consumables.get(row["consumable_name"], 0) + row["count"]
    flasked = _prepared_raids((r for r in rows if r["count"] > 0), load_catalog())
    return PlayerStats(name, raids=len(raids), consumables=consumables, flasked_raids=flasked)


def guild_stats(
    repo: RaidRepository, sources: tuple[str, ...] = GUILD_SOURCES, scope: RaidScope | None = None
) -> dict[str, PlayerStats]:
    """Counts for every character, keyed by lower-case name, over the raids inside ``scope`` when given."""
    scope = narrowed(scope, sources)
    stats: dict[str, PlayerStats] = {}
    for row in repo.get_raid_attendance(sources, scope=scope):
        stats[row["name"].lower()] = PlayerStats(row["name"], row["player_class"] or "", row["raids"])
    for row in repo.get_consumable_totals(sources, scope=scope):
        player = stats.setdefault(row["name"].lower(), PlayerStats(row["name"]))
        player.consumables[row["consumable_name"]] = row["count"]
    catalog = load_catalog()
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in repo.get_consumable_raids(catalog.names, sources, scope=scope):
        rows_by_name.setdefault(row["name"].lower(), []).append(row)
    for key, rows in rows_by_name.items():
        player = stats.setdefault(key, PlayerStats(rows[0]["name"]))
        player.flasked_raids = _prepared_raids(rows, catalog)
    return stats


# ── Service ──


class BadgeService:
    """Badges for one character or the whole guild, over any ``RaidRepository``."""

    def __init__(
        self,
        storage: StorageFactory,
        rules: BadgeRules | None = None,
        sources: tuple[str, ...] = GUILD_SOURCES,
        scope: ScopeSource = None,
    ):
        self.storage = storage
        self.rules = rules if rules is not None else BadgeRules()
        self.sources = sources
        # A scope, or a callable giving the active profile's at read time; None counts every raid of ``sources``.
        self._scope = scope

    @property
    def scope(self) -> RaidScope | None:
        return resolve_scope(self._scope)

    @classmethod
    def from_context(cls, ctx: AppContext) -> BadgeService:
        """Badges over the context's storage and active profile, with thresholds from its config."""
        return cls(ctx.repository, BadgeRules.from_config(ctx.config), scope=lambda: ctx.scope)

    def catalogue(self) -> list[BadgeRule]:
        return list(self.rules.rules)

    def for_character(self, name: str) -> PlayerBadges:
        with self.storage() as repo:
            return self.rules.award(character_stats(repo, name, self.sources, self.scope))

    def for_guild(self, names: Iterable[str] | None = None) -> list[PlayerBadges]:
        """Every character (or just ``names``), most tiers first, then by name."""
        with self.storage() as repo:
            stats = guild_stats(repo, self.sources, self.scope)
        if names is not None:
            wanted = {n.lower() for n in names}
            stats = {k: v for k, v in stats.items() if k in wanted}
        players = [self.rules.award(s) for s in stats.values()]
        return sorted(players, key=lambda p: (-p.score, p.name.lower()))
