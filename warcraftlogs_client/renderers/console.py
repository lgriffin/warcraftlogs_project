"""
Console renderer for raid analysis results.

Takes data model objects and prints formatted output to stdout.
"""

from collections import defaultdict
from typing import TYPE_CHECKING

from wcl_core.common.log import get_console
from wcl_core.models import (
    DPSPerformance,
    HealerPerformance,
    RaidAnalysis,
    TankPerformance,
)

if TYPE_CHECKING:
    from ..services import ReferenceComparison

console = get_console()

ROLES = ("tank", "healer", "melee", "ranged")


def render_raid_analysis(analysis: RaidAnalysis, role: str | None = None) -> None:
    """Render a raid analysis to the console, optionally limited to one role."""
    if role is not None and role not in ROLES:
        raise ValueError(f"Unknown role {role!r}; expected one of {', '.join(ROLES)}")

    def _wanted(r: str) -> bool:
        return role is None or role == r

    _render_metadata(analysis)
    _render_composition(analysis)
    if _wanted("tank"):
        _render_tanks(analysis.tanks)
    if _wanted("healer"):
        _render_healers(analysis.healers)
    for dps_role in ("melee", "ranged"):
        if _wanted(dps_role):
            _render_dps(analysis.dps, dps_role)
    if _wanted("healer"):
        _render_healer_summary_tables(analysis.healers)
    dps = [d for d in analysis.dps if _wanted(d.role)]
    if dps:
        _render_dps_summary_tables(dps)
    if _wanted("tank"):
        _render_tank_summary_tables(analysis.tanks)


def _render_metadata(analysis: RaidAnalysis) -> None:
    m = analysis.metadata
    console.info("\n========================")
    console.info("Report Metadata")
    console.info("========================")
    console.info(f"Title: {m.title}")
    console.info(f"Owner: {m.owner}")
    console.info(f"Date: {m.date_formatted}")

    non_tank_healer = [p.name for p in analysis.composition.melee + analysis.composition.ranged]
    console.info(f"\nCharacters Considered: {', '.join(sorted(non_tank_healer))}")


def _render_composition(analysis: RaidAnalysis) -> None:
    comp = analysis.composition
    console.info("\n===== Inferred Raid Makeup =====")

    if comp.tanks:
        console.info("Tanks:")
        by_class: dict[str, list[str]] = defaultdict(list)
        for t in comp.tanks:
            by_class[t.player_class].append(t.name)
        for cls in sorted(by_class):
            console.info(f"  {cls}: {', '.join(sorted(by_class[cls]))}")
    else:
        console.info("Tanks: None identified")

    if comp.healers:
        console.info("Healers:")
        by_class = defaultdict(list)
        for h in comp.healers:
            by_class[h.player_class].append(h.name)
        for cls in sorted(by_class):
            console.info(f"  {cls}: {', '.join(sorted(by_class[cls]))}")
    else:
        console.info("Healers: None identified")


def _render_tanks(tanks: list[TankPerformance]) -> None:
    if not tanks:
        return
    console.info("\n===== Individual Tank Reports =====")
    for tank in tanks:
        console.info(f"\n{tank.name} ({tank.player_class})")
        console.info(f"Total Taken: {tank.total_damage_taken:,}")
        console.info(f"Total Mitigated: {tank.total_mitigated:,} ({tank.mitigation_percent}%)")
        if tank.active_time_percent > 0:
            console.info(f"Active Time: {tank.active_time_percent:.1f}%")

        console.info("Damage Taken Breakdown:")
        for spell in tank.damage_taken_breakdown:
            console.info(f"  - {spell.spell_name}: {spell.casts} hits")

        console.info("Abilities Used:")
        for spell in tank.abilities_used:
            console.info(f"  - {spell.spell_name}: {spell.casts} uses")


