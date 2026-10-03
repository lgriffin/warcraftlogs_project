"""
Week-on-week healing: the guild's standard view of how much healing its raids put out.

Raids are grouped into weeks that start on Monday (by ``raid_date``, the report's local start). Every number is
per raid, so a week with two raids compares fairly with a week with one:

- the raid's **healing per raid** (effective healing, overheal left out) and its change on the previous week
  that had a raid,
- the **average per character**: healing per healer per raid, over every healer in every raid that week,
- the raid's **overheal** share of all healing done,
- each healer's **healing per raid attended** as a healer that week.

The standard is the guild's own numbers over time, not a fixed target: the latest raided week's healing per raid
and average per character are each compared with their average over the ``BASELINE_WEEKS`` raided weeks before it
(``HealingStandard``), and the per-raid average is drawn as a reference line on the chart.

Guild raids only; reference logs are never counted. ``WeeklyHealing.raid_chart`` and ``healer_chart`` turn the
numbers into ``wcl_app.charts`` payloads with the chart limits applied.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from wcl_store import RaidScope

from wcl_app.charts import BAR, LINE, MAX_SERIES, Chart, Reference, Series, compact, top_series, y_ceiling
from wcl_app.context import AppContext, ScopeSource, StorageFactory, resolve_scope

DEFAULT_WEEKS = 12
MIN_WEEKS = 2
# Half a year: a season's trend, and a bounded number of raids read per page.
MAX_WEEKS = 26
# Raided weeks averaged for the baseline the latest week is measured against.
BASELINE_WEEKS = 4
# Within this many percent of the baseline, the trend is steady.
STEADY_PERCENT = 2.0
# The key of the guild's average line on the healers chart. Character names are letters only, so no healer's key
# (their lower-cased name) can be this.
AVERAGE_KEY = "guild_average"


def week_start(day: date) -> date:
    """The Monday of ``day``'s week."""
    return day - timedelta(days=day.weekday())


def week_label(monday: date) -> str:
    return f"{monday.day} {monday:%b}"


def clamp_weeks(weeks: int) -> int:
    return max(MIN_WEEKS, min(int(weeks), MAX_WEEKS))


@dataclass
class HealingWeek:
    start: date  # Monday
    raids: int = 0
    healing: int = 0
    overhealing: int = 0
    healers: int = 0
    # Healers counted once per raid they healed in: the divisor of ``per_character``.
    appearances: int = 0
    # Healing per raid against the previous week that had a raid, in percent; None when there is nothing to compare.
    change_percent: float | None = None

    @property
    def per_raid(self) -> float | None:
        return self.healing / self.raids if self.raids else None

    @property
    def per_character(self) -> float | None:
        """Average healing per healer per raid."""
        return self.healing / self.appearances if self.appearances else None

    @property
    def overheal_percent(self) -> float | None:
        done = self.healing + self.overhealing
        return round(self.overhealing / done * 100, 1) if done else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.start.isoformat(),
            "raids": self.raids,
            "healing": self.healing,
            "healing_per_raid": None if self.per_raid is None else round(self.per_raid),
            "healing_per_character": None if self.per_character is None else round(self.per_character),
            "overheal_percent": self.overheal_percent,
            "healers": self.healers,
            "change_percent": self.change_percent,
        }


@dataclass
class HealerWeeks:
    name: str
    player_class: str
    # Per week, oldest first, lined up with ``WeeklyHealing.weeks``: (raids attended as a healer, healing).
    weeks: list[tuple[int, int]]

    @property
    def total(self) -> int:
        return sum(h for _, h in self.weeks)

    def per_raid(self) -> list[float | None]:
        return [h / n if n else None for n, h in self.weeks]


def _percent(value: float, against: float | None) -> float | None:
    return round((value - against) / against * 100, 1) if against else None


def _trend(change: float | None) -> str:
    """``up``, ``down`` or ``steady`` for a change in percent, or ``new`` with nothing to compare."""
    if change is None:
        return "new"
    if abs(change) <= STEADY_PERCENT:
        return "steady"
    return "up" if change > 0 else "down"


