"""
Unified analysis engine.

All analysis logic lives here, returning data model objects.
No printing — presentation is handled by renderers (console, markdown, GUI).
"""

import bisect
import contextlib
import json
import logging
import os
from collections import defaultdict

logger = logging.getLogger(__name__)

import requests

from .client import WarcraftLogsClient
from .models import (
    AuraBand,
    AuraUptime,
    BossEvent,
    CancelledCastCorrelation,
    CancelledCastDetail,
    CancelledCastSummary,
    ConsumableUsage,
    DispelUsage,
    DPSPerformance,
    EncounterPerformance,
    EncounterSummary,
    HealerPerformance,
    InterruptUsage,
    PlayerIdentity,
    RaidAnalysis,
    RaidComposition,
    ResourceUsage,
    SpellUsage,
    TankPerformance,
)
from .spell_manager import SpellBreakdown, get_spell_manager

_TEN_MAN_ZONES = {"Karazhan", "Zul'Aman"}


def analyze_raid(
    client: WarcraftLogsClient,
    report_id: str,
    healer_threshold: int = 40000,
    tank_min_taken: int = 150000,
    tank_min_mitigation: int = 40,
    healer_threshold_10: int = 400000,
    tank_min_taken_10: int = 300000,
) -> RaidAnalysis:
    """Run a full raid analysis and return structured results."""
    logger.info("analyze_raid: starting for report %s (API_URL=%s)", report_id, client.API_URL)

    metadata = client.get_report_metadata(report_id)
    logger.info("  metadata: title=%s zone=%s", metadata.title, metadata.zone)

    master_actors = client.get_master_data(report_id)
    logger.info("  master_actors: %d entries", len(master_actors) if master_actors else 0)

    if metadata.zone in _TEN_MAN_ZONES:
        healer_threshold = healer_threshold_10
        tank_min_taken = tank_min_taken_10

    composition = _identify_composition(
        client,
        report_id,
        master_actors,
        healer_threshold,
        tank_min_taken,
        tank_min_mitigation,
    )
    logger.info(
        "  composition: %d healers, %d tanks, %d melee, %d ranged",
        len(composition.healers),
        len(composition.tanks),
        len(composition.melee),
        len(composition.ranged),
    )

    all_warnings: list[str] = []

    healers, healer_warns = _analyze_healers(client, report_id, composition.healers)
    all_warnings.extend(healer_warns)
    logger.info("  healers analyzed: %d", len(healers))
    tanks, tank_warns = _analyze_tanks(client, report_id, composition.tanks)
    all_warnings.extend(tank_warns)
    logger.info("  tanks analyzed: %d", len(tanks))
    melee_dps, melee_warns = _analyze_dps(client, report_id, composition.melee, "melee")
    all_warnings.extend(melee_warns)
    ranged_dps, ranged_warns = _analyze_dps(client, report_id, composition.ranged, "ranged")
    all_warnings.extend(ranged_warns)
    logger.info("  dps analyzed: %d melee, %d ranged", len(melee_dps), len(ranged_dps))

    consumables, consume_warns = _analyze_consumables(client, report_id, composition)
    all_warnings.extend(consume_warns)

    interrupts, interrupt_warns = _analyze_interrupts(client, report_id, composition)
    all_warnings.extend(interrupt_warns)
    logger.info("  interrupts analyzed: %d entries", len(interrupts))

    try:
        encounters = _analyze_encounters(client, report_id, composition)
        logger.info("  encounters analyzed: %d", len(encounters))
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        logger.error("  encounter analysis failed: %s", e)
        encounters = []
        all_warnings.append(f"Encounter analysis failed: {e}")

    _apply_active_time(encounters, healers, tanks, melee_dps + ranged_dps)

    try:
        cancelled_casts, cc_warns = _analyze_cancelled_casts(client, report_id, composition)
        all_warnings.extend(cc_warns)
        logger.info("  cancelled casts analyzed: %d entries", len(cancelled_casts))
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        logger.error("  cancelled cast analysis failed: %s", e)
        cancelled_casts = []
        all_warnings.append(f"Cancelled cast analysis failed: {e}")

    if encounters:
        try:
            _correlate_cancelled_casts(client, report_id, cancelled_casts, encounters)
            logger.info("  cancelled cast correlations computed")
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("  cancelled cast correlation failed: %s", e)
            all_warnings.append(f"Cancelled cast correlation failed: {e}")

    try:
        aura_uptimes, aura_warns = _analyze_aura_uptimes(client, report_id, encounters)
        all_warnings.extend(aura_warns)
        logger.info("  aura uptimes analyzed: %d entries", len(aura_uptimes))
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        logger.error("  aura uptime analysis failed: %s", e)
        aura_uptimes = []
        all_warnings.append(f"Aura uptime analysis failed: {e}")

    try:
        totem_uptimes, totem_warns = _analyze_totem_uptimes(client, report_id, composition, encounters)
        all_warnings.extend(totem_warns)
        logger.info("  totem uptimes analyzed: %d entries", len(totem_uptimes))
    except (requests.RequestException, KeyError, TypeError, ValueError) as e:
        logger.error("  totem uptime analysis failed: %s", e)
        totem_uptimes = []
        all_warnings.append(f"Totem uptime analysis failed: {e}")

    if all_warnings:
        logger.warning("analyze_raid: completed with %d warnings", len(all_warnings))

    logger.info("analyze_raid: complete for %s", report_id)
    return RaidAnalysis(
        metadata=metadata,
        composition=composition,
        healers=healers,
        tanks=tanks,
        dps=melee_dps + ranged_dps,
        consumables=consumables,
        interrupts=interrupts,
        cancelled_casts=cancelled_casts,
        aura_uptimes=aura_uptimes,
        totem_uptimes=totem_uptimes,
        encounters=encounters,
        warnings=all_warnings,
    )


