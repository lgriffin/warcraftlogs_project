"""
Week-on-week healing: the guild's standard view of how much healing its raids put out.

Raids are grouped into weeks that start on Monday (by ``raid_date``, the report's local start). Every number is
per raid, so a week with two raids compares fairly with a week with one:

- the raid's **healing per raid** (effective healing, overheal left out) and its change on the previous week
  that had a raid,
- the raid's **overheal** share of all healing done,
- each healer's **healing per raid attended** as a healer that week.

Guild raids only; reference logs are never counted. ``WeeklyHealing.raid_chart`` and ``healer_chart`` turn the
numbers into ``wcl_app.charts`` payloads with the chart limits applied.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from wcl_core.models import RaidAnalysis

from wcl_app.charts import BAR, LINE, MAX_SERIES, Chart, Series, compact, top_series, y_ceiling
from wcl_app.context import AppContext, StorageFactory

DEFAULT_WEEKS = 12
MIN_WEEKS = 2
# Half a year: a season's trend, and a bounded number of raids read per page.
MAX_WEEKS = 26
# Newest guild raids read: several raids a week for MAX_WEEKS weeks.
RAIDS_READ = 150


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


@dataclass
class WeeklyHealing:
    weeks: list[HealingWeek]  # oldest first, every week in the window, raided or not
    healers: list[HealerWeeks] = field(default_factory=list)  # most healing first

    @property
    def raids(self) -> int:
        return sum(w.raids for w in self.weeks)

    def to_dict(self) -> dict[str, Any]:
        return {
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
        """Healing per raid, one bar per week, with the latest week-on-week change in the notes."""
        values = [w.per_raid for w in self.weeks]
        series = [Series("healing_per_raid", "Healing per raid", values, [_display(v) for v in values], emphasis=True)]
        chart = Chart(
            id="healing_weekly",
            title="Weekly healing",
            kind=BAR,
            categories=self._categories(),
            series=series,
            subtitle=f"Effective healing per raid, weeks from Monday, last {len(self.weeks)} weeks",
            x_label="Week starting",
            y_label="Healing per raid",
            y_max=y_ceiling(series),
        )
        if not self.raids:
            chart.empty = f"No guild raids in the last {len(self.weeks)} weeks."
            return chart.validate()
        latest = next(w for w in reversed(self.weeks) if w.raids)
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


def weekly_healing(
    raids: Sequence[dict[str, Any]],
    load: Callable[[str], RaidAnalysis | None],
    today: date,
    weeks: int = DEFAULT_WEEKS,
) -> WeeklyHealing:
    """Week-on-week healing for the ``weeks`` weeks up to and including ``today``'s. ``raids`` are guild raid rows
    (``report_id``, ``raid_date``); ``load`` reads one raid's analysis and is called only for raids in the window."""
    weeks = clamp_weeks(weeks)
    this_week = week_start(today)
    starts = [this_week - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    index = {s: i for i, s in enumerate(starts)}
    table = [HealingWeek(s) for s in starts]
    healers: dict[str, HealerWeeks] = {}
    names: list[set[str]] = [set() for _ in starts]
    for raid in raids:
        raid_date = _parse_date(raid.get("raid_date"))
        i = index.get(week_start(raid_date.date())) if raid_date else None
        if i is None:
            continue
        analysis = load(raid["report_id"])
        if analysis is None:
            continue
        week = table[i]
        week.raids += 1
        for h in analysis.healers:
            week.healing += h.total_healing
            week.overhealing += h.total_overhealing
            key = h.name.lower()
            names[i].add(key)
            entry = healers.setdefault(key, HealerWeeks(h.name, h.player_class, [(0, 0)] * len(starts)))
            attended, healing = entry.weeks[i]
            entry.weeks[i] = (attended + 1, healing + h.total_healing)
    previous: HealingWeek | None = None
    for week, seen in zip(table, names, strict=True):
        week.healers = len(seen)
        if not week.raids:
            continue
        if previous is not None and previous.per_raid and week.per_raid is not None:
            week.change_percent = round((week.per_raid - previous.per_raid) / previous.per_raid * 100, 1)
        previous = week
    ranked = sorted(healers.values(), key=lambda h: (-h.total, h.name.lower()))
    return WeeklyHealing(table, ranked)


def _parse_date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


class HealingService:
    """Week-on-week healing from storage."""

    def __init__(self, storage: StorageFactory, *, now: Callable[[], datetime] = datetime.now):
        self.storage = storage
        self.now = now

    @classmethod
    def from_context(cls, ctx: AppContext) -> HealingService:
        return cls(ctx.repository)

    def weekly(self, weeks: int = DEFAULT_WEEKS) -> WeeklyHealing:
        """The last ``weeks`` weeks (clamped to ``MIN_WEEKS``..``MAX_WEEKS``), this week included. Raises
        ``wcl_store.StorageError`` if storage fails."""
        with self.storage() as repo:
            raids = repo.get_raid_list(limit=RAIDS_READ)
            return weekly_healing(raids, repo.get_raid_analysis, self.now().date(), weeks)