def _average(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _trend_note(label: str, value: float, baseline: float | None, change: float | None) -> list[str]:
    """One line saying how ``value`` compares with its baseline, or none when there is no baseline yet."""
    if not baseline:
        return []
    return [
        f"{label} {compact(value)}: {_trend(change)}, {abs(change or 0):.1f}% "
        f"{'above' if value >= baseline else 'below'} its {BASELINE_WEEKS}-week average of {compact(baseline)}."
    ]


@dataclass
class HealingStandard:
    """The latest raided week measured against the guild's own recent weeks: healing per raid and the average per
    character, each against its average over up to ``BASELINE_WEEKS`` raided weeks before it (None for the first)."""

    week: date
    healing_per_raid: float
    baseline: float | None
    healing_per_character: float
    character_baseline: float | None
    raided_weeks: int = 0

    @property
    def vs_baseline_percent(self) -> float | None:
        return _percent(self.healing_per_raid, self.baseline)

    @property
    def character_vs_baseline_percent(self) -> float | None:
        return _percent(self.healing_per_character, self.character_baseline)

    @property
    def trend(self) -> str:
        """Healing per raid against its baseline."""
        return _trend(self.vs_baseline_percent)

    @property
    def character_trend(self) -> str:
        """Average per character against its baseline."""
        return _trend(self.character_vs_baseline_percent)

    def raid_notes(self) -> list[str]:
        return _trend_note("Per raid", self.healing_per_raid, self.baseline, self.vs_baseline_percent)

    def character_notes(self) -> list[str]:
        return _trend_note(
            "Per character", self.healing_per_character, self.character_baseline, self.character_vs_baseline_percent
        )

    def notes(self) -> list[str]:
        return self.raid_notes() + self.character_notes()

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week.isoformat(),
            "healing_per_raid": round(self.healing_per_raid),
            "baseline": None if self.baseline is None else round(self.baseline),
            "vs_baseline_percent": self.vs_baseline_percent,
            "trend": self.trend,
            "healing_per_character": round(self.healing_per_character),
            "character_baseline": None if self.character_baseline is None else round(self.character_baseline),
            "character_vs_baseline_percent": self.character_vs_baseline_percent,
            "character_trend": self.character_trend,
            "raided_weeks": self.raided_weeks,
        }


@dataclass
class WeeklyHealing:
    weeks: list[HealingWeek]  # oldest first, every week in the window, raided or not
    healers: list[HealerWeeks] = field(default_factory=list)  # most healing first

    @property
    def raids(self) -> int:
        return sum(w.raids for w in self.weeks)

    def standard(self) -> HealingStandard | None:
        """The latest raided week against the weeks before it; None when no week in the window raided."""
        raided = [w for w in self.weeks if w.raids]
        if not raided:
            return None
        latest, before = raided[-1], raided[-1 - BASELINE_WEEKS : -1]
        return HealingStandard(
            week=latest.start,
            healing_per_raid=latest.per_raid or 0.0,
            baseline=_average([w.per_raid or 0.0 for w in before]),
            healing_per_character=latest.per_character or 0.0,
            character_baseline=_average([w.per_character or 0.0 for w in before]),
            raided_weeks=len(raided),
        )

    def to_dict(self) -> dict[str, Any]:
        standard = self.standard()
        return {
            "standard": standard.to_dict() if standard else None,
            "weeks": [w.to_dict() for w in self.weeks],
            "healers": [
                {
                    "name": h.name,
                    "player_class": h.player_class,
                    "healing": h.total,
                    "healing_per_raid": [None if v is None else round(v) for v in h.per_raid()],
                }
                for h in self.healers
            ],
        }

    def _categories(self) -> list[str]:
        return [week_label(w.start) for w in self.weeks]

    def raid_chart(self) -> Chart:
        """Healing per raid, one bar per week, measured against its recent average (a reference line), with the
        latest week's trend per raid and per character, change and overheal in the notes."""
        values = [w.per_raid for w in self.weeks]
        series = [Series("healing_per_raid", "Healing per raid", values, [_display(v) for v in values], emphasis=True)]
        standard = self.standard()
        references = []
        if standard and standard.baseline:
            label = f"{BASELINE_WEEKS}-week average"
            references.append(Reference("baseline", label, standard.baseline, compact(standard.baseline)))
        chart = Chart(
            id="healing_weekly",
            title="Weekly healing",
            kind=BAR,
            categories=self._categories(),
            series=series,
            subtitle=f"Effective healing per raid, weeks from Monday, last {len(self.weeks)} weeks",
            x_label="Week starting",
            y_label="Healing per raid",
            y_max=y_ceiling(series, references),
            references=references,
        )
        if standard is None:
            chart.empty = f"No guild raids in the last {len(self.weeks)} weeks."
            return chart.validate()
        latest = next(w for w in reversed(self.weeks) if w.raids)
        chart.notes.extend(standard.notes())
        if latest.change_percent is not None:
            chart.notes.append(
                f"Week of {week_label(latest.start)}: {latest.change_percent:+.1f}% on the week before it raided."
            )
        if latest.overheal_percent is not None:
            chart.notes.append(f"Overheal that week: {latest.overheal_percent}%.")
        return chart.validate()

    def healer_chart(self, top: int = MAX_SERIES) -> Chart:
        """The guild's average per character (the emphasised line) and each healer's healing per raid attended,
        one line per healer. Only the healers with the most healing per raid summed over the weeks are drawn (``top``
        lines in all), so a regular healer outranks a one-off guest."""
        average = [w.per_character for w in self.weeks]
        series = [Series(AVERAGE_KEY, "Average per character", average, [_display(v) for v in average], emphasis=True)]
        series += [
            Series(h.name.lower(), h.name, h.per_raid(), [_display(v) for v in h.per_raid()]) for h in self.healers
        ]
        if not self.healers:
            series = []
        kept, hidden = top_series(series, top)
        standard = self.standard()
        references = []
        if standard and standard.character_baseline and any(s.key == AVERAGE_KEY for s in kept):
            base = standard.character_baseline
            references.append(Reference("character_baseline", f"{BASELINE_WEEKS}-week average", base, compact(base)))
        chart = Chart(
            id="healers_weekly",
            title="Healers week on week",
            kind=LINE,
            categories=self._categories(),
            series=kept,
            subtitle="Healing per raid attended as a healer, against the guild's average per character",
            x_label="Week starting",
            y_label="Healing per raid",
            y_max=y_ceiling(kept, references),
            references=references,
        )
        if not self.healers:
            chart.empty = f"No healers in guild raids in the last {len(self.weeks)} weeks."
        elif not kept:
            chart.empty = "No lines to draw."
        if standard and references:
            chart.notes.extend(standard.character_notes())
        if hidden:
            drawn = sum(1 for s in kept if s.key != AVERAGE_KEY)
            left_out = len(self.healers) - drawn
            chart.notes.append(
                f"Showing the {drawn} healers with the most healing per raid; {left_out} more not drawn."
            )
        return chart.validate()


