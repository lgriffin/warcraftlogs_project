"""
Markdown renderer for raid analysis results.

Takes data model objects and produces a markdown string suitable for
file export or embedding in a UI.
"""

import os
from collections import defaultdict

from ..models import (
    ConsumableUsage,
    DPSPerformance,
    HealerPerformance,
    RaidAnalysis,
    TankPerformance,
)


def render_raid_analysis(analysis: RaidAnalysis) -> str:
    """Render a complete raid analysis to a markdown string."""
    sections = [
        _render_metadata(analysis),
        _render_composition(analysis),
        _render_healer_summary_tables(analysis.healers),
        _render_tank_summary_tables(analysis.tanks),
        _render_dps_summary_tables(analysis.dps, "melee"),
        _render_dps_summary_tables(analysis.dps, "ranged"),
        _render_consumables(analysis.consumables),
    ]
    return "\n".join(s for s in sections if s)


def export_raid_analysis(analysis: RaidAnalysis, output_path: str | None = None) -> str:
    """Render and write a raid analysis markdown file. Returns the path written."""
    content = render_raid_analysis(analysis)

    if not output_path:
        safe_title = "".join(
            c if c.isalnum() or c in " _-" else "_"
            for c in analysis.metadata.title
        ).strip().replace(" ", "_")
        from .. import paths
        output_path = os.path.join(str(paths.get_reports_dir()), f"{safe_title}.md")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path


# ── Sections ──


def _render_metadata(analysis: RaidAnalysis) -> str:
    m = analysis.metadata
    lines = [
        f"# {m.title}",
        "",
        f"- **Owner:** {m.owner}",
        f"- **Date:** {m.date_formatted}",
        f"- **Log:** [{m.report_id}]({m.url})",
        "",
    ]
    return "\n".join(lines)


def _render_composition(analysis: RaidAnalysis) -> str:
    comp = analysis.composition
    lines = ["## Raid Composition", ""]

    for label, group in [("Tanks", comp.tanks), ("Healers", comp.healers)]:
        if not group:
            continue
        by_class: dict[str, list[str]] = defaultdict(list)
        for p in group:
            by_class[p.player_class].append(p.name)
        lines.append(f"**{label}**")
        for cls in sorted(by_class):
            lines.append(f"- {cls}: {', '.join(sorted(by_class[cls]))}")
        lines.append("")

    dps_players = comp.melee + comp.ranged
    if dps_players:
        by_class: dict[str, list[str]] = defaultdict(list)
        for p in dps_players:
            by_class[p.player_class].append(p.name)
        lines.append("**DPS**")
        for cls in sorted(by_class):
            lines.append(f"- {cls}: {', '.join(sorted(by_class[cls]))}")
        lines.append("")

    return "\n".join(lines)


def _render_healer_summary_tables(healers: list[HealerPerformance]) -> str:
    if not healers:
        return ""

    by_class: dict[str, list[HealerPerformance]] = defaultdict(list)
    for h in healers:
        by_class[h.player_class].append(h)

    lines = ["## Healer Summary", ""]

    for class_name in ["Priest", "Paladin", "Druid", "Shaman"]:
        group = by_class.get(class_name)
        if not group:
            continue

        all_spell_names: set[str] = set()
        all_dispel_names: set[str] = set()
        for h in group:
            all_spell_names.update(s.spell_name for s in h.spells)
            all_dispel_names.update(d.spell_name for d in h.dispels)

        spell_names = sorted(all_spell_names)
        dispel_names = sorted(all_dispel_names)

        lines.append(f"### {class_name}")
        lines.append("")

        headers = ["Character", "Healing", "Overheal%"]
        headers.extend(spell_names)
        headers.extend(dispel_names)
        headers.extend(["Mana Pot", "Dark Rune"])

        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")

        for h in sorted(group, key=lambda x: x.total_healing, reverse=True):
            spell_lookup = {s.spell_name: s for s in h.spells}
            dispel_lookup = {d.spell_name: d.casts for d in h.dispels}
            resource_lookup = {r.name: r.count for r in h.resources}

            cells = [
                h.name,
                f"{h.total_healing:,}",
                f"{h.overheal_percent:.1f}%",
            ]
            cells.extend(
                str(spell_lookup[s].casts) if s in spell_lookup else "0"
                for s in spell_names
            )
            cells.extend(str(dispel_lookup.get(d, 0)) for d in dispel_names)
            cells.append(str(resource_lookup.get("Super Mana Potion", 0)))
            cells.append(str(resource_lookup.get("Dark Rune", 0)))

            lines.append("| " + " | ".join(cells) + " |")

        lines.append("")

    return "\n".join(lines)


