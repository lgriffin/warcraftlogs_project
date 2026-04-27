"""
Reusable chart widgets for performance trends using PySide6.QtCharts.
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta

from PySide6.QtCharts import (
    QChart, QChartView, QLineSeries, QValueAxis, QDateTimeAxis,
)
from PySide6.QtCore import Qt, QDateTime, QPointF, QMargins, QRectF
from PySide6.QtGui import QPen, QColor, QPainter, QFont, QBrush, QPainterPath
from PySide6.QtWidgets import QWidget, QToolTip

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


# ── Spider / Radar chart ──

class SpiderChartWidget(QWidget):
    """Custom-painted radar chart for multi-dimensional character comparison."""

    LABELS = ["Healing", "Damage", "Mitigation", "Activity", "Consumables", "Consistency"]
    KEYS = ["healing", "damage", "mitigation", "activity", "consumables", "consistency"]
    DESCRIPTIONS = {
        "healing": "Percentile rank of average healing output compared to all tracked characters.",
        "damage": "Percentile rank of average damage output compared to all tracked characters.",
        "mitigation": "Percentile rank of average damage mitigation compared to all tracked tanks.",
        "activity": "Percentile rank of total raids attended compared to all tracked characters.",
        "consumables": "Percentile rank of total consumables used compared to all tracked characters.",
        "consistency": "How stable performance is across raids (100 = identical every raid, lower = more variance).",
    }

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data = data
        self._label_rects: list[tuple[QRectF, str]] = []
        self.setMinimumHeight(280)
        self.setMinimumWidth(280)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 40
        n = len(self.LABELS)
        angles = [2 * math.pi * i / n - math.pi / 2 for i in range(n)]

        painter.fillRect(self.rect(), QColor(COLORS["bg_card"]))

        grid_pen = QPen(QColor(COLORS["border"]))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)

        for ring in [0.25, 0.5, 0.75, 1.0]:
            path = QPainterPath()
            r = radius * ring
            for i, angle in enumerate(angles):
                x = cx + r * math.cos(angle)
                y = cy + r * math.sin(angle)
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            path.closeSubpath()
            painter.drawPath(path)

        for angle in angles:
            painter.drawLine(
                QPointF(cx, cy),
                QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

        label_font = QFont("Segoe UI", 9)
        painter.setFont(label_font)
        painter.setPen(QColor(COLORS["text"]))
        fm = painter.fontMetrics()

        self._label_rects = []
        for i, (angle, label) in enumerate(zip(angles, self.LABELS)):
            val = self._data.get(self.KEYS[i], 0)
            text = f"{label} ({val})"
            tw = fm.horizontalAdvance(text)
            th = fm.height()
            lx = cx + (radius + 20) * math.cos(angle) - tw / 2
            ly = cy + (radius + 20) * math.sin(angle) + th / 4
            painter.drawText(QPointF(lx, ly), text)
            self._label_rects.append((QRectF(lx, ly - th, tw, th + 4), self.KEYS[i]))

        values = [self._data.get(k, 0) / 100.0 for k in self.KEYS]
        if any(v > 0 for v in values):
            fill_path = QPainterPath()
            for i, (angle, val) in enumerate(zip(angles, values)):
                r = radius * max(val, 0.02)
                x = cx + r * math.cos(angle)
                y = cy + r * math.sin(angle)
                if i == 0:
                    fill_path.moveTo(x, y)
                else:
                    fill_path.lineTo(x, y)
            fill_path.closeSubpath()

            fill_color = QColor(SERIES_COLORS[0])
            fill_color.setAlpha(60)
            painter.setBrush(QBrush(fill_color))
            border_pen = QPen(SERIES_COLORS[0])
            border_pen.setWidth(2)
            painter.setPen(border_pen)
            painter.drawPath(fill_path)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(SERIES_COLORS[0]))
            for i, (angle, val) in enumerate(zip(angles, values)):
                r = radius * max(val, 0.02)
                x = cx + r * math.cos(angle)
                y = cy + r * math.sin(angle)
                painter.drawEllipse(QPointF(x, y), 4, 4)

        painter.end()

    def mouseMoveEvent(self, event):
        pos = event.position()
        for rect, key in self._label_rects:
            if rect.contains(pos):
                val = self._data.get(key, 0)
                desc = self.DESCRIPTIONS.get(key, "")
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"<b>{key.title()}: {val}/100</b><br>{desc}",
                    self,
                )
                return
        QToolTip.hideText()


# ── Calendar Heatmap ──

class CalendarHeatmapWidget(QWidget):
    """GitHub-style contribution heatmap colored by raid performance."""

    def __init__(self, raid_data: list[dict], parent=None):
        super().__init__(parent)
        self._raid_data = raid_data
        self._cells: list[tuple[QRectF, str, dict | None]] = []
        self.setMinimumHeight(160)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS["bg_card"]))

        if not self._raid_data:
            painter.setPen(QColor(COLORS["text_dim"]))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No raid data")
            painter.end()
            return

        date_map = {}
        for row in self._raid_data:
            try:
                dt = datetime.fromisoformat(row["raid_date"])
                key = dt.strftime("%Y-%m-%d")
                date_map[key] = row
            except (ValueError, TypeError):
                continue

        if not date_map:
            painter.end()
            return

        all_dates = sorted(date_map.keys())
        end_date = datetime.fromisoformat(all_dates[-1])
        start_date = end_date - timedelta(weeks=25)

        cell_size = 14
        gap = 2
        step = cell_size + gap
        left_margin = 32
        top_margin = 24

        painter.setPen(QColor(COLORS["text_dim"]))
        painter.setFont(QFont("Segoe UI", 8))
        day_labels = ["M", "", "W", "", "F", "", "S"]
        for i, lbl in enumerate(day_labels):
            if lbl:
                y = top_margin + i * step + cell_size - 2
                painter.drawText(2, int(y), lbl)

        self._cells = []
        current = start_date - timedelta(days=start_date.weekday())
        col = 0
        month_labels_drawn = set()

        while current <= end_date + timedelta(days=6):
            for row_idx in range(7):
                day = current + timedelta(days=row_idx)
                if day > end_date + timedelta(days=1):
                    break

                key = day.strftime("%Y-%m-%d")
                x = left_margin + col * step
                y = top_margin + row_idx * step
                rect = QRectF(x, y, cell_size, cell_size)

                raid = date_map.get(key)
                if raid:
                    healing = raid.get("total_healing") or 0
                    damage = raid.get("total_damage") or 0
                    mitigation = raid.get("mitigation_percent") or 0
                    score = max(healing, damage, mitigation * 10000)

                    all_scores = []
                    for r in self._raid_data:
                        h = r.get("total_healing") or 0
                        d = r.get("total_damage") or 0
                        m = (r.get("mitigation_percent") or 0) * 10000
                        all_scores.append(max(h, d, m))

                    max_score = max(all_scores) if all_scores else 1
                    intensity = score / max_score if max_score > 0 else 0

                    if intensity > 0.75:
                        color = QColor("#2ecc71")
                    elif intensity > 0.5:
                        color = QColor("#69CCF0")
                    elif intensity > 0.25:
                        color = QColor("#f39c12")
                    else:
                        color = QColor("#e94560")

                    self._cells.append((rect, key, raid))
                else:
                    color = QColor(COLORS["bg_dark"])
                    self._cells.append((rect, key, None))

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))
                painter.drawRoundedRect(rect, 2, 2)

                month_key = day.strftime("%Y-%m")
                if month_key not in month_labels_drawn and day.day <= 7:
                    painter.setPen(QColor(COLORS["text_dim"]))
                    painter.setFont(QFont("Segoe UI", 8))
                    painter.drawText(int(x), top_margin - 6, day.strftime("%b"))
                    month_labels_drawn.add(month_key)

            current += timedelta(weeks=1)
            col += 1

        painter.end()

    def mouseMoveEvent(self, event):
        pos = event.position() if hasattr(event, 'position') else event.pos()
        for rect, date_str, raid in self._cells:
            if rect.contains(pos):
                if raid:
                    title = raid.get("title", "")
                    h = raid.get("total_healing") or 0
                    d = raid.get("total_damage") or 0
                    m = raid.get("mitigation_percent") or 0
                    parts = [f"{date_str}  {title}"]
                    if h:
                        parts.append(f"Healing: {h:,}")
                    if d:
                        parts.append(f"Damage: {d:,}")
                    if m:
                        parts.append(f"Mitigation: {m:.1f}%")
                    tip_pos = (event.globalPosition().toPoint()
                               if hasattr(event, 'globalPosition')
                               else event.globalPos())
                    QToolTip.showText(tip_pos, "\n".join(parts), self)
                else:
                    tip_pos = (event.globalPosition().toPoint()
                               if hasattr(event, 'globalPosition')
                               else event.globalPos())
                    QToolTip.showText(tip_pos, f"{date_str}: No raid", self)
                return
        QToolTip.hideText()
        super().mouseMoveEvent(event)


# ── Group Performance chart ──

def build_group_performance_chart(trend_data: list[dict]) -> QChartView:
    chart = _make_chart("Group Performance Over Time")

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    x_axis.setTitleText("Raid Date")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_axis = QValueAxis()
    y_axis.setTitleText("Average")
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    healing_pts = _parse_dates_and_values(trend_data, "avg_healing")
    damage_pts = _parse_dates_and_values(trend_data, "avg_damage")

    all_pts = healing_pts + damage_pts
    _fit_axes(x_axis, y_axis, all_pts)

    if healing_pts:
        _add_series(chart, healing_pts, "Avg Healing", 0, x_axis, y_axis)
    if damage_pts:
        _add_series(chart, damage_pts, "Avg Damage", 2, x_axis, y_axis)

    members_pts = _parse_dates_and_values(trend_data, "members_present")
    if members_pts:
        y2 = QValueAxis()
        y2.setTitleText("Members")
        _style_axis(y2)
        chart.addAxis(y2, Qt.AlignmentFlag.AlignRight)
        max_m = max(v for _, v in members_pts)
        y2.setRange(0, max_m + 2)
        y2.setLabelFormat("%d")
        _add_series(chart, members_pts, "Members Present", 3, x_axis, y2)

    return make_chart_view(chart)


def build_class_comparison_chart(trend_data: list[dict], metric_key: str) -> QChartView:
    """Multi-series line chart with one line per player for class comparison."""
    title_map = {
        "healing": "Healing Comparison",
        "damage": "Damage Comparison",
        "mitigation": "Mitigation % Comparison",
    }
    chart = _make_chart(title_map.get(metric_key, "Class Comparison"))

    x_axis = QDateTimeAxis()
    x_axis.setFormat("MM/dd")
    x_axis.setTitleText("Raid Date")
    _style_axis(x_axis)
    chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

    y_label = {
        "healing": "Total Healing",
        "damage": "Total Damage",
        "mitigation": "Mitigation %",
    }
    y_axis = QValueAxis()
    y_axis.setTitleText(y_label.get(metric_key, "Value"))
    _style_axis(y_axis)
    chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

    by_player: dict[str, list[tuple[datetime, float]]] = {}
    for row in trend_data:
        if row.get("metric_key") != metric_key:
            continue
        name = row["name"]
        date_str = row.get("raid_date", "")
        val = row.get("metric_value", 0) or 0
        try:
            dt = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            continue
        by_player.setdefault(name, []).append((dt, float(val)))

    all_pts = []
    for i, (name, pts) in enumerate(sorted(by_player.items())):
        pts.sort(key=lambda p: p[0])
        all_pts.extend(pts)
        _add_series(chart, pts, name, i, x_axis, y_axis)

    _fit_axes(x_axis, y_axis, all_pts)
    return make_chart_view(chart)
