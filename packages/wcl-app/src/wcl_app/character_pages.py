"""
Character pages: one character's raids as a JSON payload, the desktop's character profile for the Toads Hub's Me page.

A page holds the character's raids (newest first, at most ``MAX_RAIDS``), each with the role they played, that role's
headline number and where it stood in the raid: the median of the others in the same role and the character's place
among them. Beside the raids sit the character's lineage (``wcl_app.lineage``: min / mean / max of each metric, their
casts and consumables), their personal bests and one chart per role played, the character against the raid's median.

Everything is read through ``RaidRepository``, so pages build the same on SQLite and Postgres. ``pages(names)`` builds a
whole roster in one storage session and reads each raid's analysis once; every call reads raids afresh.
``guides/character_pages.md`` is the JSON contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import TYPE_CHECKING, Any

from wcl_store import RaidScope, StorageError
from wcl_store.scope import narrowed

from wcl_app.charts import LINE, Chart, Series, compact, y_ceiling
from wcl_app.context import AppContext, ScopeSource, StorageFactory, resolve_scope
from wcl_app.lineage import character_lineage
from wcl_app.raid_pages import weekday_of

if TYPE_CHECKING:
    from wcl_core.models import RaidAnalysis
    from wcl_store import RaidRepository

CHARACTER_PAGE_VERSION = 1
# Half a year of weekly raids on two or three nights; the chart shows the newest ``CHART_RAIDS``.
MAX_RAIDS = 40
CHART_RAIDS = 20
TOP_CASTS = 10
TOP_CONSUMABLES = 10

# Each role's headline number: (raid-role row column, label). Higher is better except a tank's damage taken.
HEADLINE: dict[str, tuple[str, str]] = {
    "healer": ("healing", "Healing"),
    "tank": ("damage_taken", "Damage taken"),
    "melee": ("damage", "Damage"),
    "ranged": ("damage", "Damage"),
}
ROLE_NAMES = {"healer": "Healer", "tank": "Tank", "melee": "Melee", "ranged": "Ranged"}


@dataclass
class CharacterRaid:
    report_id: str
    title: str
    zone: str
    raid_date: str
    # 0 for Monday to 6 for Sunday; None when the date cannot be read.
    weekday: int | None
    role: str
    metric: str
    value: float
    display: str
    # The median of everyone in the raid in the same role, the character included; None when the raid cannot be read.
    median: float | None = None
    median_display: str = "-"
    # The character's place in their role in the raid (1 is the most), and how many played it. 0 when unknown, and
    # always for tanks, whose damage taken is no ranking.
    rank: int = 0
    of: int = 0
    # The role's second number: overheal % for a healer, mitigation % for a tank.
    percent: float | None = None


@dataclass
class PersonalBest:
    metric: str
    role: str
    value: float
    display: str
    report_id: str
    raid_date: str


@dataclass
class CharacterPage:
    name: str
    player_class: str
    raids: int
    first_raid: str | None
    last_raid: str | None
    role_counts: dict[str, int]
    recent: list[CharacterRaid] = field(default_factory=list)
    # ``wcl_app.lineage.Spread`` dicts: headline metrics, the most cast spells and the most used consumables.
    metrics: list[dict[str, Any]] = field(default_factory=list)
    casts: list[dict[str, Any]] = field(default_factory=list)
    consumables: list[dict[str, Any]] = field(default_factory=list)
    bests: list[PersonalBest] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["charts"] = [c.to_dict() for c in self.charts]
        return {"version": CHARACTER_PAGE_VERSION, **out}


def _value(row: dict[str, Any]) -> tuple[str, str, float] | None:
    headline = HEADLINE.get(str(row.get("role")))
    if headline is None or row.get(headline[0]) is None:
        return None
    return headline[0], headline[1], float(row[headline[0]])


def _role_values(analysis: RaidAnalysis, role: str) -> dict[str, float]:
    """Each player's headline number in ``role``, by lower-cased name."""
    if role == "healer":
        return {h.name.lower(): float(h.total_healing) for h in analysis.healers}
    if role == "tank":
        return {t.name.lower(): float(t.total_damage_taken) for t in analysis.tanks}
    return {d.name.lower(): float(d.total_damage) for d in analysis.dps if d.role == role}


def _standing(raid: CharacterRaid, name: str, analysis: RaidAnalysis | None) -> None:
    """Fill in the raid's median for the role and the character's place in it."""
    if analysis is None:
        return
    values = _role_values(analysis, raid.role)
    if not values:
        return
    raid.median = float(median(values.values()))
    raid.median_display = compact(raid.median)
    if raid.role != "tank" and name.lower() in values:
        mine = values[name.lower()]
        raid.rank = 1 + sum(1 for v in values.values() if v > mine)
        raid.of = len(values)


def _percent(row: dict[str, Any]) -> float | None:
    key = {"healer": "overheal_percent", "tank": "mitigation_percent"}.get(str(row.get("role")))
    return None if key is None or row.get(key) is None else float(row[key])