def _render_tank_summary_tables(tanks: list[TankPerformance]) -> str:
    if not tanks:
        return ""

    lines = ["## Tank Summary", ""]

    # Damage taken breakdown
    all_taken: set[str] = set()
    for t in tanks:
        all_taken.update(s.spell_name for s in t.damage_taken_breakdown)
    taken_names = sorted(all_taken)

    if taken_names:
        lines.append("### Damage Taken")
        lines.append("")
        headers = ["Character", "Total Taken", "Mitigation%"] + taken_names
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")

        for t in tanks:
            lookup = {s.spell_name: s.casts for s in t.damage_taken_breakdown}
            cells = [
                t.name,
                f"{t.total_damage_taken:,}",
                f"{t.mitigation_percent:.1f}%",
            ]
            cells.extend(str(lookup.get(n, 0)) for n in taken_names)
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    # Abilities used, grouped by class
    by_class: dict[str, list[TankPerformance]] = defaultdict(list)
    for t in tanks:
        by_class[t.player_class].append(t)

    for class_name in sorted(by_class):
        group = by_class[class_name]
        all_abilities: set[str] = set()
        for t in group:
            all_abilities.update(a.spell_name for a in t.abilities_used)
        ability_names = sorted(all_abilities)

        if not ability_names:
            continue

        lines.append(f"### {class_name} — Abilities Used")
        lines.append("")
        headers = ["Character"] + ability_names
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")

        for t in group:
            lookup = {a.spell_name: a.casts for a in t.abilities_used}
            cells = [t.name]
            cells.extend(str(lookup.get(a, 0)) for a in ability_names)
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    return "\n".join(lines)


def _render_dps_summary_tables(all_dps: list[DPSPerformance], role: str) -> str:
    dps = [d for d in all_dps if d.role == role]
    if not dps:
        return ""

    label = "Melee" if role == "melee" else "Ranged"
    by_class: dict[str, list[DPSPerformance]] = defaultdict(list)
    for d in dps:
        by_class[d.player_class].append(d)

    lines = [f"## {label} DPS Summary", ""]

    for class_name in sorted(by_class):
        group = by_class[class_name]
        all_abilities: set[str] = set()
        for d in group:
            all_abilities.update(a.spell_name for a in d.abilities)
        abilities = sorted(all_abilities)

        lines.append(f"### {class_name}")
        lines.append("")
        headers = ["Character", "Total Damage"] + abilities
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")

        for d in sorted(group, key=lambda x: x.total_damage, reverse=True):
            cast_lookup = {a.spell_name: a.casts for a in d.abilities}
            cells = [d.name, f"{d.total_damage:,}"]
            cells.extend(str(cast_lookup.get(a, 0)) for a in abilities)
            lines.append("| " + " | ".join(cells) + " |")

        lines.append("")

    return "\n".join(lines)