def _identify_composition(
    client: WarcraftLogsClient,
    report_id: str,
    master_actors: list[dict],
    healer_threshold: int,
    tank_min_taken: int,
    tank_min_mitigation: int,
) -> RaidComposition:
    """Dynamically identify roles for all players."""
    tanks = _identify_tanks(client, report_id, master_actors, tank_min_taken, tank_min_mitigation)
    tank_names = {t.name for t in tanks}

    healers = _identify_healers(client, report_id, master_actors, healer_threshold)
    healer_names = {h.name for h in healers}

    excluded = tank_names | healer_names
    always_ranged = {"Mage", "Warlock", "Hunter"}
    always_melee = {"Rogue"}
    # Hybrid classes need damage profile check to determine melee vs ranged
    hybrid_classes = {"Warrior", "Paladin", "Druid", "Shaman", "Priest"}

    melee = []
    ranged = []
    for actor in master_actors:
        name = actor["name"]
        if name in excluded:
            continue
        cls = actor["subType"]
        pid = PlayerIdentity(name=name, player_class=cls, source_id=actor["id"], role="")
        if cls in always_ranged:
            pid.role = "ranged"
            ranged.append(pid)
        elif cls in always_melee:
            pid.role = "melee"
            melee.append(pid)
        elif cls in hybrid_classes:
            role = _classify_hybrid_role(client, report_id, actor["id"], cls)
            pid.role = role
            if role == "ranged":
                ranged.append(pid)
            else:
                melee.append(pid)

    return RaidComposition(tanks=tanks, healers=healers, melee=melee, ranged=ranged)


# Auto-attack / melee swing ability IDs in WarcraftLogs
_MELEE_ABILITY_IDS = {1, -4, -32}

# Spells that are strong indicators of a ranged spec
_RANGED_SPEC_SPELLS = {
    # Shadow Priest
    "Shadow Bolt",
    "Mind Blast",
    "Mind Flay",
    "Shadow Word: Pain",
    "Vampiric Embrace",
    "Devouring Plague",
    "Shadow Word: Death",
    # Balance Druid
    "Wrath",
    "Starfire",
    "Moonfire",
    "Insect Swarm",
    "Hurricane",
    # Elemental Shaman
    "Lightning Bolt",
    "Chain Lightning",
    "Earth Shock",
    "Flame Shock",
    "Frost Shock",
    # Holy/Disc Priest doing damage (Smite)
    "Smite",
    "Holy Fire",
}


def _classify_hybrid_role(
    client: WarcraftLogsClient,
    report_id: str,
    source_id: int,
    player_class: str,
) -> str:
    """Determine whether a hybrid-class DPS player is melee or ranged.

    Examines the player's damage profile: if most damage comes from melee
    swings and instant strikes, they're melee; if from spells, they're ranged.
    """
    try:
        events = client.get_damage_done_data(report_id, source_id)
    except (requests.RequestException, KeyError):
        return "melee"

    melee_damage = 0
    spell_damage = 0

    for e in events:
        if e.get("type") != "damage":
            continue
        amount = e.get("amount", 0)
        ability_id = e.get("abilityGameID")
        if ability_id in _MELEE_ABILITY_IDS:
            melee_damage += amount
        else:
            spell_damage += amount

    total = melee_damage + spell_damage
    if total == 0:
        return "melee"

    melee_ratio = melee_damage / total

    # If more than 40% of damage is melee swings, classify as melee.
    # Ranged casters typically have <5% melee damage; Enhancement/Ret/Feral
    # have 40-70%+ from auto-attacks.
    if melee_ratio > 0.40:
        return "melee"
    return "ranged"


