"""
Reference comparison: import another guild's raid as a reference and compare one of our raids against it.

A reference report usually belongs to a guild we have no access to through the client-credentials key, so importing
one needs the user-scoped Warcraft Logs login (``AppContext.user_client``). Without it ``import_reference`` raises
``ReferenceAuthRequired``. Stored references are kept apart from guild raids (``source = "reference"``), so they never
count towards guild stats.

``ReferenceService.compare`` returns a ``ReferenceComparison``; ``to_dict()`` is the JSON shape every frontend
renders (the desktop's Head to Head tab and the Toads Hub page). Numbers arrive raw and formatted, so a frontend
never formats them itself. When our raid killed bosses the reference did not, consumables and encounters are scoped
to the window of the shared bosses so the two sides cover the same fights; totals still cover the whole raid.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from wcl_core.models import EncounterSummary, RaidAnalysis

from wcl_app.context import AppContext, ProgressCallback
from wcl_app.player_page import parse_report_code
from wcl_app.raids import RaidService

REFERENCE = "reference"
GUILD = "guild"
COMPARISON_SCHEMA_VERSION = 1
MAX_LABEL_LENGTH = 80


class ReferenceRequestError(ValueError):
    """A reference request the rules refuse: a bad code, a raid of the wrong kind, or one that is not stored."""


@dataclass(frozen=True)
class StoredRaid:
    """A stored raid as the pickers list it."""

    report_id: str
    title: str
    raid_date: str
    zone: str | None = None
    raid_size: int | None = None
    label: str | None = None
    owner: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> StoredRaid:
        return cls(
            report_id=row["report_id"],
            title=row.get("title") or "",
            raid_date=row.get("raid_date") or "",
            zone=row.get("zone"),
            raid_size=row.get("raid_size"),
            label=row.get("label"),
            owner=row.get("owner"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RaidSide:
    """What one side of a comparison is."""

    report_id: str
    title: str
    raid_date: str
    zone: str | None
    raid_size: int
    duration_ms: int


@dataclass(frozen=True)
class Metric:
    """One number for both sides. ``delta_percent`` is ours against the reference; ``better`` says whether that
    is good (None when either side is missing or the reference is zero)."""

    key: str
    label: str
    guild: float | None
    reference: float | None
    guild_display: str
    reference_display: str
    delta_percent: float | None
    higher_is_better: bool
    better: bool | None


@dataclass(frozen=True)
class ClassRow:
    player_class: str
    role: str
    # The role's own number: healing for healers, mitigation % for tanks, damage for DPS.
    metric: str
    guild_count: int
    guild_average: float | None
    reference_count: int
    reference_average: float | None
    delta_percent: float | None


@dataclass(frozen=True)
class ConsumableRow:
    name: str
    guild_uses: int
    guild_users: int
    reference_uses: int
    reference_users: int


@dataclass(frozen=True)
class EncounterRow:
    name: str
    guild_duration_ms: int
    reference_duration_ms: int
    guild_damage: int
    reference_damage: int
    guild_healing: int
    reference_healing: int
    duration_delta_percent: float | None


@dataclass(frozen=True)
class Scope:
    """Whether consumables and encounters were cut to the shared bosses, and which of our bosses fell outside."""

    scoped: bool
    shared_encounters: int
    guild_extra_encounters: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReferenceComparison:
    guild: RaidSide
    reference: RaidSide
    scope: Scope
    overview: list[Metric]
    composition: list[Metric]
    classes: list[ClassRow]
    consumables: list[ConsumableRow]
    encounters: list[EncounterRow]
    version: int = COMPARISON_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Pure comparison helpers (also used by the desktop's Head to Head charts) ──


def delta_percent(guild: float | None, reference: float | None) -> float | None:
    """Ours against the reference, in percent; None when either is missing or the reference is zero."""
    if guild is None or reference is None or reference == 0:
        return None
    return round((guild - reference) / abs(reference) * 100, 1)


def compact(n: float) -> str:
    """1234567 -> "1.23M", 45600 -> "45.6k"."""
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{n:,.0f}"


def duration(ms: float) -> str:
    seconds = int(ms // 1000)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _percent(n: float) -> str:
    return f"{n:.1f}%"


def _plain(n: float) -> str:
    return f"{n:,.0f}"


def _metric(
    key: str,
    label: str,
    guild: float | None,
    reference: float | None,
    fmt: Callable[[float], str] = compact,
    *,
    higher_is_better: bool = True,
) -> Metric:
    delta = delta_percent(guild, reference)
    better = None if delta is None or delta == 0 else (delta > 0) == higher_is_better
    return Metric(
        key=key,
        label=label,
        guild=guild,
        reference=reference,
        guild_display="—" if guild is None else fmt(guild),
        reference_display="—" if reference is None else fmt(reference),
        delta_percent=delta,
        higher_is_better=higher_is_better,
        better=better,
    )


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def raid_duration_ms(analysis: RaidAnalysis) -> int:
    end = analysis.metadata.end_time
    return max(0, end - analysis.metadata.start_time) if end else 0


def overheal_percent(analysis: RaidAnalysis) -> float | None:
    healing = sum(h.total_healing for h in analysis.healers)
    over = sum(h.total_overhealing for h in analysis.healers)
    return round(over / (healing + over) * 100, 1) if healing + over else None


def class_performance(analysis: RaidAnalysis) -> list[dict[str, Any]]:
    """Per (class, role): how many players and the average of the role's own number, sorted by class then role."""
    by_class_role: dict[tuple[str, str], list[float]] = defaultdict(list)
    for h in analysis.healers:
        by_class_role[(h.player_class, "healer")].append(h.total_healing)
    for t in analysis.tanks:
        by_class_role[(t.player_class, "tank")].append(t.mitigation_percent)
    for d in analysis.dps:
        by_class_role[(d.player_class, d.role)].append(d.total_damage)
    return [
        {"class": cls, "role": role, "count": len(values), "avg_metric": sum(values) / len(values)}
        for (cls, role), values in sorted(by_class_role.items())
    ]