def _bests(rows: list[dict[str, Any]]) -> list[PersonalBest]:
    """The raid with the character's highest headline number in each role (a tank's lowest damage taken is no best)."""
    best: dict[str, PersonalBest] = {}
    for row in rows:
        found = _value(row)
        if found is None or row["role"] == "tank":
            continue
        _, label, value = found
        current = best.get(row["role"])
        if current is None or value > current.value:
            best[row["role"]] = PersonalBest(
                label, row["role"], value, compact(value), str(row["report_id"]), str(row["raid_date"])
            )
    return [best[r] for r in HEADLINE if r in best]


def _chart(role: str, raids: list[CharacterRaid]) -> Chart:
    """The character's headline number in ``role`` against the raid's median, oldest raid first."""
    shown = [r for r in raids if r.role == role][:CHART_RAIDS][::-1]
    metric = HEADLINE[role][1]
    mine = Series("you", "You", [r.value for r in shown], [r.display for r in shown], emphasis=True)
    others = Series(
        "median",
        f"{ROLE_NAMES[role]} median",
        [r.median for r in shown],
        [r.median_display for r in shown],
    )
    series = [mine, others]
    return Chart(
        id=f"character_{role}",
        title=f"{metric} as {ROLE_NAMES[role].lower()}",
        kind=LINE,
        categories=[f"{r.raid_date[8:10]}/{r.raid_date[5:7]}" for r in shown],
        series=series,
        subtitle=f"Your last {len(shown)} raids as {ROLE_NAMES[role].lower()}, against the raid's median",
        x_label="Raid",
        y_label=metric,
        y_max=y_ceiling(series),
    ).validate()


class CharacterPageService:
    """Character pages built from stored guild raids, read through the repository only."""

    def __init__(self, storage: StorageFactory, scope: ScopeSource = None):
        self._storage = storage
        # A scope, or a callable giving the active profile's at read time; None reads every guild raid.
        self._scope = scope
        # Raid analyses read for the medians during one pages() call.
        self._analyses: dict[str, RaidAnalysis] = {}

    @classmethod
    def from_context(cls, ctx: AppContext) -> CharacterPageService:
        return cls(ctx.repository, scope=lambda: ctx.scope)

    def page(self, name: str) -> CharacterPage | None:
        """The character's page, or None when they have no guild raid inside the scope or storage cannot be read."""
        return self.pages([name])[0]

    def pages(self, names: list[str]) -> list[CharacterPage | None]:
        """Each named character's page, in order, as ``page`` gives it; each raid's analysis is read once."""
        # Character pages are the guild's raids, whatever sources the active profile's scope names.
        scope = narrowed(resolve_scope(self._scope), ("guild",))
        self._analyses = {}
        try:
            with self._storage() as db:
                return [self._build(db, name, scope) for name in names]
        except StorageError:
            return [None] * len(names)
        finally:
            self._analyses = {}

    def _analysis(self, db: RaidRepository, report_id: str) -> RaidAnalysis | None:
        if report_id not in self._analyses:
            try:
                analysis = db.get_raid_analysis(report_id)
            except StorageError:
                return None
            if analysis is None:
                return None
            self._analyses[report_id] = analysis
        return self._analyses[report_id]

    def _build(self, db: RaidRepository, name: str, scope: RaidScope | None) -> CharacterPage | None:
        history = db.get_character_history(name, scope=scope)
        lineage = character_lineage(db, name, scope=scope)
        if history is None or lineage is None:
            return None
        rows = db.get_character_raid_roles(name, scope=scope)
        recent: list[CharacterRaid] = []
        for row in reversed(rows[-MAX_RAIDS:]):
            found = _value(row)
            if found is None:
                continue
            _, label, value = found
            raid_date = str(row["raid_date"] or "")
            raid = CharacterRaid(
                report_id=str(row["report_id"]),
                title=str(row.get("title") or ""),
                zone=str(row.get("zone") or ""),
                raid_date=raid_date,
                weekday=weekday_of(raid_date),
                role=str(row["role"]),
                metric=label,
                value=value,
                display=compact(value),
                percent=_percent(row),
            )
            _standing(raid, history.name, self._analysis(db, raid.report_id))
            recent.append(raid)
        roles = [r for r in HEADLINE if any(raid.role == r for raid in recent)]
        return CharacterPage(
            name=history.name,
            player_class=history.player_class,
            raids=lineage.raids,
            first_raid=lineage.first_raid,
            last_raid=lineage.last_raid,
            role_counts=lineage.role_counts,
            recent=recent,
            metrics=[asdict(s) for s in lineage.metrics],
            casts=[asdict(s) for s in lineage.casts[:TOP_CASTS]],
            consumables=[asdict(s) for s in lineage.consumables[:TOP_CONSUMABLES]],
            bests=_bests(rows),
            charts=[_chart(role, recent) for role in roles],
        )