def render_cross_analysis(raid_stats: dict, historical: list[dict],
                          player_deltas: list[dict], size_label: str) -> str:
    lines = [
        f"# Cross-Analysis: {raid_stats['title']}",
        "",
        f"- **Date:** {raid_stats.get('raid_date', '')[:10]}",
        f"- **Raid Size:** {size_label}",
        f"- **Compared Against:** {len(historical)} raids",
        "",
    ]

    if historical:
        def _fmt(val):
            if val is None:
                return "N/A"
            if abs(val) >= 1_000_000:
                return f"{val / 1_000_000:.1f}M"
            if abs(val) >= 1_000:
                return f"{val / 1_000:.1f}K"
            return f"{val:,.0f}"

        def _dur(ms):
            if not ms or ms <= 0:
                return "N/A"
            s = ms / 1000
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            return f"{h}h {m}m" if h else f"{m}m"

        def _pct(cur, avg):
            if not avg:
                return "—"
            p = (cur - avg) / avg * 100
            return f"{p:+.1f}%"

        avg_dur = sum(h["duration_ms"] for h in historical) / len(historical)
        avg_dmg = sum(h["total_damage"] for h in historical) / len(historical)
        avg_hps = sum(h["total_healing"] for h in historical) / len(historical)
        avg_taken = sum(h["total_damage_taken"] for h in historical) / len(historical)

        lines.extend([
            "## Raid Summary",
            "",
            "| Metric | This Raid | Historical Avg | Change |",
            "| --- | --- | --- | --- |",
            f"| Duration | {_dur(raid_stats['duration_ms'])} | {_dur(avg_dur)} | {_pct(raid_stats['duration_ms'], avg_dur)} |",
            f"| Total Damage | {_fmt(raid_stats['total_damage'])} | {_fmt(avg_dmg)} | {_pct(raid_stats['total_damage'], avg_dmg)} |",
            f"| Total Healing | {_fmt(raid_stats['total_healing'])} | {_fmt(avg_hps)} | {_pct(raid_stats['total_healing'], avg_hps)} |",
            f"| Damage Taken | {_fmt(raid_stats['total_damage_taken'])} | {_fmt(avg_taken)} | {_pct(raid_stats['total_damage_taken'], avg_taken)} |",
            "",
        ])

    role_order = [
        ("Healers", "healer"),
        ("Tanks", "tank"),
        ("Melee DPS", "melee"),
        ("Ranged DPS", "ranged"),
    ]

    for role_label, role_key in role_order:
        players = [p for p in player_deltas if p["role"] == role_key]
        if not players:
            continue

        lines.extend([f"## {role_label}", ""])

        for p in sorted(players, key=lambda x: x["name"]):
            m = p["metrics"]
            lines.append(f"### {p['name']} ({p['player_class']})")
            lines.append("")

            if role_key == "healer":
                lines.extend([
                    "| Metric | This Raid | Avg | Change |",
                    "| --- | --- | --- | --- |",
                    f"| Healing | {_fmt(m.get('total_healing'))} | {_fmt(m.get('avg_healing'))} | {_pct(m.get('total_healing', 0), m.get('avg_healing'))} |",
                    f"| Overheal % | {m.get('overheal_percent', 0):.1f}% | {m.get('avg_overheal', 0):.1f}% | — |",
                    "",
                ])
            elif role_key == "tank":
                lines.extend([
                    "| Metric | This Raid | Avg | Change |",
                    "| --- | --- | --- | --- |",
                    f"| Damage Taken | {_fmt(m.get('total_damage_taken'))} | {_fmt(m.get('avg_damage_taken'))} | {_pct(m.get('total_damage_taken', 0), m.get('avg_damage_taken'))} |",
                    f"| Mitigation % | {m.get('mitigation_percent', 0):.1f}% | {m.get('avg_mitigation', 0):.1f}% | {_pct(m.get('mitigation_percent', 0), m.get('avg_mitigation'))} |",
                    "",
                ])
            else:
                lines.extend([
                    "| Metric | This Raid | Avg | Change |",
                    "| --- | --- | --- | --- |",
                    f"| Total Damage | {_fmt(m.get('total_damage'))} | {_fmt(m.get('avg_damage'))} | {_pct(m.get('total_damage', 0), m.get('avg_damage'))} |",
                    "",
                ])

            if p.get("spell_deltas"):
                lines.extend([
                    "**Spell Changes**",
                    "",
                    "| Spell | Casts | Avg | Delta |",
                    "| --- | --- | --- | --- |",
                ])
                for s in p["spell_deltas"][:10]:
                    d = s["cast_delta"]
                    delta_str = f"+{d:.0f}" if d > 0 else f"{d:.0f}" if d < 0 else "—"
                    lines.append(
                        f"| {s['spell_name']} | {s['this_casts']} | {s['avg_casts']:.1f} | {delta_str} |"
                    )
                lines.append("")

            if p.get("consumable_deltas"):
                lines.extend([
                    "**Consumable Changes**",
                    "",
                    "| Consumable | Count | Avg | Delta |",
                    "| --- | --- | --- | --- |",
                ])
                for c in p["consumable_deltas"][:10]:
                    d = c["delta"]
                    delta_str = f"+{d:.0f}" if d > 0.5 else f"{d:.0f}" if d < -0.5 else "—"
                    lines.append(
                        f"| {c['consumable_name']} | {c['this_count']} | {c['avg_count']:.1f} | {delta_str} |"
                    )
                lines.append("")

    return "\n".join(lines)


def export_cross_analysis(raid_stats: dict, historical: list[dict],
                          player_deltas: list[dict], size_label: str,
                          output_path: str | None = None) -> str:
    content = render_cross_analysis(raid_stats, historical, player_deltas, size_label)

    if not output_path:
        safe_title = "".join(
            c if c.isalnum() or c in " _-" else "_"
            for c in raid_stats.get("title", "report")
        ).strip().replace(" ", "_")
        from .. import paths
        output_path = os.path.join(str(paths.get_reports_dir()), f"{safe_title}_cross_analysis.md")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path


def _render_consumables(consumables: list[ConsumableUsage]) -> str:
    if not consumables:
        return ""

    lines = ["## Consumable Usage", ""]

    # Build player -> consumable -> count mapping
    player_data: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    all_consumable_names: set[str] = set()
    for c in consumables:
        if c.count > 0:
            player_data[c.player_name][c.consumable_name] += c.count
            all_consumable_names.add(c.consumable_name)

    if not all_consumable_names:
        return ""

    col_names = sorted(all_consumable_names)
    headers = ["Player"] + col_names
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")

    for player in sorted(player_data):
        cells = [player]
        cells.extend(
            str(player_data[player].get(c, 0)) if player_data[player].get(c, 0) > 0 else ""
            for c in col_names
        )
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    return "\n".join(lines)