def consumable_summary(analysis: RaidAnalysis) -> dict[str, dict[str, int]]:
    """``{consumable: {"total_uses", "unique_users"}}``."""
    users: dict[str, set[str]] = defaultdict(set)
    totals: dict[str, int] = defaultdict(int)
    for cu in analysis.consumables:
        users[cu.consumable_name].add(cu.player_name)
        totals[cu.consumable_name] += cu.count
    return {name: {"total_uses": totals[name], "unique_users": len(users[name])} for name in totals}


_EncounterData = dict[str, Any]


def _encounter_data(
    encounters: Iterable[EncounterSummary],
) -> tuple[dict[int, _EncounterData], dict[str, _EncounterData]]:
    by_id: dict[int, _EncounterData] = {}
    by_name: dict[str, _EncounterData] = {}
    for e in encounters:
        data = {
            "name": e.name,
            "duration_ms": e.duration_ms,
            "total_damage": sum(p.total_damage for p in e.players),
            "total_healing": sum(p.total_healing for p in e.players),
        }
        by_id[e.encounter_id] = data
        by_name[e.name] = data
    return by_id, by_name


def match_encounters(guild: RaidAnalysis, reference: RaidAnalysis) -> list[dict[str, Any]]:
    """Bosses both raids killed, matched by encounter id and then by name: ``{"name", "guild", "ref"}``."""
    guild_by_id, guild_by_name = _encounter_data(guild.encounters)
    ref_by_id, ref_by_name = _encounter_data(reference.encounters)

    rows = []
    matched: set[str] = set()
    for eid in sorted(set(guild_by_id) & set(ref_by_id)):
        rows.append({"name": guild_by_id[eid]["name"], "guild": guild_by_id[eid], "ref": ref_by_id[eid]})
        matched.add(guild_by_id[eid]["name"])
    for name in sorted(set(guild_by_name) & set(ref_by_name)):
        if name not in matched:
            rows.append({"name": name, "guild": guild_by_name[name], "ref": ref_by_name[name]})
    return rows


def shared_encounter_window(guild: RaidAnalysis, reference: RaidAnalysis) -> dict[str, Any] | None:
    """Our bosses the reference did not kill, and the time window of the ones it did.

    None when either raid has no encounters. ``window_start``/``window_end`` are None when there is nothing to
    scope (no extra bosses) or nothing shared.
    """
    if not guild.encounters or not reference.encounters:
        return None
    ref_ids = {e.encounter_id for e in reference.encounters}
    ref_names = {e.name for e in reference.encounters}
    shared = [e for e in guild.encounters if e.encounter_id in ref_ids or e.name in ref_names]
    extra = [e for e in guild.encounters if not (e.encounter_id in ref_ids or e.name in ref_names)]
    scoped = bool(extra and shared)
    return {
        "has_extra_encounters": bool(extra),
        "guild_extra_names": sorted(e.name for e in extra),
        "window_start": min(e.start_time for e in shared) if scoped else None,
        "window_end": max(e.end_time for e in shared) if scoped else None,
        "shared_count": len(shared),
    }


def scope_to_window(analysis: RaidAnalysis, window_start: int, window_end: int) -> RaidAnalysis:
    """A copy with consumables and encounters cut to ``[window_start, window_end]``."""
    consumables = []
    for cu in analysis.consumables:
        ts = [t for t in cu.timestamps if window_start <= t <= window_end]
        if ts:
            consumables.append(dataclasses.replace(cu, timestamps=ts, count=len(ts)))
    encounters = [e for e in analysis.encounters if e.start_time >= window_start and e.end_time <= window_end]
    return dataclasses.replace(analysis, consumables=consumables, encounters=encounters)