def _identify_tanks(
    client: WarcraftLogsClient,
    report_id: str,
    master_actors: list[dict],
    min_taken: int,
    min_mitigation: int,
) -> list[PlayerIdentity]:
    tanks = []
    for actor in master_actors:
        if actor["subType"] not in {"Warrior", "Druid", "Paladin"}:
            continue
        try:
            events = client.get_damage_taken_data(report_id, actor["id"])
            total_taken = sum(e.get("amount", 0) for e in events if e.get("type") == "damage")
            total_mitigated = sum(e.get("mitigated", 0) for e in events if e.get("type") == "damage")
            total_unmitigated = total_taken + total_mitigated
            if total_unmitigated == 0:
                continue
            percent = total_mitigated / total_unmitigated * 100
            if total_taken > min_taken and percent > min_mitigation:
                tanks.append(
                    PlayerIdentity(
                        name=actor["name"],
                        player_class=actor["subType"],
                        source_id=actor["id"],
                        role="tank",
                    )
                )
        except (requests.RequestException, KeyError, TypeError):
            pass
    return tanks


def _identify_healers(
    client: WarcraftLogsClient,
    report_id: str,
    master_actors: list[dict],
    threshold: int,
) -> list[PlayerIdentity]:
    healing_classes = {"Priest", "Paladin", "Druid", "Shaman"}
    healers = []
    for actor in master_actors:
        if actor["subType"] not in healing_classes:
            continue
        try:
            events = client.get_healing_data(report_id, actor["id"])
            total = sum(e.get("amount", 0) for e in events if e.get("type") == "heal")
            if total > threshold:
                healers.append(
                    PlayerIdentity(
                        name=actor["name"],
                        player_class=actor["subType"],
                        source_id=actor["id"],
                        role="healer",
                    )
                )
        except (requests.RequestException, KeyError, TypeError):
            pass
    return healers


_RESOURCE_SPELL_IDS = {
    28499: "Super Mana Potion",
    27869: "Dark Rune",
    16666: "Demonic Rune",
}


def _get_resources_from_events(
    client: WarcraftLogsClient,
    report_id: str,
    source_id: int,
) -> dict[str, int]:
    """Count consumable usage from cast events."""
    try:
        cast_events = client.get_cast_events_paginated(report_id, source_id)
        resources: dict[str, int] = defaultdict(int)
        for e in cast_events:
            if e.get("type") == "begincast":
                continue
            aid = e.get("abilityGameID")
            if aid in _RESOURCE_SPELL_IDS:
                resources[_RESOURCE_SPELL_IDS[aid]] += 1
        if resources.get("Demonic Rune") and not resources.get("Dark Rune"):
            resources["Dark Rune"] = resources.pop("Demonic Rune")
        elif resources.get("Demonic Rune"):
            resources["Dark Rune"] += resources.pop("Demonic Rune")
        return dict(resources)
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return {}


def _analyze_healers(
    client: WarcraftLogsClient,
    report_id: str,
    healer_ids: list[PlayerIdentity],
) -> tuple[list[HealerPerformance], list[str]]:
    results = []
    warnings = []
    alias_map = get_spell_manager().get_legacy_aliases()
    spell_mgr = get_spell_manager()

    for player in healer_ids:
        try:
            healing_events = client.get_healing_data(report_id, player.source_id)

            total_healing = sum(e.get("amount", 0) for e in healing_events)
            total_overhealing = sum(e.get("overheal", 0) for e in healing_events)

            spell_map, spell_casts, cast_entries = SpellBreakdown.get_spell_id_to_name_map(
                client, report_id, player.source_id
            )

            spell_totals = SpellBreakdown.calculate(healing_events)
            spells = []
            for spell_id, amount in sorted(spell_totals.items(), key=lambda x: x[1], reverse=True):
                if amount <= 0:
                    continue
                canonical_id = alias_map.get(spell_id, spell_id)
                name = str(spell_map.get(canonical_id, spell_mgr.get_spell_name(spell_id)))
                casts = spell_casts.get(canonical_id, 0)
                spells.append(SpellUsage(spell_id=canonical_id, spell_name=name, casts=casts, total_amount=amount))

            dispel_data = SpellBreakdown.calculate_dispels(cast_entries, player.player_class)
            dispels = [DispelUsage(spell_name=k, casts=v) for k, v in dispel_data.items() if v > 0]

            resource_data = SpellBreakdown.get_resources_used(cast_entries)
            if not any(resource_data.values()):
                resource_data = _get_resources_from_events(client, report_id, player.source_id)
            resources = [ResourceUsage(name=k, count=v) for k, v in resource_data.items()]

            fear_ward = SpellBreakdown.get_fear_ward_usage(cast_entries)
            fw_casts = fear_ward["casts"] if fear_ward else 0

            results.append(
                HealerPerformance(
                    name=player.name,
                    player_class=player.player_class,
                    source_id=player.source_id,
                    total_healing=total_healing,
                    total_overhealing=total_overhealing,
                    spells=spells,
                    dispels=dispels,
                    resources=resources,
                    fear_ward_casts=fw_casts,
                )
            )
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("Error processing healer %s: %s", player.name, e)
            warnings.append(f"Failed to analyze healer {player.name}: {e}")

    return results, warnings


