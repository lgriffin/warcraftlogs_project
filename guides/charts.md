# Charts

Charts are decided once, in `wcl_app.charts`, and drawn by each frontend in its own toolkit: QtCharts on the
desktop, SVG on the Toads Hub. A frontend never picks which series to show, formats a number or chooses the
axis range; it draws the payload below. The module is standard library only, so any host can build or check one.
Tests: `tests/test_charts.py` and `tests/test_healing_service.py`.

## Limits

A chart is capped so it stays readable on a phone and its payload stays small:

| limit        | value | why                                                              |
|--------------|-------|------------------------------------------------------------------|
| `MAX_SERIES` | 8     | a longer legend stops being readable and colours start to repeat |
| `MAX_POINTS` | 52    | a year of weekly points; more labels no longer fit a narrow axis |
| `MAX_TEXT`   | 120   | titles, labels, categories and notes stay on one line            |

Builders apply them (`top_series` keeps emphasised series, then the largest) and say what they dropped in
`notes`. `Chart.validate()` and `Chart.from_dict()` raise `ChartError` for a payload that breaks a limit or does
not line up, so a host that stores or relays a chart can refuse a bad one at the door.

## Payload

```json
{
  "version": 1,
  "id": "healing_weekly",
  "title": "Weekly healing",
  "kind": "bar",
  "subtitle": "Effective healing per raid, weeks from Monday, last 12 weeks",
  "x_label": "Week starting",
  "y_label": "Healing per raid",
  "categories": ["7 Jul", "14 Jul", "..."],
  "series": [
    {"key": "healing_per_raid", "name": "Healing per raid", "values": [null, 4100000.0, "..."],
     "display": ["-", "4.1M", "..."], "emphasis": true}
  ],
  "y_max": 5000000.0,
  "notes": ["Week of 21 Sep: +4.2% on the week before it raided.", "Overheal that week: 31.5%."],
  "empty": ""
}
```

| field        | meaning                                                                                  |
|--------------|------------------------------------------------------------------------------------------|
| `version`    | `CHART_SCHEMA_VERSION`; changes only when a field changes meaning or goes away           |
| `kind`       | `bar` (grouped bars per category) or `line` (one line per series)                        |
| `categories` | the x axis, left to right                                                                |
| `series`     | at most 8; `values` and `display` line up with `categories`                              |
| `values`     | raw numbers; `null` is a gap: no bar, and a line breaks there                            |
| `display`    | the same numbers formatted for tooltips and labels ("4.1M", "-" for a gap)               |
| `emphasis`   | the headline series: draw it stronger or in the accent colour                            |
| `y_max`      | a round number (1, 2, 2.5 or 5 times a power of ten) at or above every value; the y axis runs 0 to `y_max` |
| `notes`      | short lines to show under the chart, such as series left out by the limits              |
| `empty`      | when set, draw this message instead of the chart                                         |

Colours are the frontend's: give series colours in order, with the emphasised series in the accent colour.

## Week-on-week healing

`wcl_app.healing` is the guild's standard healing view. Weeks start on Monday (by the raid's local start) and
every number is per raid, so a week with two raids compares fairly with a week with one. Guild raids only.

```python
from wcl_app import HealingService

weekly = HealingService.from_context(ctx).weekly(weeks=12)   # clamped to 2..26 weeks, this week included
weekly.to_dict()          # the numbers: per week raids, healing, healing_per_raid, overheal_percent, healers,
                          # change_percent; per healer healing and healing_per_raid by week
weekly.raid_chart()       # bar chart "healing_weekly": healing per raid by week, latest change in the notes
weekly.healer_chart()     # line chart "healers_weekly": the top 8 healers' healing per raid attended
```

`change_percent` compares a week's healing per raid with the previous week that had a raid. On the home page
the same charts are the `healing_weekly` and `healers_weekly` widgets (`guides/home_widgets.md`).