def _side(analysis: RaidAnalysis) -> RaidSide:
    return RaidSide(
        report_id=analysis.metadata.report_id,
        title=analysis.metadata.title,
        # As the store keeps it: the report start in local time.
        raid_date=analysis.metadata.date.strftime("%Y-%m-%d %H:%M:%S"),
        zone=analysis.metadata.zone,
        raid_size=len(analysis.composition.all_players),
        duration_ms=raid_duration_ms(analysis),
    )


def _overview(guild: RaidAnalysis, ref: RaidAnalysis) -> list[Metric]:
    def total_damage(a: RaidAnalysis) -> float:
        return sum(d.total_damage for d in a.dps)

    def total_healing(a: RaidAnalysis) -> float:
        return sum(h.total_healing for h in a.healers)

    def taken(a: RaidAnalysis) -> float:
        return sum(t.total_damage_taken for t in a.tanks)

    def per_dps(a: RaidAnalysis) -> float | None:
        return total_damage(a) / len(a.dps) if a.dps else None

    def per_healer(a: RaidAnalysis) -> float | None:
        return total_healing(a) / len(a.healers) if a.healers else None

    return [
        _metric(
            "duration", "Duration", raid_duration_ms(guild), raid_duration_ms(ref), duration, higher_is_better=False
        ),
        _metric("total_damage", "Total damage", total_damage(guild), total_damage(ref)),
        _metric("total_healing", "Total healing", total_healing(guild), total_healing(ref)),
        _metric("damage_taken", "Tank damage taken", taken(guild), taken(ref), higher_is_better=False),
        _metric("damage_per_dps", "Damage per DPS", per_dps(guild), per_dps(ref)),
        _metric("healing_per_healer", "Healing per healer", per_healer(guild), per_healer(ref)),
        _metric(
            "overheal", "Overheal", overheal_percent(guild), overheal_percent(ref), _percent, higher_is_better=False
        ),
    ]


def _composition(guild: RaidAnalysis, ref: RaidAnalysis) -> list[Metric]:
    g, r = guild.composition, ref.composition
    return [
        _metric("raid_size", "Raid size", len(g.all_players), len(r.all_players), _plain),
        _metric("tanks", "Tanks", len(g.tanks), len(r.tanks), _plain),
        _metric("healers", "Healers", len(g.healers), len(r.healers), _plain),
        _metric("melee", "Melee", len(g.melee), len(r.melee), _plain),
        _metric("ranged", "Ranged", len(g.ranged), len(r.ranged), _plain),
    ]


_ROLE_METRIC = {"healer": "healing", "tank": "mitigation %"}


def _classes(guild: RaidAnalysis, ref: RaidAnalysis) -> list[ClassRow]:
    ours = {(r["class"], r["role"]): r for r in class_performance(guild)}
    theirs = {(r["class"], r["role"]): r for r in class_performance(ref)}
    rows = []
    for key in sorted(set(ours) | set(theirs), key=lambda k: (k[1], k[0])):
        g, r = ours.get(key), theirs.get(key)
        g_avg = g["avg_metric"] if g else None
        r_avg = r["avg_metric"] if r else None
        rows.append(
            ClassRow(
                player_class=key[0],
                role=key[1],
                metric=_ROLE_METRIC.get(key[1], "damage"),
                guild_count=g["count"] if g else 0,
                guild_average=g_avg,
                reference_count=r["count"] if r else 0,
                reference_average=r_avg,
                delta_percent=delta_percent(g_avg, r_avg),
            )
        )
    return rows


def _consumables(guild: RaidAnalysis, ref: RaidAnalysis) -> list[ConsumableRow]:
    ours, theirs = consumable_summary(guild), consumable_summary(ref)
    empty = {"total_uses": 0, "unique_users": 0}
    rows = [
        ConsumableRow(
            name=name,
            guild_uses=ours.get(name, empty)["total_uses"],
            guild_users=ours.get(name, empty)["unique_users"],
            reference_uses=theirs.get(name, empty)["total_uses"],
            reference_users=theirs.get(name, empty)["unique_users"],
        )
        for name in set(ours) | set(theirs)
    ]
    rows.sort(key=lambda row: (-(row.guild_uses + row.reference_uses), row.name))
    return rows


def _encounters(guild: RaidAnalysis, ref: RaidAnalysis) -> list[EncounterRow]:
    return [
        EncounterRow(
            name=m["name"],
            guild_duration_ms=m["guild"]["duration_ms"],
            reference_duration_ms=m["ref"]["duration_ms"],
            guild_damage=m["guild"]["total_damage"],
            reference_damage=m["ref"]["total_damage"],
            guild_healing=m["guild"]["total_healing"],
            reference_healing=m["ref"]["total_healing"],
            duration_delta_percent=delta_percent(m["guild"]["duration_ms"], m["ref"]["duration_ms"]),
        )
        for m in match_encounters(guild, ref)
    ]