def _render_healers(healers: list[HealerPerformance]) -> None:
    if not healers:
        return
    console.info("\n===== Individual Healer Reports =====")
    for h in healers:
        console.info(f"\n{h.name:<15} ({h.player_class})")
        console.info(f"{'Spell':<30} {'Healing':>15} {'Casts':>10}")
        console.info("-" * 60)
        for spell in h.spells:
            console.info(f"{spell.spell_name:<30} {spell.total_amount:>15,} {spell.casts:>10}")

        console.info(f"Total Healing: {h.total_healing:,}")
        console.info(f"Total Overhealing: {h.total_overhealing:,}")
        if h.active_time_percent > 0:
            console.info(f"Active Time: {h.active_time_percent:.1f}%")

        if h.fear_ward_casts > 0:
            console.info(f"Fear Ward Casts: {h.fear_ward_casts}")

        if h.dispels:
            console.info("Dispels:")
            for d in h.dispels:
                console.info(f"  - {d.spell_name}: {d.casts} casts")

        if h.resources:
            console.info("Resources Used:")
            for r in h.resources:
                console.info(f"  - {r.name}: {r.count}")


def _render_dps(all_dps: list[DPSPerformance], role: str) -> None:
    dps = [d for d in all_dps if d.role == role]
    if not dps:
        return
    label = "Melee" if role == "melee" else "Ranged"
    console.info(f"\n===== Individual {label} Reports =====")
    for d in dps:
        at_str = f"  Active Time: {d.active_time_percent:.1f}%" if d.active_time_percent > 0 else ""
        console.info(f"\n{d.name:<15} {d.total_damage:>15,}{at_str}")
        console.info(f"{'Ability':<30} {'Damage':>12} {'Casts':>8}")
        console.info("-" * 55)
        for a in d.abilities:
            console.info(f"{a.spell_name:<30} {a.total_amount:>12,} {a.casts:>8}")


def _render_healer_summary_tables(healers: list[HealerPerformance]) -> None:
    by_class: dict[str, list[HealerPerformance]] = defaultdict(list)
    for h in healers:
        by_class[h.player_class].append(h)

    for class_name in ["Priest", "Paladin", "Druid", "Shaman"]:
        group = by_class.get(class_name, [])
        if not group:
            continue

        all_spell_names: set[str] = set()
        all_dispel_names: set[str] = set()
        for h in group:
            all_spell_names.update(s.spell_name for s in h.spells)
            all_dispel_names.update(d.spell_name for d in h.dispels)

        spell_names = sorted(all_spell_names)
        dispel_names = sorted(all_dispel_names)

        console.info(f"\nHealer Summary: {class_name}")
        dispel_hdrs = "".join(f"{d[:16]:>16}" for d in dispel_names)
        header = (
            f"{'Character':<15} {'Healing':>12} {'Overheal':>12} "
            + "".join(f"{s[:14]:>16}" for s in spell_names)
            + dispel_hdrs
            + f"{'Mana Pot':>12}{'Dark Rune':>12}"
        )
        console.info(header)
        console.info("-" * len(header))

        for h in sorted(group, key=lambda x: x.total_healing, reverse=True):
            spell_lookup = {s.spell_name: s for s in h.spells}
            dispel_lookup = {d.spell_name: d.casts for d in h.dispels}
            resource_lookup = {r.name: r.count for r in h.resources}

            spell_cols = "".join(f"{spell_lookup[s].casts if s in spell_lookup else 0:>16}" for s in spell_names)
            dispel_cols = "".join(f"{dispel_lookup.get(d, 0):>16}" for d in dispel_names)
            mana = resource_lookup.get("Super Mana Potion", 0)
            rune = resource_lookup.get("Dark Rune", 0)

            console.info(
                f"{h.name:<15} {h.total_healing:>12,} {h.total_overhealing:>12,}"
                f"{spell_cols}{dispel_cols}{mana:>12}{rune:>12}"
            )


def _render_dps_summary_tables(all_dps: list[DPSPerformance]) -> None:
    by_class: dict[str, list[DPSPerformance]] = defaultdict(list)
    for d in all_dps:
        by_class[d.player_class].append(d)

    for class_name in sorted(by_class):
        group = by_class[class_name]
        all_abilities: set[str] = set()
        for d in group:
            all_abilities.update(a.spell_name for a in d.abilities)
        abilities = sorted(all_abilities)

        role_label = group[0].role.capitalize() if group else ""
        console.info(f"\n{role_label} Summary: {class_name}")
        header = f"{'Character':<15} {'Total Damage':>15}" + "".join(f"{a[:14]:>16}" for a in abilities)
        console.info(header)
        console.info("-" * len(header))

        for d in sorted(group, key=lambda x: x.total_damage, reverse=True):
            cast_lookup = {a.spell_name: a.casts for a in d.abilities}
            row = f"{d.name:<15} {d.total_damage:>15,}"
            row += "".join(f"{cast_lookup.get(a, 0):>16}" for a in abilities)
            console.info(row)


