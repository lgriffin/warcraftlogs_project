"""
Raid pages: the desktop app's raid browser and raid analysis as JSON payloads every frontend can render.

The desktop app's Raids hub lists stored raids with a weekday filter, opens a raid's analysis in tabs (healers, tanks,
melee and ranged DPS, consumables, boss against trash, interrupts, cancelled casts, debuff and totem uptimes,
engineering, boss encounters and the composition) and shows each boss's history across raids. ``RaidPageService``
builds the same things from storage alone, with no Warcraft Logs call:

    ``index()``          one ``RaidSummary`` per stored guild raid, newest first, with its weekday
    ``page(report_id)``  a ``RaidPage``: the summary and every analysis section
    ``boss_history()``   ``BossHistory`` per boss, split by weekday so a frontend sums the days it shows

``to_dict()`` on each is the JSON shape the Toads Hub serves, documented in ``guides/raid_pages.md``. Values arrive
raw, so a frontend formats them; the weekday is 0 for Monday, as ``date.weekday()``. Bump ``RAID_PAGE_VERSION`` when
a field changes meaning.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

from wcl_core.config import configured_api_url
from wcl_core.game_version import RETAIL, game_version_for_url, host_for
from wcl_core.models import RaidAnalysis
from wcl_store import StorageError

from wcl_app.context import AppContext, ScopeSource, StorageFactory, resolve_scope

RAID_PAGE_VERSION = 1

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

ENGINEERING_ITEMS = frozenset(
    {
        "Super Sapper Charge",
        "Goblin Sapper Charge",
        "Adamantite Grenade",
        "Gnomish Flame Turret",
        "Fel Iron Bomb",
        "Bomb",
    }
)


# ── Analysis helpers (shared with the desktop app's raid view) ──


def classify_consumable_usage(analysis: RaidAnalysis) -> dict[str, dict[str, int]]:
    """Each consumable's uses split into boss and trash, by whether a use falls inside a boss encounter."""
    intervals = [(e.start_time, e.end_time) for e in analysis.encounters or []]
    by_name: dict[str, dict[str, int]] = defaultdict(lambda: {"boss": 0, "trash": 0})
    for cu in analysis.consumables or []:
        for ts in cu.timestamps:
            in_boss = any(s <= ts <= e for s, e in intervals)
            by_name[cu.consumable_name]["boss" if in_boss else "trash"] += 1
    return dict(by_name)


def compute_engineering_stats(analysis: RaidAnalysis) -> dict[str, dict[str, Any]]:
    """Casts, damage and users per engineering item, with the min, median and max of the users' damage per cast."""
    items: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"player_avgs": [], "total_casts": 0, "total_damage": 0, "users": 0}
    )
    for player in analysis.dps or []:
        for ability in player.abilities or []:
            if ability.spell_name not in ENGINEERING_ITEMS or ability.casts <= 0:
                continue
            entry = items[ability.spell_name]
            entry["player_avgs"].append(ability.total_amount / ability.casts)
            entry["total_casts"] += ability.casts
            entry["total_damage"] += ability.total_amount
            entry["users"] += 1
    result: dict[str, dict[str, Any]] = {}
    for name, data in items.items():
        avgs = sorted(data["player_avgs"])
        result[name] = {
            "total_casts": data["total_casts"],
            "total_damage": data["total_damage"],
            "users": data["users"],
            "min_avg": avgs[0],
            "median_avg": median(avgs),
            "max_avg": avgs[-1],
        }
    return result


# ── Payloads ──


@dataclass(frozen=True)
class RaidSummary:
    """One stored raid as a list row."""

    report_id: str
    title: str
    zone: str
    # "YYYY-MM-DD HH:MM:SS" as stored, the raid's local start time.
    raid_date: str
    # 0 is Monday; None when the stored date cannot be read.
    weekday: int | None
    size: int
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EncounterPlayer:
    name: str
    player_class: str
    role: str
    damage: int
    healing: int
    damage_taken: int
    active_percent: float


@dataclass(frozen=True)
class Encounter:
    encounter_id: int
    name: str
    duration_ms: int
    damage: int
    healing: int
    players: list[EncounterPlayer]


@dataclass(frozen=True)
class RaidPage:
    """A raid's analysis, section by section, as the desktop app's raid view shows it."""

    summary: RaidSummary
    duration_ms: int
    composition: dict[str, list[dict[str, str]]]
    healers: list[dict[str, Any]]
    tanks: list[dict[str, Any]]
    melee: list[dict[str, Any]]
    ranged: list[dict[str, Any]]
    # Consumable names in the order the pivot shows them, then one row per player with a count per name.
    consumable_names: list[str]
    consumables: list[dict[str, Any]]
    boss_vs_trash: list[dict[str, Any]]
    interrupts: list[dict[str, Any]]
    cancelled_casts: list[dict[str, Any]]
    debuff_uptimes: list[dict[str, Any]]
    totem_uptimes: list[dict[str, Any]]
    engineering: list[dict[str, Any]]
    encounters: list[Encounter]
    warnings: list[str] = field(default_factory=list)
    version: int = RAID_PAGE_VERSION

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["summary"] = self.summary.to_dict()
        return out