def _analyze_tanks(
    client: WarcraftLogsClient,
    report_id: str,
    tank_ids: list[PlayerIdentity],
) -> tuple[list[TankPerformance], list[str]]:
    results = []
    warnings = []
    alias_map = get_spell_manager().get_legacy_aliases()

    spell_mgr = get_spell_manager()

    for player in tank_ids:
        try:
            taken_events = client.get_damage_taken_data(report_id, player.source_id)

            total_taken = sum(e.get("amount", 0) for e in taken_events if e.get("type") == "damage")
            total_mitigated = sum(e.get("mitigated", 0) for e in taken_events if e.get("type") == "damage")

            spell_map, _, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, player.source_id)

            taken_table = client.get_damage_taken_table(report_id, player.source_id)
            for entry in taken_table:
                eid = entry.get("guid")
                ename = entry.get("name")
                if eid and ename:
                    canonical = alias_map.get(eid, eid)
                    spell_map.setdefault(canonical, ename)

            done_table = client.get_damage_done_table(report_id, player.source_id)
            for entry in done_table:
                eid = entry.get("guid")
                ename = entry.get("name")
                if eid and ename:
                    canonical = alias_map.get(eid, eid)
                    spell_map.setdefault(canonical, ename)

            taken_counts: dict[int, int] = defaultdict(int)
            for e in taken_events:
                if e.get("type") == "damage":
                    sid = e.get("abilityGameID")
                    taken_counts[alias_map.get(sid, sid)] += 1

            taken_breakdown = [
                SpellUsage(
                    spell_id=sid,
                    spell_name=str(spell_map.get(sid, spell_mgr.get_spell_name(sid))),
                    casts=count,
                )
                for sid, count in sorted(taken_counts.items(), key=lambda x: -x[1])
            ]

            done_events = client.get_damage_done_data(report_id, player.source_id)
            done_counts: dict[int, int] = defaultdict(int)
            for e in done_events:
                if e.get("type") == "damage":
                    sid = e.get("abilityGameID")
                    done_counts[alias_map.get(sid, sid)] += 1

            abilities_used = [
                SpellUsage(
                    spell_id=sid,
                    spell_name=str(spell_map.get(sid, spell_mgr.get_spell_name(sid))),
                    casts=count,
                )
                for sid, count in sorted(done_counts.items(), key=lambda x: -x[1])
            ]

            results.append(
                TankPerformance(
                    name=player.name,
                    player_class=player.player_class,
                    source_id=player.source_id,
                    total_damage_taken=total_taken,
                    total_mitigated=total_mitigated,
                    damage_taken_breakdown=taken_breakdown,
                    abilities_used=abilities_used,
                )
            )
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("Error processing tank %s: %s", player.name, e)
            warnings.append(f"Failed to analyze tank {player.name}: {e}")

    return results, warnings


def _analyze_dps(
    client: WarcraftLogsClient,
    report_id: str,
    player_ids: list[PlayerIdentity],
    role: str,
) -> tuple[list[DPSPerformance], list[str]]:
    results = []
    warnings = []
    alias_map = get_spell_manager().get_legacy_aliases()

    spell_mgr = get_spell_manager()

    for player in player_ids:
        try:
            events = client.get_damage_done_data(report_id, player.source_id)
            spell_map, spell_casts, _ = SpellBreakdown.get_spell_id_to_name_map(client, report_id, player.source_id)

            done_table = client.get_damage_done_table(report_id, player.source_id)
            table_hits: dict[int, int] = {}
            for entry in done_table:
                eid = entry.get("guid")
                ename = entry.get("name")
                if eid is not None and ename:
                    canonical = alias_map.get(eid, eid)
                    spell_map.setdefault(canonical, ename)
                    hits = entry.get("hitCount", 0) + entry.get("tickCount", 0)
                    if hits:
                        table_hits[canonical] = table_hits.get(canonical, 0) + hits

            total_damage = 0
            damage_by_ability: dict[int, int] = defaultdict(int)
            for e in events:
                if e.get("type") == "damage":
                    amount = e.get("amount", 0)
                    sid = e.get("abilityGameID")
                    canonical = alias_map.get(sid, sid)
                    total_damage += amount
                    damage_by_ability[canonical] += amount

            casts_by_id: dict[int, int] = defaultdict(int)
            for sid, count in spell_casts.items():
                canonical = alias_map.get(sid, sid)
                casts_by_id[canonical] += count

            for sid in damage_by_ability:
                if not casts_by_id.get(sid) and table_hits.get(sid):
                    casts_by_id[sid] = table_hits[sid]

            abilities = [
                SpellUsage(
                    spell_id=sid,
                    spell_name=str(spell_map.get(sid, spell_mgr.get_spell_name(sid))),
                    casts=casts_by_id.get(sid, 0),
                    total_amount=dmg,
                )
                for sid, dmg in sorted(damage_by_ability.items(), key=lambda x: -x[1])
            ]

            results.append(
                DPSPerformance(
                    name=player.name,
                    player_class=player.player_class,
                    source_id=player.source_id,
                    role=role,
                    total_damage=total_damage,
                    abilities=abilities,
                )
            )
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("Error processing %s %s: %s", role, player.name, e)
            warnings.append(f"Failed to analyze {role} {player.name}: {e}")

    return results, warnings


