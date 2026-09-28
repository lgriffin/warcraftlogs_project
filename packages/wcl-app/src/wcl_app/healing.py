"""
Week-on-week healing: the guild's standard view of how much healing its raids put out.

Raids are grouped into weeks that start on Monday (by ``raid_date``, the report's local start). Every number is
per raid, so a week with two raids compares fairly with a week with one:

- the raid's **healing per raid** (effective healing, overheal left out) and its change on the previous week
  that had a raid,
- the raid's **overheal** share of all healing done,
- each healer's **healing per raid attended** as a healer that week.

It is a standard to measure against, not only a record: the latest raided week is compared with the average of
the ``BASELINE_WEEKS`` raided weeks before it (the trend) and, when the guild has set one, a target healing per
raid (``HealingStandard``). Both are drawn as reference lines on the chart.

Guild raids only; reference logs are never counted. ``WeeklyHealing.raid_chart`` and ``healer_chart`` turn the
numbers into ``wcl_app.charts`` payloads with the chart limits applied.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from wcl_app.charts import BAR, LINE, MAX_SERIES, Chart, Reference, Series, compact, top_series, y_ceiling
from wcl_app.context import AppContext, StorageFactory

DEFAULT_WEEKS = 12
MIN_WEEKS = 2
# Half a year: a season's trend, and a bounded number of raids read per page.
MAX_WEEKS = 26
# Raided weeks averaged for the baseline the latest week is measured against.
BASELINE_WEEKS = 4
# Within this many percent of the baseline, the trend is steady.
STEADY_PERCENT = 2.0


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
    # Healing per raid against the previous week that had a raid, in percent; None when there is nothing to compare.
    change_percent: float | None = None

    @property
    def per_raid(self) -> float | None:
        return self.healing / self.raids if self.raids else None

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


@dataclass
class HealingStandard:
    """The latest raided week measured against the recent baseline and the guild's target."""

    week: date
    healing_per_raid: float
    # Average healing per raid over up to BASELINE_WEEKS raided weeks before ``week``; None if it is the first.
    baseline: float | None
    target: float | None = None
    # Raided weeks in the window at or above the target.
    weeks_on_target: int = 0
    raided_weeks: int = 0

    @property
    def vs_baseline_percent(self) -> float | None:
        return _percent(self.healing_per_raid, self.baseline)

    @property
    def vs_target_percent(self) -> float | None:
        return _percent(self.healing_per_raid, self.target)

    @property
    def on_target(self) -> bool | None:
        return None if not self.target else self.healing_per_raid >= self.target

    @property
    def trend(self) -> str:
        """``up``, ``down`` or ``steady`` against the baseline, or ``new`` with nothing to compare."""
        change = self.vs_baseline_percent
        if change is None:
            return "new"
        if abs(change) <= STEADY_PERCENT:
            return "steady"
        return "up" if change > 0 else "down"

    def notes(self) -> list[str]:
        out = []
        if self.baseline:
            out.append(
                f"Trend {self.trend}: {abs(self.vs_baseline_percent or 0):.1f}% "
                f"{'above' if self.healing_per_raid >= self.baseline else 'below'} the "
                f"{BASELINE_WEEKS}-week average of {compact(self.baseline)}."
            )
        if self.target:
            verdict = "met" if self.on_target else f"missed by {abs(self.vs_target_percent or 0):.1f}%"
            out.append(
                f"Target {compact(self.target)} per raid {verdict}; "
                f"met in {self.weeks_on_target} of {self.raided_weeks} raided weeks."
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week.isoformat(),
            "healing_per_raid": round(self.healing_per_raid),
            "baseline": None if self.baseline is None else round(self.baseline),
            "vs_baseline_percent": self.vs_baseline_percent,
            "trend": self.trend,
            "target": self.target,
            "vs_target_percent": self.vs_target_percent,
            "on_target": self.on_target,
            "weeks_on_target": self.weeks_on_target,
            "raided_weeks": self.raided_weeks,
        }


