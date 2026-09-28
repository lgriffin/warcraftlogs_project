"""The chart payload contract (``wcl_app.charts``, documented in ``guides/charts.md``)."""

from __future__ import annotations

import json
import math

import pytest
from wcl_app.charts import BAR, LINE, MAX_POINTS, MAX_SERIES, Chart, ChartError, Series, nice_ceiling, top_series


def _series(key: str, values: list[float | None], emphasis: bool = False) -> Series:
    return Series(key, key.title(), values, ["-" if v is None else str(v) for v in values], emphasis)


def _chart(**overrides) -> Chart:
    fields = {
        "id": "demo",
        "title": "Demo",
        "kind": LINE,
        "categories": ["a", "b", "c"],
        "series": [_series("one", [1, None, 3])],
        "y_max": 5.0,
    }
    fields.update(overrides)
    return Chart(**fields)


def test_a_valid_chart_round_trips_through_json():
    chart = _chart(notes=["one note"], subtitle="sub")
    data = json.loads(json.dumps(chart.to_dict()))
    assert data["version"] == 1
    assert data["series"][0] == {
        "key": "one",
        "name": "One",
        "values": [1, None, 3],
        "display": ["1", "-", "3"],
        "emphasis": False,
    }
    assert Chart.from_dict(data) == chart


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"kind": "pie"}, "unknown chart kind"),
        ({"series": [_series(f"s{i}", [1, 2, 3]) for i in range(MAX_SERIES + 1)]}, "series; at most"),
        ({"categories": ["x"] * (MAX_POINTS + 1), "series": []}, "categories; at most"),
        ({"title": "x" * 121}, "text longer than"),
        ({"series": [_series("one", [1, 2, 3]), _series("one", [1, 2, 3])]}, "unique"),
        ({"series": [_series("one", [1, 2])]}, "does not match"),
        ({"series": [_series("one", [1, 2, 6])]}, "above y_max"),
        ({"series": [_series("one", [1, 2, math.nan])]}, "not finite"),
    ],
)
def test_validate_refuses_a_chart_that_breaks_the_contract(overrides, message):
    with pytest.raises(ChartError, match=message):
        _chart(**overrides).validate()


def test_from_dict_refuses_something_that_is_not_a_chart():
    with pytest.raises(ChartError, match="not a chart payload"):
        Chart.from_dict({"id": "x"})
    with pytest.raises(ChartError, match="not a chart payload"):
        Chart.from_dict({**_chart().to_dict(), "colour": "red"})


def test_an_empty_chart_is_valid():
    assert _chart(kind=BAR, categories=[], series=[], y_max=0.0, empty="Nothing yet").validate().empty


@pytest.mark.parametrize(
    ("value", "ceiling"),
    [(0, 0), (-3, 0), (0.7, 1), (1, 1), (7.3, 10), (12, 20), (22, 25), (1234, 2000), (4_100_000, 5_000_000)],
)
def test_nice_ceiling(value, ceiling):
    assert nice_ceiling(value) == ceiling


def test_top_series_keeps_emphasis_then_the_largest_and_counts_the_rest():
    series = [
        _series("small", [1, 1, None]),
        _series("big", [5, 5, 5]),
        _series("headline", [0, 0, 1], emphasis=True),
        _series("mid", [2, 2, 2]),
    ]
    kept, hidden = top_series(series, 3)
    assert [s.key for s in kept] == ["headline", "big", "mid"]
    assert hidden == 1


def test_top_series_never_keeps_more_than_the_limit():
    series = [_series(f"s{i}", [i, i, i]) for i in range(20)]
    kept, hidden = top_series(series, 100)
    assert len(kept) == MAX_SERIES and hidden == 20 - MAX_SERIES
    assert top_series(series, -1) == ([], 20)
