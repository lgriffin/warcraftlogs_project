"""
Reusable chart widgets for performance trends using PySide6.QtCharts.
"""

from collections import defaultdict
from datetime import datetime

from PySide6.QtCharts import (
    QChart, QChartView, QLineSeries, QValueAxis, QDateTimeAxis,
)
from PySide6.QtCore import Qt, QDateTime, QPointF, QMargins
from PySide6.QtGui import QPen, QColor, QPainter, QFont

from .styles import COLORS

SERIES_COLORS = [
    QColor("#e94560"),
    QColor("#69CCF0"),
    QColor("#2ecc71"),
    QColor("#f39c12"),
    QColor("#9b59b6"),
    QColor("#ABD473"),
    QColor("#F58CBA"),
    QColor("#C79C6E"),
    QColor("#FFF569"),
    QColor("#0070DE"),
]


def _make_chart(title: str) -> QChart:
    chart = QChart()
    chart.setTitle(title)
    chart.setTitleFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
    chart.setTitleBrush(QColor(COLORS["text_header"]))
    chart.setBackgroundBrush(QColor(COLORS["bg_card"]))
    chart.legend().setLabelColor(QColor(COLORS["text"]))
    chart.legend().setFont(QFont("Segoe UI", 9))
    chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
    chart.setMargins(QMargins(8, 8, 8, 8))
    return chart


def _style_axis(axis, color=None):
    c = QColor(color or COLORS["text_dim"])
    axis.setLabelsColor(c)
    axis.setGridLineColor(QColor(COLORS["border"]))
    axis.setLinePenColor(QColor(COLORS["border"]))
    axis.setLabelsFont(QFont("Segoe UI", 8))


def _parse_dates_and_values(trend_data: list[dict], value_key: str) -> list[tuple[datetime, float]]:
    points = []
    for row in reversed(trend_data):
        date_str = row.get("raid_date", "")
        val = row.get(value_key, 0) or 0
        try:
            dt = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            continue
        points.append((dt, float(val)))
    return points


def _add_series(chart: QChart, points: list[tuple[datetime, float]],
                name: str, color_idx: int,
                x_axis: QDateTimeAxis, y_axis: QValueAxis):
    series = QLineSeries()
    series.setName(name)
    pen = QPen(SERIES_COLORS[color_idx % len(SERIES_COLORS)])
    pen.setWidth(2)
    series.setPen(pen)

    for dt, val in points:
        ms = QDateTime(dt).toMSecsSinceEpoch()
        series.append(QPointF(ms, val))

    chart.addSeries(series)
    series.attachAxis(x_axis)
    series.attachAxis(y_axis)


def _fit_axes(x_axis: QDateTimeAxis, y_axis: QValueAxis,
              all_points: list[tuple[datetime, float]]):
    if not all_points:
        return
    dates = [p[0] for p in all_points]
    values = [p[1] for p in all_points]

    x_axis.setRange(QDateTime(min(dates)), QDateTime(max(dates)))

    max_val = max(values) if values else 100
    y_axis.setRange(0, max_val * 1.1)
    y_axis.setLabelFormat("%'.0f")


def make_chart_view(chart: QChart) -> QChartView:
    view = QChartView(chart)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.setStyleSheet(f"background-color: {COLORS['bg_card']}; border: none;")
    view.setMinimumHeight(220)
    return view


# ── Standard summary charts ──

def build_healer_chart(trend_data: list[dict]) -> QChartView:
    chart = _make_chart("Healing Performance")

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    x_axis.setTitleText("Raid Date")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_axis = QValueAxis()
    y_axis.setTitleText("Amount")
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    healing_pts = _parse_dates_and_values(trend_data, "total_healing")
    overheal_pts = _parse_dates_and_values(trend_data, "total_overhealing")

    all_pts = healing_pts + overheal_pts
    _fit_axes(x_axis, y_axis, all_pts)

    _add_series(chart, healing_pts, "Healing", 0, x_axis, y_axis)
    _add_series(chart, overheal_pts, "Overhealing", 1, x_axis, y_axis)

    return make_chart_view(chart)


def build_healer_overheal_chart(trend_data: list[dict]) -> QChartView:
    chart = _make_chart("Overheal %")

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_axis = QValueAxis()
    y_axis.setTitleText("OH%")
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    pts = _parse_dates_and_values(trend_data, "overheal_percent")
    _fit_axes(x_axis, y_axis, pts)
    if pts:
        y_axis.setRange(0, min(100, max(v for _, v in pts) * 1.2))
    _add_series(chart, pts, "Overheal %", 3, x_axis, y_axis)

    return make_chart_view(chart)