@dataclass
class WeeklyHealing:
    weeks: list[HealingWeek]  # oldest first, every week in the window, raided or not
    healers: list[HealerWeeks] = field(default_factory=list)  # most healing first
    # The guild's target healing per raid, if it has set one.
    target: float | None = None

    @property
    def raids(self) -> int:
        return sum(w.raids for w in self.weeks)

    def standard(self) -> HealingStandard | None:
        """The latest raided week against the baseline and target; None when no week in the window raided."""
        raided = [(w, w.per_raid) for w in self.weeks if w.per_raid is not None]
        if not raided:
            return None
        latest, value = raided[-1]
        before = [v for _, v in raided[-1 - BASELINE_WEEKS : -1]]
        target = self.target if self.target and self.target > 0 else None
        return HealingStandard(
            week=latest.start,
            healing_per_raid=value,
            baseline=sum(before) / len(before) if before else None,
            target=target,
            weeks_on_target=sum(1 for _, v in raided if target and v >= target),
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
        """Healing per raid, one bar per week, measured against the baseline and target (reference lines), with
        the latest week's change, trend and target in the notes."""
        values = [w.per_raid for w in self.weeks]
        series = [Series("healing_per_raid", "Healing per raid", values, [_display(v) for v in values], emphasis=True)]
        standard = self.standard()
        references = []
        if standard and standard.baseline:
            label = f"{BASELINE_WEEKS}-week average"
            references.append(Reference("baseline", label, standard.baseline, compact(standard.baseline)))
        if standard and standard.target:
            references.append(Reference("target", "Target", standard.target, compact(standard.target)))
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
        """Each healer's healing per raid attended, one line per healer. Only the ``top`` healers with the most
        healing per raid summed over the weeks are drawn, so a regular healer outranks a one-off guest."""
        series = [
            Series(h.name.lower(), h.name, h.per_raid(), [_display(v) for v in h.per_raid()]) for h in self.healers
        ]
        kept, hidden = top_series(series, top)
        chart = Chart(
            id="healers_weekly",
            title="Healers week on week",
            kind=LINE,
            categories=self._categories(),
            series=kept,
            subtitle="Healing per raid attended as a healer, weeks from Monday",
            x_label="Week starting",
            y_label="Healing per raid",
            y_max=y_ceiling(kept),
        )
        if not kept:
            chart.empty = f"No healers in guild raids in the last {len(self.weeks)} weeks."
        if hidden:
            chart.notes.append(
                f"Showing the {len(kept)} healers with the most healing per raid; {hidden} more not drawn."
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
    target: float | None = None,
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
        entry = healers.setdefault(key, HealerWeeks(row["name"], row.get("player_class") or "", [(0, 0)] * len(starts)))
        attended, total = entry.weeks[i]
        entry.weeks[i] = (attended + 1, total + healing)
    for week, seen, raided in zip(table, names, raids, strict=True):
        week.healers, week.raids = len(seen), len(raided)
    _link_changes(table)
    ranked = sorted(healers.values(), key=lambda h: (-h.total, h.name.lower()))
    return WeeklyHealing(table, ranked, target)


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
        target: float | None = None,
        now: Callable[[], datetime] = datetime.now,
    ):
        """``target`` is the guild's healing per raid to measure each week against; None measures against the
        recent baseline only."""
        self.storage = storage
        self.target = target
        self.now = now

    @classmethod
    def from_context(cls, ctx: AppContext, target: float | None = None) -> HealingService:
        return cls(ctx.repository, target=target)

    def weekly(self, weeks: int = DEFAULT_WEEKS) -> WeeklyHealing:
        """The last ``weeks`` weeks (clamped to ``MIN_WEEKS``..``MAX_WEEKS``), this week included. Raises
        ``wcl_store.StorageError`` if storage fails."""
        with self.storage() as repo:
            today = self.now().date()
            rows = repo.get_healing_by_raid(window_start(today, weeks))
        return weekly_healing(rows, today, weeks, self.target)