def _load_consumes_config() -> dict:
    from . import paths

    config_path = str(paths.get_consumes_config_path())
    if not os.path.exists(config_path):
        return {"buff_consumables": {}, "cast_consumables": {}}
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def _analyze_consumables(
    client: WarcraftLogsClient,
    report_id: str,
    composition: RaidComposition,
) -> tuple[list[ConsumableUsage], list[str]]:
    config = _load_consumes_config()

    buff_ids: dict[int, str] = {int(sid): name for sid, name in config.get("buff_consumables", {}).items()}
    cast_ids: dict[int, str] = {int(sid): name for sid, name in config.get("cast_consumables", {}).items()}

    results: list[ConsumableUsage] = []
    warnings: list[str] = []

    for player in composition.all_players:
        try:
            table_data = client.get_buffs_table(report_id, player.source_id)
            if isinstance(table_data, str):
                table_data = json.loads(table_data)

            auras = table_data.get("data", {}).get("auras", [])
            if not auras:
                auras = table_data.get("auras", [])
            for aura in auras:
                ability_id = aura.get("guid")
                if ability_id in buff_ids:
                    count = aura.get("totalUses", 0)
                    if count > 0:
                        bands = aura.get("bands", [])
                        timestamps = sorted(b.get("startTime", 0) for b in bands)
                        results.append(
                            ConsumableUsage(
                                player_name=player.name,
                                player_role=player.role,
                                report_id=report_id,
                                consumable_name=buff_ids[ability_id],
                                count=count,
                                timestamps=timestamps,
                            )
                        )
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("Error analyzing buff consumables for %s: %s", player.name, e)
            warnings.append(f"Failed to analyze consumables for {player.name}: {e}")

        try:
            cast_events = client.get_cast_events_paginated(report_id, player.source_id)
            cast_data: dict[int, list[int]] = defaultdict(list)
            for e in cast_events:
                if e.get("type") == "begincast":
                    continue
                aid = e.get("abilityGameID")
                if aid in cast_ids:
                    ts = e.get("timestamp", 0)
                    cast_data[aid].append(ts)

            for spell_id, timestamps in cast_data.items():
                results.append(
                    ConsumableUsage(
                        player_name=player.name,
                        player_role=player.role,
                        report_id=report_id,
                        consumable_name=cast_ids[spell_id],
                        count=len(timestamps),
                        timestamps=sorted(timestamps),
                    )
                )
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("Error analyzing cast consumables for %s: %s", player.name, e)
            warnings.append(f"Failed to analyze consumables for {player.name}: {e}")

    return results, warnings


def _load_interrupt_config() -> dict[int, str]:
    from . import paths

    config_path = str(paths.get_interrupt_config_path())
    if not os.path.exists(config_path):
        return {}
    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)
    return {int(sid): name for sid, name in raw.items()}


def _analyze_interrupts(
    client: WarcraftLogsClient,
    report_id: str,
    composition: RaidComposition,
) -> tuple[list[InterruptUsage], list[str]]:
    interrupt_ids = _load_interrupt_config()
    if not interrupt_ids:
        return [], []

    results: list[InterruptUsage] = []
    warnings: list[str] = []

    for player in composition.all_players:
        try:
            cast_events = client.get_cast_events_paginated(report_id, player.source_id)
            spell_data: dict[int, list[int]] = defaultdict(list)
            for e in cast_events:
                if e.get("type") == "begincast":
                    continue
                aid = e.get("abilityGameID")
                if aid in interrupt_ids:
                    spell_data[aid].append(e.get("timestamp", 0))

            for spell_id, timestamps in spell_data.items():
                results.append(
                    InterruptUsage(
                        player_name=player.name,
                        player_class=player.player_class,
                        source_id=player.source_id,
                        spell_id=spell_id,
                        spell_name=interrupt_ids[spell_id],
                        count=len(timestamps),
                        timestamps=sorted(timestamps),
                    )
                )
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("Error analyzing interrupts for %s: %s", player.name, e)
            warnings.append(f"Failed to analyze interrupts for {player.name}: {e}")

    return results, warnings