def build_tank_chart(trend_data: list[dict]) -> QChartView:
    chart = _make_chart("Tank Performance")

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    x_axis.setTitleText("Raid Date")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_axis = QValueAxis()
    y_axis.setTitleText("Amount")
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    taken_pts = _parse_dates_and_values(trend_data, "total_damage_taken")
    mitigated_pts = _parse_dates_and_values(trend_data, "total_mitigated")

    all_pts = taken_pts + mitigated_pts
    _fit_axes(x_axis, y_axis, all_pts)

    _add_series(chart, taken_pts, "Damage Taken", 0, x_axis, y_axis)
    _add_series(chart, mitigated_pts, "Mitigated", 2, x_axis, y_axis)

    return make_chart_view(chart)


def build_tank_mitigation_chart(trend_data: list[dict]) -> QChartView:
    chart = _make_chart("Mitigation %")

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_axis = QValueAxis()
    y_axis.setTitleText("Mit%")
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    pts = _parse_dates_and_values(trend_data, "mitigation_percent")
    _fit_axes(x_axis, y_axis, pts)
    if pts:
        y_axis.setRange(0, min(100, max(v for _, v in pts) * 1.2))
    _add_series(chart, pts, "Mitigation %", 2, x_axis, y_axis)

    return make_chart_view(chart)


def build_dps_chart(trend_data: list[dict]) -> QChartView:
    chart = _make_chart("DPS Performance")

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    x_axis.setTitleText("Raid Date")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_axis = QValueAxis()
    y_axis.setTitleText("Total Damage")
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    damage_pts = _parse_dates_and_values(trend_data, "total_damage")

    _fit_axes(x_axis, y_axis, damage_pts)
    _add_series(chart, damage_pts, "Damage", 0, x_axis, y_axis)

    return make_chart_view(chart)


# ── Per-spell/ability multi-series charts ──

def _group_spell_data(spell_trend: list[dict], value_key: str,
                      top_n: int = 8, name_key: str = "spell_name",
                      ) -> dict[str, list[tuple[datetime, float]]]:
    """Group spell trend rows by name, keeping only the top N by total value."""
    totals: dict[str, float] = defaultdict(float)
    for row in spell_trend:
        totals[row.get(name_key, "") or row.get("spell_name", "")] += row.get(value_key, 0) or 0

    top_spells = sorted(totals, key=lambda s: totals[s], reverse=True)[:top_n]
    top_set = set(top_spells)

    series_data: dict[str, list[tuple[datetime, float]]] = {s: [] for s in top_spells}
    for row in reversed(spell_trend):
        name = row.get(name_key, "") or row.get("spell_name", "")
        if name not in top_set:
            continue
        date_str = row.get("raid_date", "")
        val = row.get(value_key, 0) or 0
        try:
            dt = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            continue
        series_data[name].append((dt, float(val)))

    return series_data


def build_spell_trend_chart(spell_trend: list[dict], value_key: str,
                            title: str, y_label: str) -> QChartView:
    """Build a multi-series chart with one line per spell/ability."""
    chart = _make_chart(title)

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_axis = QValueAxis()
    y_axis.setTitleText(y_label)
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    grouped = _group_spell_data(spell_trend, value_key)

    all_pts = []
    for i, (spell_name, points) in enumerate(grouped.items()):
        if not points:
            continue
        all_pts.extend(points)
        _add_series(chart, points, spell_name, i, x_axis, y_axis)

    _fit_axes(x_axis, y_axis, all_pts)

    return make_chart_view(chart)


def build_consumable_trend_chart(consumable_trend: list[dict]) -> QChartView:
    """Build a multi-series chart showing consumable usage over time."""
    chart = _make_chart("Consumable Usage Over Time")

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_axis = QValueAxis()
    y_axis.setTitleText("Count")
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    grouped = _group_spell_data(consumable_trend, "count",
                                top_n=10, name_key="consumable_name")

    all_pts = []
    for i, (name, points) in enumerate(grouped.items()):
        if not points:
            continue
        all_pts.extend(points)
        _add_series(chart, points, name, i, x_axis, y_axis)

    _fit_axes(x_axis, y_axis, all_pts)
    if all_pts:
        max_v = max(v for _, v in all_pts)
        y_axis.setRange(0, max(max_v * 1.1, 1))
        y_axis.setLabelFormat("%d")

    return make_chart_view(chart)