@dataclass
class BossPlayerTotals:
    name: str
    player_class: str
    role: str
    kills: int = 0
    damage: int = 0
    healing: int = 0
    damage_taken: int = 0


@dataclass
class BossDayTotals:
    """One boss's kills on one weekday: sums, so a frontend can add the days it shows and divide by kills."""

    kills: int = 0
    duration_ms: int = 0
    damage: int = 0
    healing: int = 0
    players: dict[str, BossPlayerTotals] = field(default_factory=dict)


@dataclass
class BossHistory:
    encounter_id: int
    name: str
    # Weekday (0 is Monday) to that day's totals.
    days: dict[int, BossDayTotals] = field(default_factory=dict)

    @property
    def kills(self) -> int:
        return sum(d.kills for d in self.days.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "encounter_id": self.encounter_id,
            "name": self.name,
            "days": {
                str(day): {
                    "kills": t.kills,
                    "duration_ms": t.duration_ms,
                    "damage": t.damage,
                    "healing": t.healing,
                    "players": [
                        asdict(p) for p in sorted(t.players.values(), key=lambda p: (p.name.casefold(), p.role))
                    ],
                }
                for day, t in sorted(self.days.items())
            },
        }


# ── Building ──


def weekday_of(raid_date: str | None) -> int | None:
    try:
        return datetime.fromisoformat(raid_date).weekday() if raid_date else None
    except ValueError:
        return None


def _summary(row: dict[str, Any], url: str) -> RaidSummary:
    raid_date = str(row.get("raid_date") or "")
    return RaidSummary(
        report_id=str(row["report_id"]),
        title=str(row.get("title") or ""),
        zone=str(row.get("zone") or ""),
        raid_date=raid_date,
        weekday=weekday_of(raid_date),
        size=int(row.get("raid_size") or 0),
        url=url,
    )


def _report_url(report_id: str, game_version: str | None) -> str:
    """The report on its site, as ``RaidMetadata.url``: a raid stored before the site was read uses the configured one."""
    version = game_version or game_version_for_url(configured_api_url())
    return f"{host_for(version) or host_for(RETAIL)}/reports/{report_id}"


def _dps(analysis: RaidAnalysis, role: str) -> list[dict[str, Any]]:
    return [
        {**_player(d.name, d.player_class), "damage": d.total_damage, "active_percent": round(d.active_time_percent, 1)}
        for d in sorted(analysis.dps, key=lambda d: -d.total_damage)
        if d.role == role
    ]


def _player(name: str, player_class: str) -> dict[str, str]:
    return {"name": name, "player_class": player_class}


def _consumables(analysis: RaidAnalysis) -> tuple[list[str], list[dict[str, Any]]]:
    totals: dict[str, int] = defaultdict(int)
    rows: dict[str, dict[str, Any]] = {}
    for cu in analysis.consumables or []:
        totals[cu.consumable_name] += cu.count
        row = rows.setdefault(cu.player_name, {"name": cu.player_name, "role": cu.player_role, "counts": {}})
        row["counts"][cu.consumable_name] = row["counts"].get(cu.consumable_name, 0) + cu.count
    names = sorted(totals, key=lambda n: (-totals[n], n))
    return names, sorted(rows.values(), key=lambda r: r["name"].casefold())


def _uptimes(auras: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {"spell_name": a.spell_name, "fight_name": a.fight_name, "uptime_percent": round(a.uptime_percent, 1)}
        for a in auras
    ]


def _encounters(analysis: RaidAnalysis) -> list[Encounter]:
    out = []
    for e in analysis.encounters or []:
        players = sorted(
            (
                EncounterPlayer(
                    name=p.name,
                    player_class=p.player_class,
                    role=p.role,
                    damage=p.total_damage,
                    healing=p.total_healing,
                    damage_taken=p.total_damage_taken,
                    active_percent=round(p.active_time_percent, 1),
                )
                for p in e.players
            ),
            key=lambda p: (-p.damage, p.name),
        )
        out.append(
            Encounter(
                encounter_id=e.encounter_id,
                name=e.name,
                duration_ms=e.duration_ms,
                damage=sum(p.damage for p in players),
                healing=sum(p.healing for p in players),
                players=players,
            )
        )
    return out