def _analyze_cancelled_casts(
    client: WarcraftLogsClient,
    report_id: str,
    composition: RaidComposition,
) -> tuple[list[CancelledCastSummary], list[str]]:
    results: list[CancelledCastSummary] = []
    warnings: list[str] = []
    spell_mgr = get_spell_manager()

    for player in composition.all_players:
        try:
            cast_events = client.get_cast_events_paginated(report_id, player.source_id)

            spell_names: dict[int, str] = {}
            try:
                cast_table = client.get_cast_table(report_id, player.source_id)
                for entry in cast_table:
                    gid = entry.get("guid")
                    name = entry.get("name")
                    if gid and name:
                        spell_names[gid] = name
            except (requests.RequestException, KeyError, TypeError, ValueError):
                pass

            pending: dict[int, int] = {}
            completed = 0
            cancelled = 0
            spell_completed: dict[int, int] = {}
            spell_cancelled: dict[int, int] = {}
            spell_cancel_timestamps: dict[int, list[int]] = {}

            for e in cast_events:
                etype = e.get("type")
                aid = e.get("abilityGameID")
                if not aid:
                    continue

                if etype == "begincast":
                    if aid in pending:
                        cancelled += 1
                        spell_cancelled[aid] = spell_cancelled.get(aid, 0) + 1
                        spell_cancel_timestamps.setdefault(aid, []).append(pending[aid])
                    pending[aid] = e.get("timestamp", 0)
                elif etype == "cast":
                    if aid in pending:
                        completed += 1
                        spell_completed[aid] = spell_completed.get(aid, 0) + 1
                        del pending[aid]

            for aid, ts in pending.items():
                cancelled += 1
                spell_cancelled[aid] = spell_cancelled.get(aid, 0) + 1
                spell_cancel_timestamps.setdefault(aid, []).append(ts)

            total = completed + cancelled
            if total == 0:
                continue

            cancel_rate = round(cancelled / total * 100, 1)

            details = []
            for sid in set(spell_completed) | set(spell_cancelled):
                sc = spell_completed.get(sid, 0)
                sn = spell_cancelled.get(sid, 0)
                st = sc + sn
                details.append(
                    CancelledCastDetail(
                        spell_id=sid,
                        spell_name=spell_names.get(sid, spell_mgr.get_spell_name(sid)),
                        total_casts=sc,
                        cancelled_casts=sn,
                        cancel_rate=round(sn / st * 100, 1) if st else 0.0,
                        timestamps=sorted(spell_cancel_timestamps.get(sid, [])),
                    )
                )
            details.sort(key=lambda d: d.cancelled_casts, reverse=True)

            results.append(
                CancelledCastSummary(
                    player_name=player.name,
                    player_class=player.player_class,
                    source_id=player.source_id,
                    total_casts=completed,
                    cancelled_casts=cancelled,
                    cancel_rate=cancel_rate,
                    spell_details=details,
                )
            )
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("Error analyzing cancelled casts for %s: %s", player.name, e)
            warnings.append(f"Failed to analyze cancelled casts for {player.name}: {e}")

    return results, warnings


_CORRELATION_WINDOW_MS = 3000


def _correlate_cancelled_casts(
    client: WarcraftLogsClient,
    report_id: str,
    cancelled_casts: list[CancelledCastSummary],
    encounters: list[EncounterSummary],
) -> None:
    actor_names: dict[int, str] = {}
    try:
        all_actors = client.get_all_actors(report_id)
        actor_names = {a["id"]: a["name"] for a in all_actors if "id" in a and "name" in a}
    except (requests.RequestException, KeyError, TypeError, ValueError):
        pass

    for enc in encounters:
        spell_names: dict[int, str] = {}
        with contextlib.suppress(requests.RequestException, KeyError, TypeError, ValueError):
            spell_names = client.get_enemy_ability_names(report_id, enc.start_time, enc.end_time)

        try:
            enemy_casts = client.get_enemy_cast_events(report_id, enc.start_time, enc.end_time)
        except (requests.RequestException, KeyError, TypeError, ValueError):
            enemy_casts = []
        try:
            dmg_events = client.get_raid_damage_taken_events(report_id, enc.start_time, enc.end_time)
        except (requests.RequestException, KeyError, TypeError, ValueError):
            dmg_events = []

        def _ability_name(aid: int, _names: dict[int, str] = spell_names) -> str:
            return _names.get(aid, f"(ID {aid})")

        boss_events: list[BossEvent] = []

        for e in enemy_casts:
            ts = e.get("timestamp", 0)
            aid = e.get("abilityGameID", 0)
            src_id = e.get("sourceID", 0)
            boss_events.append(
                BossEvent(
                    timestamp=ts,
                    event_type="boss_cast",
                    ability_name=_ability_name(aid),
                    ability_id=aid,
                    source_name=actor_names.get(src_id, "Boss"),
                )
            )

        seen_dmg: set[tuple[int, int]] = set()
        for e in dmg_events:
            ts = e.get("timestamp", 0)
            aid = e.get("abilityGameID", 0)
            key = (ts, aid)
            if key in seen_dmg:
                continue
            seen_dmg.add(key)
            src_id = e.get("sourceID", 0)
            boss_events.append(
                BossEvent(
                    timestamp=ts,
                    event_type="damage",
                    ability_name=_ability_name(aid),
                    ability_id=aid,
                    source_name=actor_names.get(src_id, "Boss"),
                )
            )

        boss_events.append(
            BossEvent(
                timestamp=enc.end_time,
                event_type="boss_death",
                ability_name="Boss Died",
                ability_id=0,
                source_name=enc.name,
            )
        )

        boss_events.sort(key=lambda b: b.timestamp)
        enc.boss_events = boss_events
        boss_timestamps = [b.timestamp for b in boss_events]

        for cc in cancelled_casts:
            for detail in cc.spell_details:
                for cancel_ts in detail.timestamps:
                    if cancel_ts < enc.start_time or cancel_ts > enc.end_time:
                        continue

                    lo = bisect.bisect_left(boss_timestamps, cancel_ts - _CORRELATION_WINDOW_MS)
                    hi = bisect.bisect_right(boss_timestamps, cancel_ts + _CORRELATION_WINDOW_MS)

                    nearby = []
                    for i in range(lo, hi):
                        be = boss_events[i]
                        nearby.append(
                            BossEvent(
                                timestamp=be.timestamp,
                                event_type=be.event_type,
                                ability_name=be.ability_name,
                                ability_id=be.ability_id,
                                source_name=be.source_name,
                                offset_ms=be.timestamp - cancel_ts,
                            )
                        )

                    if nearby:
                        detail.correlations.append(
                            CancelledCastCorrelation(
                                cancel_timestamp=cancel_ts,
                                nearby_events=nearby,
                            )
                        )