def _render_tank_summary_tables(tanks: list[TankPerformance]) -> None:
    if not tanks:
        return

    console.info("\nTank Summary: Damage Taken by Ability")
    all_taken: set[str] = set()
    for t in tanks:
        all_taken.update(s.spell_name for s in t.damage_taken_breakdown)
    taken_names = sorted(all_taken)

    header = f"{'Character':<15}" + "".join(f"{s[:14]:>16}" for s in taken_names)
    console.info(header)
    console.info("-" * len(header))
    for t in tanks:
        lookup = {s.spell_name: s.casts for s in t.damage_taken_breakdown}
        row = f"{t.name:<15}" + "".join(f"{lookup.get(s, 0):>16}" for s in taken_names)
        console.info(row)

    console.info("\nTank Summary: Damage Done by Ability")
    by_class: dict[str, list[TankPerformance]] = defaultdict(list)
    for t in tanks:
        by_class[t.player_class].append(t)

    for class_name in sorted(by_class):
        group = by_class[class_name]
        all_abilities: set[str] = set()
        for t in group:
            all_abilities.update(a.spell_name for a in t.abilities_used)
        ability_names = sorted(all_abilities)

        console.info(f"\n======= Team {class_name} (Tanks - Damage Done) =======")
        header = f"{'Character':<15}" + "".join(f"{a[:14]:>16}" for a in ability_names)
        console.info(header)
        console.info("-" * len(header))
        for t in group:
            lookup = {a.spell_name: a.casts for a in t.abilities_used}
            row = f"{t.name:<15}" + "".join(f"{lookup.get(a, 0):>16}" for a in ability_names)
            console.info(row)


def _delta(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def render_reference_comparison(comparison: "ReferenceComparison") -> None:
    """Our raid against a reference raid, as the Head to Head tab shows it."""
    g, r = comparison.guild, comparison.reference
    console.info(f"=== {g.title} ({g.raid_date[:10]}) vs reference {r.title} ({r.raid_date[:10]}) ===")
    if comparison.scope.scoped:
        extra = ", ".join(comparison.scope.guild_extra_encounters)
        console.info(f"Consumables and encounters cover the shared bosses only; the reference did not kill: {extra}")

    for title, metrics in (("Overview", comparison.overview), ("Composition", comparison.composition)):
        console.info(f"\n{title:<22} {'Ours':>12} {'Reference':>12} {'Delta':>9}")
        console.info("-" * 58)
        for m in metrics:
            console.info(f"{m.label:<22} {m.guild_display:>12} {m.reference_display:>12} {_delta(m.delta_percent):>9}")

    if comparison.classes:
        console.info(f"\n{'Class':<10} {'Role':<7} {'Metric':<13} {'Ours':>12} {'Reference':>12} {'Delta':>9}")
        console.info("-" * 68)
        for c in comparison.classes:
            ours = "—" if c.guild_average is None else f"{c.guild_average:,.0f} ({c.guild_count})"
            ref = "—" if c.reference_average is None else f"{c.reference_average:,.0f} ({c.reference_count})"
            console.info(
                f"{c.player_class:<10} {c.role:<7} {c.metric:<13} {ours:>12} {ref:>12} {_delta(c.delta_percent):>9}"
            )

    if comparison.encounters:
        console.info(f"\n{'Boss':<28} {'Ours':>8} {'Reference':>10} {'Delta':>9}")
        console.info("-" * 58)
        for e in comparison.encounters:
            ours_s, ref_s = e.guild_duration_ms // 1000, e.reference_duration_ms // 1000
            console.info(
                f"{e.name:<28} {ours_s // 60:>5}:{ours_s % 60:02d} {ref_s // 60:>7}:{ref_s % 60:02d}"
                f" {_delta(e.duration_delta_percent):>9}"
            )

    if comparison.consumables:
        console.info(f"\n{'Consumable':<32} {'Ours':>10} {'Reference':>10}")
        console.info("-" * 54)
        for cons in comparison.consumables:
            console.info(f"{cons.name:<32} {cons.guild_uses:>10} {cons.reference_uses:>10}")