def build_page(analysis: RaidAnalysis, summary: RaidSummary) -> RaidPage:
    """A raid's analysis as its page. Pure: no storage, so the desktop app and the hub's worker share it."""
    meta = analysis.metadata
    comp = analysis.composition
    duration = max((meta.end_time or meta.start_time) - meta.start_time, 0)
    consumable_names, consumables = _consumables(analysis)
    split = classify_consumable_usage(analysis)
    return RaidPage(
        summary=summary,
        duration_ms=duration,
        composition={
            role: [_player(p.name, p.player_class) for p in players]
            for role, players in (
                ("tanks", comp.tanks),
                ("healers", comp.healers),
                ("melee", comp.melee),
                ("ranged", comp.ranged),
            )
        },
        healers=[
            {
                **_player(h.name, h.player_class),
                "healing": h.total_healing,
                "overhealing": h.total_overhealing,
                "overheal_percent": h.overheal_percent,
                "dispels": sum(d.casts for d in h.dispels),
                "active_percent": round(h.active_time_percent, 1),
            }
            for h in sorted(analysis.healers, key=lambda h: -h.total_healing)
        ],
        tanks=[
            {
                **_player(t.name, t.player_class),
                "damage_taken": t.total_damage_taken,
                "mitigated": t.total_mitigated,
                "mitigation_percent": t.mitigation_percent,
                "active_percent": round(t.active_time_percent, 1),
            }
            for t in sorted(analysis.tanks, key=lambda t: -t.total_damage_taken)
        ],
        melee=_dps(analysis, "melee"),
        ranged=_dps(analysis, "ranged"),
        consumable_names=consumable_names,
        consumables=consumables,
        boss_vs_trash=[{"name": n, **split[n]} for n in sorted(split, key=lambda n: (-sum(split[n].values()), n))],
        interrupts=[
            {**_player(i.player_name, i.player_class), "spell_name": i.spell_name, "count": i.count}
            for i in sorted(analysis.interrupts, key=lambda i: (-i.count, i.player_name))
        ],
        cancelled_casts=[
            {
                **_player(c.player_name, c.player_class),
                "total_casts": c.total_casts,
                "cancelled_casts": c.cancelled_casts,
                "cancel_rate": round(c.cancel_rate, 1),
                "spells": [
                    {
                        "spell_name": s.spell_name,
                        "total_casts": s.total_casts,
                        "cancelled_casts": s.cancelled_casts,
                        "cancel_rate": round(s.cancel_rate, 1),
                    }
                    for s in c.spell_details
                ],
            }
            for c in sorted(analysis.cancelled_casts, key=lambda c: (-c.cancelled_casts, c.player_name))
        ],
        debuff_uptimes=_uptimes(analysis.aura_uptimes),
        totem_uptimes=_uptimes(analysis.totem_uptimes),
        engineering=[{"name": name, **stats} for name, stats in sorted(compute_engineering_stats(analysis).items())],
        encounters=_encounters(analysis),
        warnings=list(analysis.warnings),
    )


def boss_history(pages: Iterable[RaidPage]) -> list[BossHistory]:
    """Every boss killed across the pages, with per-weekday totals for the raid and each player; most kills first."""
    bosses: dict[int, BossHistory] = {}
    for page in pages:
        day = page.summary.weekday
        if day is None:
            continue
        for e in page.encounters:
            boss = bosses.setdefault(e.encounter_id, BossHistory(e.encounter_id, e.name))
            totals = boss.days.setdefault(day, BossDayTotals())
            totals.kills += 1
            totals.duration_ms += e.duration_ms
            totals.damage += e.damage
            totals.healing += e.healing
            for p in e.players:
                # One row per character and role, as the desktop breakdown keeps a respec apart.
                mine = totals.players.setdefault(f"{p.name}|{p.role}", BossPlayerTotals(p.name, p.player_class, p.role))
                mine.kills += 1
                mine.damage += p.damage
                mine.healing += p.healing
                mine.damage_taken += p.damage_taken
    return sorted(bosses.values(), key=lambda b: (-b.kills, b.name))


def summary_of(analysis: RaidAnalysis) -> RaidSummary:
    """A raid's list row from its analysis, for a raid that is not (yet) read through ``index()``."""
    meta = analysis.metadata
    raid_date = meta.date.strftime("%Y-%m-%d %H:%M:%S")
    return RaidSummary(
        report_id=meta.report_id,
        title=meta.title,
        zone=meta.zone or "",
        raid_date=raid_date,
        weekday=weekday_of(raid_date),
        size=len(analysis.composition.all_players),
        url=_report_url(meta.report_id, meta.game_version),
    )


class RaidPageService:
    """Stored guild raids as list rows and pages, read through the repository only."""

    def __init__(self, storage: StorageFactory, scope: ScopeSource = None):
        self._storage = storage
        # A scope, or a callable giving the active profile's at read time; None lists every guild raid.
        self._scope = scope

    @classmethod
    def from_context(cls, ctx: AppContext) -> RaidPageService:
        return cls(ctx.repository, scope=lambda: ctx.scope)

    def _rows(self, limit: int) -> list[dict[str, Any]]:
        with self._storage() as db:
            return db.get_raids_by_source("guild", limit=limit, scope=resolve_scope(self._scope))

    def index(self, limit: int = 1000) -> list[RaidSummary]:
        """Every stored guild raid, newest first."""
        return [_summary(r, _report_url(str(r["report_id"]), r.get("game_version"))) for r in self._rows(limit)]

    def page(self, report_id: str, summary: RaidSummary | None = None) -> RaidPage | None:
        """The guild raid's page, or None when it is not a stored guild raid or cannot be read back."""
        try:
            with self._storage() as db:
                if db.get_raid_source(report_id) != "guild":
                    return None
                analysis = db.get_raid_analysis(report_id)
        except StorageError:
            return None
        if analysis is None:
            return None
        return build_page(analysis, summary or summary_of(analysis))