def compare_raids(guild: RaidAnalysis, reference: RaidAnalysis) -> ReferenceComparison:
    """Our raid against a reference raid. Totals cover each whole raid; consumables and encounters cover the
    shared bosses when our raid killed extra ones."""
    window = shared_encounter_window(guild, reference)
    scoped_guild = guild
    scope = Scope(scoped=False, shared_encounters=0)
    if window is not None:
        scoped = window["window_start"] is not None
        if scoped:
            scoped_guild = scope_to_window(guild, window["window_start"], window["window_end"])
        scope = Scope(scoped, window["shared_count"], list(window["guild_extra_names"]))
    return ReferenceComparison(
        guild=_side(guild),
        reference=_side(reference),
        scope=scope,
        overview=_overview(guild, reference),
        composition=_composition(guild, reference),
        classes=_classes(guild, reference),
        consumables=_consumables(scoped_guild, reference),
        encounters=_encounters(scoped_guild, reference),
    )


# ── The service ──


def parse_code(text: str) -> str:
    """A report code from a bare code or a Warcraft Logs URL; ReferenceRequestError if there is none."""
    code = parse_report_code(text)
    if code is None:
        raise ReferenceRequestError(f"Not a Warcraft Logs report code or URL: {text.strip()[:100]!r}")
    return code


def clean_label(label: str | None) -> str | None:
    label = " ".join((label or "").split())
    if len(label) > MAX_LABEL_LENGTH:
        raise ReferenceRequestError(f"A label is at most {MAX_LABEL_LENGTH} characters")
    return label or None


class ReferenceService:
    """Import, label, list, delete and compare reference raids."""

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.raids = RaidService(ctx)

    def signed_in(self) -> bool:
        """Whether the Warcraft Logs login reference imports need is available."""
        return self.ctx.user_client() is not None

    def references(self, limit: int = 50) -> list[StoredRaid]:
        with self.ctx.repository() as db:
            return [StoredRaid.from_row(r) for r in db.get_raids_by_source(REFERENCE, limit)]

    def guild_raids(self, limit: int = 50) -> list[StoredRaid]:
        """Our raids a reference can be compared against, newest first."""
        with self.ctx.repository() as db:
            return [StoredRaid.from_row(r) for r in db.get_raids_by_source(GUILD, limit)]

    def import_reference(
        self, report: str, *, label: str | None = None, progress: ProgressCallback | None = None
    ) -> RaidAnalysis:
        """Analyse another guild's report with the user login and store it as a reference.

        Raises ReferenceRequestError when the code is bad or the report is already stored (as a guild raid or a
        reference), and ``ReferenceAuthRequired`` without a login.
        """
        code = parse_code(report)
        label = clean_label(label)
        with self.ctx.repository() as db:
            existing = db.get_raid_source(code)
        if existing:
            raise ReferenceRequestError(f"Report {code} is already stored as a {existing} raid")
        analysis = self.raids.analyze_and_save(code, reference=True, progress=progress)
        if label:
            self.set_label(code, label)
        return analysis

    def set_label(self, report: str, label: str | None) -> None:
        code = parse_code(report)
        label = clean_label(label)
        with self.ctx.repository() as db:
            self._require(db.get_raid_source(code), code, REFERENCE)
            db.set_raid_label(code, label)

    def delete_reference(self, report: str) -> None:
        """Delete a stored reference. Refuses guild raids, so a slip cannot remove one of ours."""
        code = parse_code(report)
        with self.ctx.repository() as db:
            self._require(db.get_raid_source(code), code, REFERENCE)
            db.delete_raid(code)

    def compare(self, guild_report: str, reference_report: str) -> ReferenceComparison:
        guild_code, ref_code = parse_code(guild_report), parse_code(reference_report)
        with self.ctx.repository() as db:
            self._require(db.get_raid_source(guild_code), guild_code, GUILD)
            self._require(db.get_raid_source(ref_code), ref_code, REFERENCE)
            guild = db.get_raid_analysis(guild_code)
            ref = db.get_raid_analysis(ref_code)
        if guild is None or ref is None:
            raise ReferenceRequestError("One of the raids could not be read back from storage")
        return compare_raids(guild, ref)

    @staticmethod
    def _require(source: str | None, code: str, wanted: str) -> None:
        if source is None:
            raise ReferenceRequestError(f"Report {code} is not stored")
        if source != wanted:
            raise ReferenceRequestError(f"Report {code} is a {source} raid, not a {wanted} raid")