def _load_debuff_config() -> dict[int, str]:
    from . import paths

    config_path = str(paths.get_debuff_config_path())
    if not os.path.exists(config_path):
        return {}
    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)
    boss_debuffs = raw.get("boss_debuffs", {})
    return {int(sid): name for sid, name in boss_debuffs.items()}


def _analyze_aura_uptimes(
    client: WarcraftLogsClient,
    report_id: str,
    encounters: list[EncounterSummary],
) -> tuple[list[AuraUptime], list[str]]:
    debuff_ids = _load_debuff_config()
    if not debuff_ids:
        return [], []

    results: list[AuraUptime] = []
    warnings: list[str] = []

    for enc in encounters:
        try:
            table_data = client.get_debuffs_table(report_id, enc.start_time, enc.end_time)
            if isinstance(table_data, str):
                table_data = json.loads(table_data)

            auras = table_data.get("data", {}).get("auras", [])
            if not auras:
                auras = table_data.get("auras", [])

            fight_duration = enc.end_time - enc.start_time
            if fight_duration <= 0:
                continue

            for aura in auras:
                ability_id = aura.get("guid")
                if ability_id not in debuff_ids:
                    continue

                raw_bands = aura.get("bands", [])
                bands = []
                total_uptime = 0
                for b in raw_bands:
                    s = b.get("startTime", enc.start_time)
                    e = b.get("endTime", enc.end_time)
                    s = max(s, enc.start_time)
                    e = min(e, enc.end_time)
                    if e > s:
                        bands.append(AuraBand(start_time=s, end_time=e))
                        total_uptime += e - s

                uptime_pct = round(total_uptime / fight_duration * 100, 1)

                results.append(
                    AuraUptime(
                        spell_id=ability_id,
                        spell_name=debuff_ids[ability_id],
                        fight_name=enc.name,
                        fight_start=enc.start_time,
                        fight_end=enc.end_time,
                        uptime_percent=uptime_pct,
                        bands=bands,
                    )
                )
        except (requests.RequestException, KeyError, TypeError, ValueError) as e:
            logger.error("Error analyzing debuff uptimes for %s: %s", enc.name, e)
            warnings.append(f"Failed to analyze debuff uptimes for {enc.name}: {e}")

    return results, warnings


def _load_totem_config() -> dict[int, dict]:
    from . import paths

    config_path = str(paths.get_totem_config_path())
    if not os.path.exists(config_path):
        return {}
    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)
    totems = raw.get("totems", {})
    return {int(sid): info for sid, info in totems.items()}


def _merge_bands(bands: list[AuraBand]) -> list[AuraBand]:
    if not bands:
        return []
    sorted_bands = sorted(bands, key=lambda b: b.start_time)
    merged = [AuraBand(start_time=sorted_bands[0].start_time, end_time=sorted_bands[0].end_time)]
    for b in sorted_bands[1:]:
        if b.start_time <= merged[-1].end_time:
            merged[-1] = AuraBand(start_time=merged[-1].start_time, end_time=max(merged[-1].end_time, b.end_time))
        else:
            merged.append(AuraBand(start_time=b.start_time, end_time=b.end_time))
    return merged


