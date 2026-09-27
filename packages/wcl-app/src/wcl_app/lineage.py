"""
Character lineage: how a character's numbers spread across every raid they're in.

For each metric this gives min, mean and max over the raids it applies to, plus
the raid count, so a player can see their typical night next to their best and
worst. Spell casts are averaged over raids in the role that spell was recorded
for (a healer's Flash Heal isn't diluted by their dps nights). Consumables are
averaged over every raid attended, counting a raid where they used none as 0.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wcl_store import RaidRepository


@dataclass
class Spread:
    """min / mean / max of one metric over ``raids`` raids."""

    name: str
    min: float
    mean: float
    max: float
    raids: int
    total: float
    role: str = ""  # which role's raids the spread covers, "" for all
    raids_used: int = 0  # raids where the value was above zero

    @classmethod
    def of(cls, name: str, values: list[float], role: str = "") -> Spread:
        return cls(
            name=name,
            min=min(values),
            mean=round(sum(values) / len(values), 2),
            max=max(values),
            raids=len(values),
            total=sum(values),
            role=role,
            raids_used=sum(1 for v in values if v),
        )


@dataclass
class CharacterLineage:
    character: str
    raids: int
    role_counts: dict[str, int] = field(default_factory=dict)
    first_raid: str | None = None
    last_raid: str | None = None
    metrics: list[Spread] = field(default_factory=list)
    casts: list[Spread] = field(default_factory=list)
    consumables: list[Spread] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Per-raid headline numbers by role: (column, label).
_ROLE_METRICS: dict[str, list[tuple[str, str]]] = {
    "healer": [("healing", "Healing"), ("overheal_percent", "Overheal %")],
    "tank": [("damage_taken", "Damage taken"), ("mitigation_percent", "Mitigation %")],
    "melee": [("damage", "Damage")],
    "ranged": [("damage", "Damage")],
}


def character_lineage(
    db: RaidRepository, character_name: str, sources: tuple[str, ...] = ("guild",)
) -> CharacterLineage | None:
    raids = db.get_character_raid_roles(character_name, sources)
    if not raids:
        return None

    raid_role = {r["raid_id"]: r["role"] for r in raids}
    raids_by_role: dict[str, list[int]] = defaultdict(list)
    for r in raids:
        raids_by_role[r["role"]].append(r["raid_id"])

    lineage = CharacterLineage(
        character=character_name,
        raids=len(raids),
        role_counts={role: len(ids) for role, ids in sorted(raids_by_role.items())},
        first_raid=raids[0]["raid_date"],
        last_raid=raids[-1]["raid_date"],
    )

    # Headline metrics, per role.
    for role, columns in _ROLE_METRICS.items():
        role_rows = [r for r in raids if r["role"] == role]
        for column, label in columns:
            values = [float(r[column]) for r in role_rows if r[column] is not None]
            if values:
                lineage.metrics.append(Spread.of(label, values, role))

    # Casts: total per raid across all spells, then per spell within its role.
    cast_rows = db.get_character_spell_casts(character_name, sources)
    per_raid_total: dict[int, float] = dict.fromkeys(raid_role, 0.0)
    per_spell: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for c in cast_rows:
        per_raid_total[c["raid_id"]] = per_raid_total.get(c["raid_id"], 0.0) + c["casts"]
        key = (c["role"], c["spell_name"])
        per_spell[key][c["raid_id"]] = per_spell[key].get(c["raid_id"], 0.0) + c["casts"]
    if cast_rows:
        lineage.metrics.append(Spread.of("Total casts", list(per_raid_total.values())))
    for (role, spell), by_raid in per_spell.items():
        values = [by_raid.get(raid_id, 0.0) for raid_id in raids_by_role.get(role, [])]
        if values:
            lineage.casts.append(Spread.of(spell, values, role))
    lineage.casts.sort(key=lambda s: (-s.mean, s.name))

    # Consumables: over every raid attended, zero where none were used.
    per_item: dict[str, dict[int, float]] = defaultdict(dict)
    per_raid_consumes: dict[int, float] = dict.fromkeys(raid_role, 0.0)
    for c in db.get_character_consumable_counts(character_name, sources):
        if c["raid_id"] not in raid_role:
            continue
        per_item[c["consumable_name"]][c["raid_id"]] = c["count"]
        per_raid_consumes[c["raid_id"]] += c["count"]
    if per_item:
        lineage.metrics.append(Spread.of("Consumables used", list(per_raid_consumes.values())))
    for item, by_raid in per_item.items():
        lineage.consumables.append(Spread.of(item, [by_raid.get(raid_id, 0.0) for raid_id in raid_role]))
    lineage.consumables.sort(key=lambda s: (-s.mean, s.name))

    return lineage
