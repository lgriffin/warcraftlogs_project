"""
Chart payloads: what a chart shows, decided once, drawn by every frontend in its own toolkit.

A ``Chart`` is plain data (categories along the x axis, one or more series of values) with every number already
formatted, a shared y-axis ceiling and the limits applied. The desktop app draws it with QtCharts, the Toads Hub
with SVG, and neither decides what to leave out or how to label it. ``guides/charts.md`` is the JSON contract.

Limits keep a chart readable and a payload bounded: at most ``MAX_SERIES`` lines or bar groups and
``MAX_POINTS`` categories. ``top_series`` applies the first and says how many it dropped, so the chart can tell
the reader (``notes``); ``Chart.validate`` refuses a payload that breaks them, so a frontend never has
to cope with one.

This module has no dependencies beyond the standard library, so any host can build or check a payload.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

CHART_SCHEMA_VERSION = 1

# Chart kinds
LINE = "line"
BAR = "bar"
KINDS = (LINE, BAR)

# Beyond this many series a legend stops being readable and colours start to repeat.
MAX_SERIES = 8
# A year of weekly points; wider than that and labels no longer fit a phone screen.
MAX_POINTS = 52
# Reference lines: a standard, a target, a baseline; more and they read as data.
MAX_REFERENCES = 3
# Labels, keys, formatted numbers and notes are one line each, and there are only a few notes.
MAX_TEXT = 120
MAX_NOTES = 10


class ChartError(ValueError):
    """A chart payload that breaks the contract."""


def _finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


@dataclass
class Series:
    """One line, or one set of bars. ``values`` and ``display`` line up with the chart's categories; a gap
    (nothing to plot for that category) is ``None`` with display ``"-"``."""

    key: str
    name: str
    values: list[float | None]
    display: list[str]
    # Drawn stronger than the rest: the headline number the chart is about.
    emphasis: bool = False

    @property
    def total(self) -> float:
        return sum(v for v in self.values if v is not None)


@dataclass
class Reference:
    """A horizontal line to measure the series against, such as a target or a recent average."""

    key: str
    label: str
    value: float
    display: str


@dataclass
class Chart:
    id: str
    title: str
    kind: str
    categories: list[str]
    series: list[Series]
    subtitle: str = ""
    x_label: str = ""
    y_label: str = ""
    # A round number at or above every value and reference, so each frontend draws the same axis.
    y_max: float = 0.0
    # Horizontal lines to measure against, drawn dashed and labelled.
    references: list[Reference] = field(default_factory=list)
    # What the reader should know about the numbers, such as series left out by the limits.
    notes: list[str] = field(default_factory=list)
    # Why there is nothing to draw; categories and series may then be empty.
    empty: str = ""

    def validate(self) -> Chart:
        """Raise ``ChartError`` if the payload breaks the contract; return the chart otherwise."""
        try:
            self._check_shape()
            self._check_text()
            self._check_numbers()
        except (TypeError, AttributeError) as e:  # a field of the wrong type, e.g. from a hand-built payload
            raise ChartError(f"not a chart payload: {e}") from e
        return self

    def _check_shape(self) -> None:
        if self.kind not in KINDS:
            raise ChartError(f"unknown chart kind {self.kind!r}")
        for name, items, limit in (
            ("series", self.series, MAX_SERIES),
            ("categories", self.categories, MAX_POINTS),
            ("references", self.references, MAX_REFERENCES),
            ("notes", self.notes, MAX_NOTES),
        ):
            if len(items) > limit:
                raise ChartError(f"{len(items)} {name}; at most {limit} are drawn")
        keys = [s.key for s in self.series]
        if len(set(keys)) != len(keys):
            raise ChartError("series keys must be unique")
        for s in self.series:
            if len(s.values) != len(self.categories) or len(s.display) != len(self.categories):
                raise ChartError(f"series {s.key!r} does not match the {len(self.categories)} categories")

    def _check_text(self) -> None:
        texts = [self.id, self.title, self.subtitle, self.x_label, self.y_label, self.empty, *self.categories]
        texts += self.notes
        texts += [t for s in self.series for t in (s.key, s.name, *s.display)]
        texts += [t for r in self.references for t in (r.key, r.label, r.display)]
        for text in texts:
            if not isinstance(text, str) or len(text) > MAX_TEXT:
                raise ChartError(f"text must be at most {MAX_TEXT} characters: {str(text)[:20]!r}")

    def _check_numbers(self) -> None:
        if not _finite(self.y_max) or self.y_max < 0:
            raise ChartError("y_max must be a finite number of at least 0")
        for s in self.series:
            if any(v is not None and not (_finite(v) and 0 <= v <= self.y_max) for v in s.values):
                raise ChartError(f"series {s.key!r} has a value outside 0 to y_max")
        for ref in self.references:
            if not (_finite(ref.value) and 0 <= ref.value <= self.y_max):
                raise ChartError(f"reference {ref.key!r} is outside 0 to y_max")

    def to_dict(self) -> dict[str, Any]:
        return {"version": CHART_SCHEMA_VERSION, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Chart:
        """Read a payload back, checking it against the contract. Raises ``ChartError``."""
        if not isinstance(data, dict) or data.get("version") != CHART_SCHEMA_VERSION:
            raise ChartError(f"not a version {CHART_SCHEMA_VERSION} chart payload")
        try:
            series = [Series(**s) for s in data["series"]]
            references = [Reference(**r) for r in data.get("references", [])]
            fields = {k: v for k, v in data.items() if k not in ("version", "series", "references")}
            chart = cls(series=series, references=references, **fields)
        except (KeyError, TypeError, AttributeError) as e:
            raise ChartError(f"not a chart payload: {e}") from e
        return chart.validate()


# ── Building ──


def compact(n: float) -> str:
    """12345678 -> "12.3M", 4500 -> "4.5K", 950 -> "950"."""
    for size, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= size:
            return f"{n / size:.1f}{suffix}"
    return f"{n:,.0f}"


def nice_ceiling(value: float) -> float:
    """The smallest 1, 2, 2.5 or 5 times a power of ten at or above ``value``: 0 -> 0, 7.3 -> 10, 1234 -> 2000."""
    if value <= 0:
        return 0.0
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if step * magnitude >= value:
            return float(step * magnitude)
    return float(10 * magnitude)  # pragma: no cover - the loop always returns


def y_ceiling(series: Sequence[Series], references: Sequence[Reference] = ()) -> float:
    values = [v for s in series for v in s.values if v is not None] + [r.value for r in references]
    return nice_ceiling(max(values, default=0.0))


def top_series(series: Sequence[Series], limit: int = MAX_SERIES) -> tuple[list[Series], int]:
    """Emphasised series first, then the rest by total, largest first, up to ``limit``; also how many were left
    out. Ties keep their order."""
    limit = max(0, min(limit, MAX_SERIES))
    ranked = sorted(series, key=lambda s: (not s.emphasis, -s.total))
    return ranked[:limit], max(0, len(ranked) - limit)