def _analyze_totem_uptimes(
    client: WarcraftLogsClient,
    report_id: str,
    composition: RaidComposition,
    encounters: list[EncounterSummary],
) -> tuple[list[AuraUptime], list[str]]:
    totem_config = _load_totem_config()
    if not totem_config:
        return [], []

    shamans = [p for p in composition.all_players if p.player_class == "Shaman"]
    if not shamans:
        return [], []

    results: list[AuraUptime] = []
    warnings: list[str] = []

    shaman_casts: dict[int, list[dict]] = {}
    for shaman in shamans:
        try:
            casts = client.get_cast_events_paginated(report_id, shaman.source_id)
            shaman_casts[shaman.source_id] = [
                c for c in casts if c.get("type") == "cast" and c.get("abilityGameID") in totem_config
            ]
        except requests.RequestException as e:
            warnings.append(f"Failed to get casts for {shaman.name}: {e}")

    for enc in encounters:
        fight_duration = enc.end_time - enc.start_time
        if fight_duration <= 0:
            continue

        totem_bands: dict[int, list[AuraBand]] = {}

        for casts in shaman_casts.values():
            for cast in casts:
                ts = cast.get("timestamp", 0)
                spell_id = cast["abilityGameID"]
                duration_s = totem_config[spell_id].get("duration", 120)
                totem_expires = ts + duration_s * 1000
                if totem_expires <= enc.start_time or ts >= enc.end_time:
                    continue
                band_end = min(totem_expires, enc.end_time)
                band_start = max(ts, enc.start_time)
                if band_end > band_start:
                    totem_bands.setdefault(spell_id, []).append(AuraBand(start_time=band_start, end_time=band_end))

        for spell_id, raw_bands in totem_bands.items():
            merged = _merge_bands(raw_bands)
            total_uptime = sum(b.end_time - b.start_time for b in merged)
            uptime_pct = round(total_uptime / fight_duration * 100, 1)

            results.append(
                AuraUptime(
                    spell_id=spell_id,
                    spell_name=totem_config[spell_id]["name"],
                    fight_name=enc.name,
                    fight_start=enc.start_time,
                    fight_end=enc.end_time,
                    uptime_percent=uptime_pct,
                    bands=merged,
                )
            )

    return results, warnings


def _analyze_encounters(
    client: WarcraftLogsClient,
    report_id: str,
    composition: RaidComposition,
) -> list[EncounterSummary]:
    """Analyze per-boss-kill performance using time-windowed table queries."""
    fights = client.get_fights(report_id)
    boss_kills = [f for f in fights if f.get("encounterID", 0) > 0 and f.get("kill")]
    if not boss_kills:
        return []

    role_lookup = {p.name: p for p in composition.all_players}

    results = []
    for fight in boss_kills:
        start = fight["startTime"]
        end = fight["endTime"]

        try:
            damage_entries = client.get_encounter_table(report_id, start, end, "DamageDone")
            healing_entries = client.get_encounter_table(report_id, start, end, "Healing")
            taken_entries = client.get_encounter_table(report_id, start, end, "DamageTaken")
        except (requests.RequestException, KeyError, TypeError) as e:
            logger.error("Error fetching encounter data for %s: %s", fight["name"], e)
            continue

        fight_duration = end - start
        players_map: dict[str, dict] = {}
        for entry in damage_entries:
            name = entry.get("name", "")
            if not name or entry.get("type") == "Pet":
                continue
            players_map.setdefault(name, {"damage": 0, "healing": 0, "taken": 0, "active_time": 0})
            players_map[name]["damage"] += entry.get("total", 0)
            active = entry.get("activeTime", 0)
            if active > players_map[name]["active_time"]:
                players_map[name]["active_time"] = active

        for entry in healing_entries:
            name = entry.get("name", "")
            if not name or entry.get("type") == "Pet":
                continue
            players_map.setdefault(name, {"damage": 0, "healing": 0, "taken": 0, "active_time": 0})
            players_map[name]["healing"] += entry.get("total", 0)
            active = entry.get("activeTime", 0)
            if active > players_map[name]["active_time"]:
                players_map[name]["active_time"] = active

        for entry in taken_entries:
            name = entry.get("name", "")
            if not name or entry.get("type") == "Pet":
                continue
            players_map.setdefault(name, {"damage": 0, "healing": 0, "taken": 0, "active_time": 0})
            players_map[name]["taken"] += entry.get("total", 0)

        encounter_players = []
        for name, totals in players_map.items():
            player = role_lookup.get(name)
            at_pct = 0.0
            if fight_duration > 0 and totals["active_time"] > 0:
                at_pct = min(100.0, round(totals["active_time"] / fight_duration * 100, 1))
            encounter_players.append(
                EncounterPerformance(
                    name=name,
                    player_class=player.player_class if player else "Unknown",
                    source_id=player.source_id if player else 0,
                    role=player.role if player else "unknown",
                    total_damage=totals["damage"],
                    total_healing=totals["healing"],
                    total_damage_taken=totals["taken"],
                    active_time_percent=at_pct,
                )
            )

        encounter_players.sort(key=lambda p: p.total_damage, reverse=True)

        results.append(
            EncounterSummary(
                encounter_id=fight["encounterID"],
                name=fight["name"],
                start_time=start,
                end_time=end,
                duration_ms=end - start,
                players=encounter_players,
            )
        )

    return results


def _apply_active_time(encounters, healers, tanks, dps):
    """Average per-encounter active time and store on each player's raid performance."""
    player_times: dict[str, list[float]] = {}
    for enc in encounters:
        for p in enc.players:
            if p.active_time_percent > 0:
                player_times.setdefault(p.name, []).append(p.active_time_percent)

    for performer_list in [healers, tanks, dps]:
        for perf in performer_list:
            times = player_times.get(perf.name)
            if times:
                perf.active_time_percent = round(sum(times) / len(times), 1)