def _display(value: float | None) -> str:
    return "-" if value is None else compact(value)


def window(today: date, weeks: int = DEFAULT_WEEKS) -> list[date]:
    """The Mondays of the ``weeks`` weeks (clamped) up to and including ``today``'s, oldest first."""
    this_week = week_start(today)
    return [this_week - timedelta(weeks=n) for n in range(clamp_weeks(weeks) - 1, -1, -1)]


def window_start(today: date, weeks: int = DEFAULT_WEEKS) -> str:
    """The window's first moment as a stored ``raid_date``, for ``RaidRepository.get_healing_by_raid``."""
    return f"{window(today, weeks)[0]:%Y-%m-%d} 00:00:00"


def weekly_healing(
    rows: Sequence[dict[str, Any]],
    today: date,
    weeks: int = DEFAULT_WEEKS,
) -> WeeklyHealing:
    """Week-on-week healing for the ``weeks`` weeks up to and including ``today``'s, from
    ``RaidRepository.get_healing_by_raid`` rows (one per healer per raid). Rows outside the window are ignored."""
    starts = window(today, weeks)
    index = {s: i for i, s in enumerate(starts)}
    table = [HealingWeek(s) for s in starts]
    healers: dict[str, HealerWeeks] = {}
    names: list[set[str]] = [set() for _ in starts]
    raids: list[set[str]] = [set() for _ in starts]
    for row in rows:
        raid_date = _parse_date(row.get("raid_date"))
        i = index.get(week_start(raid_date.date())) if raid_date else None
        if i is None:
            continue
        healing, overhealing = int(row.get("healing") or 0), int(row.get("overhealing") or 0)
        table[i].healing += healing
        table[i].overhealing += overhealing
        raids[i].add(row["report_id"])
        key = row["name"].lower()
        names[i].add(key)
        table[i].appearances += 1
        entry = healers.setdefault(key, HealerWeeks(row["name"], row.get("player_class") or "", [(0, 0)] * len(starts)))
        attended, total = entry.weeks[i]
        entry.weeks[i] = (attended + 1, total + healing)
    for week, seen, raided in zip(table, names, raids, strict=True):
        week.healers, week.raids = len(seen), len(raided)
    _link_changes(table)
    ranked = sorted(healers.values(), key=lambda h: (-h.total, h.name.lower()))
    return WeeklyHealing(table, ranked)


def _link_changes(table: Sequence[HealingWeek]) -> None:
    """Each raided week's change in healing per raid on the previous week that raided."""
    previous: HealingWeek | None = None
    for week in table:
        if week.per_raid is None:
            continue
        if previous is not None and previous.per_raid:
            week.change_percent = round((week.per_raid - previous.per_raid) / previous.per_raid * 100, 1)
        previous = week


def _parse_date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


class HealingService:
    """Week-on-week healing from storage."""

    def __init__(
        self,
        storage: StorageFactory,
        *,
        now: Callable[[], datetime] = datetime.now,
        scope: ScopeSource = None,
    ):
        self.storage = storage
        self.now = now
        # A scope, or a callable giving the active profile's at read time; None reads every guild raid.
        self._scope = scope

    @property
    def scope(self) -> RaidScope | None:
        return resolve_scope(self._scope)

    @classmethod
    def from_context(cls, ctx: AppContext) -> HealingService:
        return cls(ctx.repository, scope=lambda: ctx.scope)

    def weekly(self, weeks: int = DEFAULT_WEEKS) -> WeeklyHealing:
        """The last ``weeks`` weeks (clamped to ``MIN_WEEKS``..``MAX_WEEKS``), this week included. Raises
        ``wcl_store.StorageError`` if storage fails."""
        with self.storage() as repo:
            today = self.now().date()
            rows = repo.get_healing_by_raid(window_start(today, weeks), scope=self.scope)
        return weekly_healing(rows, today, weeks)
