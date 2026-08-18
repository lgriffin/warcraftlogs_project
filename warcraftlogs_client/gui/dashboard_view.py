"""
Dashboard — landing page with at-a-glance stats and recent raids.
"""

import sqlite3
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..database import PerformanceDB
from .styles import CLASS_COLORS, COLORS, COMMON_STYLES


class _StatCard(QFrame):
    def __init__(self, title: str, value: str = "-", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            _StatCard {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-top: 3px solid {COLORS['accent']};
                border-radius: 6px;
                padding: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self._title = QLabel(title)
        self._title.setFont(QFont("Segoe UI", 10))
        self._title.setStyleSheet(f"color: {COLORS['text_dim']}; border: none;")
        layout.addWidget(self._title)

        self._value = QLabel(value)
        self._value.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self._value.setStyleSheet(f"color: {COLORS['text_gold']}; border: none;")
        layout.addWidget(self._value)

    def set_value(self, value: str):
        self._value.setText(value)


class DashboardView(QWidget):
    status_message = Signal(str)
    open_raid = Signal(str)
    navigate_to_raids = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded = False
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(
            COMMON_STYLES
            + f"""
            DashboardView, DashboardView QWidget {{
                background-color: {COLORS["bg_dark"]};
            }}
        """
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(20)

        header = QLabel("Dashboard")
        header.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_gold']}; background: transparent;")
        outer.addWidget(header)

        # Stat cards row
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        self._raids_card = _StatCard("Total Raids")
        self._characters_card = _StatCard("Characters Tracked")
        self._last_raid_card = _StatCard("Last Raid")
        self._days_since_card = _StatCard("Days Since Last Raid")
        for card in [self._raids_card, self._characters_card, self._last_raid_card, self._days_since_card]:
            cards_row.addWidget(card)
        outer.addLayout(cards_row)

        # Last raid summary
        summary_header = QLabel("Last Raid Summary")
        summary_header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        summary_header.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
        outer.addWidget(summary_header)

        self._last_raid_summary = QFrame()
        self._last_raid_summary.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 16px;
            }}
        """)
        summary_layout = QGridLayout(self._last_raid_summary)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.setSpacing(12)

        self._summary_labels = {}
        metrics = [
            ("Title", 0, 0),
            ("Date", 0, 2),
            ("Duration", 1, 0),
            ("Total Damage", 1, 2),
            ("Total Healing", 2, 0),
            ("Raid Size", 2, 2),
        ]
        for name, row, col in metrics:
            label = QLabel(name)
            label.setFont(QFont("Segoe UI", 10))
            label.setStyleSheet(f"color: {COLORS['text_dim']}; border: none;")
            summary_layout.addWidget(label, row, col)

            val = QLabel("-")
            val.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            val.setStyleSheet(f"color: {COLORS['text']}; border: none;")
            summary_layout.addWidget(val, row, col + 1)
            self._summary_labels[name] = val

        outer.addWidget(self._last_raid_summary)

        # Recent raids list
        recent_header_row = QHBoxLayout()
        recent_header = QLabel("Recent Raids")
        recent_header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        recent_header.setStyleSheet(f"color: {COLORS['text_header']}; background: transparent;")
        recent_header_row.addWidget(recent_header)
        recent_header_row.addStretch()
        view_all_btn = QPushButton("View All Raids")
        view_all_btn.setProperty("secondary", True)
        view_all_btn.clicked.connect(self.navigate_to_raids)
        recent_header_row.addWidget(view_all_btn)
        outer.addLayout(recent_header_row)

        self._recent_list = QListWidget()
        self._recent_list.setMaximumHeight(320)
        self._recent_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 10px 16px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_hover']};
                color: {COLORS['text_gold']};
            }}
            QListWidget::item:hover:!selected {{
                background-color: {COLORS['bg_input']};
            }}
        """)
        self._recent_list.itemDoubleClicked.connect(self._on_raid_double_clicked)
        outer.addWidget(self._recent_list)

        outer.addStretch()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._load_data()

    def _load_data(self):
        try:
            with PerformanceDB() as db:
                aggregates = db.get_comparison_aggregates(source="guild")
                raids = db.get_raid_list(limit=10)
                attendance = db.get_attendance_stats(min_raids=1)

                last_raid_stats = None
                if raids:
                    last_raid_stats = db.get_raid_aggregate_stats(raids[0]["report_id"])
        except (sqlite3.Error, OSError) as e:
            self.status_message.emit(f"Dashboard error: {e}")
            return

        raid_count = aggregates.get("raid_count", 0) if aggregates else 0
        char_count = len(attendance) if attendance else 0

        self._raids_card.set_value(str(raid_count))
        self._characters_card.set_value(str(char_count))

        if raids:
            last_date_str = raids[0].get("raid_date", "")
            try:
                last_date = datetime.fromisoformat(last_date_str)
                self._last_raid_card.set_value(last_date.strftime("%b %d, %Y"))
                days = (datetime.now() - last_date).days
                self._days_since_card.set_value(str(days))
            except (ValueError, TypeError):
                self._last_raid_card.set_value(last_date_str[:10] if last_date_str else "-")
                self._days_since_card.set_value("-")
        else:
            self._last_raid_card.set_value("-")
            self._days_since_card.set_value("-")

        if last_raid_stats:
            self._summary_labels["Title"].setText(last_raid_stats.get("title", "-"))
            date_str = last_raid_stats.get("raid_date", "")
            try:
                dt = datetime.fromisoformat(date_str)
                self._summary_labels["Date"].setText(dt.strftime("%A, %b %d %Y"))
            except (ValueError, TypeError):
                self._summary_labels["Date"].setText(date_str[:10] if date_str else "-")
            dur_ms = last_raid_stats.get("duration_ms", 0) or 0
            dur_s = dur_ms // 1000
            self._summary_labels["Duration"].setText(f"{dur_s // 60}m {dur_s % 60}s")
            self._summary_labels["Total Damage"].setText(f"{last_raid_stats.get('total_damage', 0):,}")
            self._summary_labels["Total Healing"].setText(f"{last_raid_stats.get('total_healing', 0):,}")
            self._summary_labels["Raid Size"].setText(str(last_raid_stats.get("raid_size", "-")))

        self._recent_list.clear()
        for raid in raids:
            date_str = raid.get("raid_date", "")
            try:
                dt = datetime.fromisoformat(date_str)
                display_date = dt.strftime("%b %d")
            except (ValueError, TypeError):
                display_date = date_str[:10] if date_str else "?"
            title = raid.get("title", "Unknown")
            item = QListWidgetItem(f"{display_date}    {title}")
            item.setData(Qt.ItemDataRole.UserRole, raid["report_id"])
            self._recent_list.addItem(item)

        self.status_message.emit("Dashboard loaded")

    def _on_raid_double_clicked(self, item: QListWidgetItem):
        report_id = item.data(Qt.ItemDataRole.UserRole)
        if report_id:
            self.open_raid.emit(report_id)
