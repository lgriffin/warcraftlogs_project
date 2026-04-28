"""
Raid Groups view — create and manage raid groups, assign characters,
view raids matching the group's scheduled days, and compare class performance.
"""

import json
import sqlite3

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QSplitter, QScrollArea,
    QCheckBox, QGroupBox, QMessageBox, QTableView, QHeaderView,
    QInputDialog, QTabWidget, QComboBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS
from .table_models import HistoryTableModel
from .charts import build_group_performance_chart, build_class_comparison_chart
from .raid_list_widget import RaidListWidget
from ..database import PerformanceDB


DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_ABBREV = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
              "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun"}
DAY_INDEX = {name: i for i, name in enumerate(DAYS_OF_WEEK)}


class RaidGroupView(QWidget):
    status_message = Signal(str)
    open_raid = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_group_id = None
        self._all_character_names = []
        self._comparison_chart_widget = None
        self._perf_chart_widget = None
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(COMMON_STYLES + f"""
            RaidGroupView, RaidGroupView QWidget {{
                background-color: {COLORS['bg_dark']};
            }}
            RaidGroupView QGroupBox {{
                background-color: {COLORS['bg_card']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QLabel("Raid Groups")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left panel: group list ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 8, 0)

        btn_row = QHBoxLayout()
        create_btn = QPushButton("  New Group  ")
        create_btn.clicked.connect(self._create_group)
        btn_row.addWidget(create_btn)

        self._delete_btn = QPushButton("  Delete  ")
        self._delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['error']};
                color: white; border: none; border-radius: 4px;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #c0392b; }}
        """)
        self._delete_btn.clicked.connect(self._delete_group)
        btn_row.addWidget(self._delete_btn)
        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        self._group_list = QListWidget()
        self._group_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px; font-size: 13px;
            }}
            QListWidget::item {{
                padding: 10px 14px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_dark']};
                border-left: 3px solid {COLORS['accent']};
            }}
        """)
        self._group_list.currentItemChanged.connect(self._on_group_selected)
        left_layout.addWidget(self._group_list)
        splitter.addWidget(left_panel)

        # ── Right panel: group detail ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(0)

        self._no_selection_label = QLabel("Select or create a raid group to get started.")
        self._no_selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_selection_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 14px; padding: 40px;")
        right_layout.addWidget(self._no_selection_label)

        # ── Fixed header: name + raid days ──
        self._header_widget = QWidget()
        header_layout = QVBoxLayout(self._header_widget)
        header_layout.setContentsMargins(0, 0, 0, 8)
        header_layout.setSpacing(8)

        name_row = QHBoxLayout()
        self._group_name_label = QLabel("")
        self._group_name_label.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        self._group_name_label.setStyleSheet(f"color: {COLORS['text_header']};")
        name_row.addWidget(self._group_name_label)

        rename_btn = QPushButton("Rename")
        rename_btn.setProperty("secondary", True)
        rename_btn.setFixedWidth(80)
        rename_btn.clicked.connect(self._rename_group)
        name_row.addWidget(rename_btn)
        name_row.addStretch()
        header_layout.addLayout(name_row)

        raid_size_row = QHBoxLayout()
        raid_size_label = QLabel("Raid Size:")
        raid_size_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
        raid_size_row.addWidget(raid_size_label)
        self._raid_size_combo = QComboBox()
        self._raid_size_combo.addItems(["All Raids", "10-man", "25-man"])
        self._raid_size_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px; padding: 4px 8px;
                font-size: 12px; min-width: 120px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                selection-background-color: {COLORS['bg_dark']};
            }}
        """)
        self._raid_size_combo.currentIndexChanged.connect(self._on_raid_size_changed)
        raid_size_row.addWidget(self._raid_size_combo)
        raid_size_row.addStretch()
        header_layout.addLayout(raid_size_row)

        days_row = QHBoxLayout()
        days_row.setSpacing(16)
        days_label = QLabel("Raid Days:")
        days_label.setStyleSheet(f"color: {COLORS['text']}; font-size: 13px; font-weight: bold;")
        days_row.addWidget(days_label)

        self._day_checkboxes = {}
        for day in DAYS_OF_WEEK:
            cb = QCheckBox(DAY_ABBREV[day])
            cb.setStyleSheet(f"""
                QCheckBox {{
                    font-size: 13px; color: {COLORS['text']}; spacing: 6px;
                }}
                QCheckBox::indicator {{ width: 18px; height: 18px; }}
            """)
            cb.toggled.connect(self._on_raid_days_changed)
            self._day_checkboxes[day] = cb
            days_row.addWidget(cb)
        days_row.addStretch()
        header_layout.addLayout(days_row)

        self._header_widget.setVisible(False)
        right_layout.addWidget(self._header_widget)

        # ── Tabbed content area ──
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_members_tab(), "Members")
        self._tabs.addTab(self._build_raids_tab(), "Raids")
        self._tabs.addTab(self._build_dashboard_tab(), "Dashboard")
        self._tabs.addTab(self._build_comparison_tab(), "Class Comparison")

        self._tabs.setVisible(False)
        right_layout.addWidget(self._tabs, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([260, 740])

        layout.addWidget(splitter, 1)

    # ── Tab builders ──

    def _build_members_tab(self) -> QWidget:
        widget = QWidget()
        members_layout = QVBoxLayout(widget)
        members_layout.setContentsMargins(8, 12, 8, 8)

        add_row = QHBoxLayout()
        self._member_search = QLineEdit()
        self._member_search.setPlaceholderText("Search characters to add...")
        self._member_search.textChanged.connect(self._filter_add_list)
        add_row.addWidget(self._member_search)

        self._add_btn = QPushButton("Add Selected")
        self._add_btn.setFixedWidth(120)
        self._add_btn.clicked.connect(self._add_member)
        add_row.addWidget(self._add_btn)
        members_layout.addLayout(add_row)

        member_splitter = QSplitter(Qt.Orientation.Horizontal)

        avail_panel = QWidget()
        avail_layout = QVBoxLayout(avail_panel)
        avail_layout.setContentsMargins(0, 0, 4, 0)
        avail_label = QLabel("Available Characters")
        avail_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        avail_layout.addWidget(avail_label)
        self._available_list = QListWidget()
        self._available_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._available_list.setMinimumHeight(150)
        self._available_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px; font-size: 12px;
            }}
            QListWidget::item {{ padding: 4px 8px; }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg_dark']};
            }}
        """)
        self._available_list.doubleClicked.connect(self._add_member)
        avail_layout.addWidget(self._available_list)
        member_splitter.addWidget(avail_panel)

        current_panel = QWidget()
        current_layout = QVBoxLayout(current_panel)
        current_layout.setContentsMargins(4, 0, 0, 0)
        current_label = QLabel("Group Members")
        current_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        current_layout.addWidget(current_label)
        self._members_list = QListWidget()
        self._members_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._members_list.setMinimumHeight(150)
        self._members_list.setStyleSheet(self._available_list.styleSheet())
        current_layout.addWidget(self._members_list)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px; padding: 6px 12px;
                font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS['border']}; }}
        """)
        remove_btn.clicked.connect(self._remove_member)
        current_layout.addWidget(remove_btn)
        member_splitter.addWidget(current_panel)

        member_splitter.setSizes([300, 300])
        members_layout.addWidget(member_splitter, 1)
        return widget

    def _build_raids_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 12, 8, 8)

        self._raids_list_widget = RaidListWidget()
        self._raids_list_widget.raid_selected.connect(self.open_raid.emit)
        self._raids_list_widget.status_message.connect(self.status_message.emit)
        layout.addWidget(self._raids_list_widget, 1)
        return widget

    def _build_dashboard_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        self._perf_chart_container = QVBoxLayout()
        layout.addLayout(self._perf_chart_container)

        dash_tables = QSplitter(Qt.Orientation.Horizontal)

        attend_panel = QWidget()
        attend_layout = QVBoxLayout(attend_panel)
        attend_layout.setContentsMargins(0, 0, 4, 0)
        attend_title = QLabel("Attendance")
        attend_title.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; font-weight: bold;")
        attend_layout.addWidget(attend_title)
        self._attendance_model = HistoryTableModel()
        attend_table = QTableView()
        attend_table.setModel(self._attendance_model)
        attend_table.setAlternatingRowColors(True)
        attend_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        attend_table.setSortingEnabled(True)
        attend_table.verticalHeader().setVisible(False)
        attend_table.horizontalHeader().setStretchLastSection(True)
        attend_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        attend_table.setStyleSheet(
            f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        attend_table.setMinimumHeight(180)
        attend_layout.addWidget(attend_table, 1)
        dash_tables.addWidget(attend_panel)

        role_panel = QWidget()
        role_layout = QVBoxLayout(role_panel)
        role_layout.setContentsMargins(4, 0, 0, 0)
        role_title = QLabel("Role Coverage")
        role_title.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px; font-weight: bold;")
        role_layout.addWidget(role_title)
        self._role_model = HistoryTableModel()
        role_table = QTableView()
        role_table.setModel(self._role_model)
        role_table.setAlternatingRowColors(True)
        role_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        role_table.setSortingEnabled(True)
        role_table.verticalHeader().setVisible(False)
        role_table.horizontalHeader().setStretchLastSection(True)
        role_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        role_table.setStyleSheet(
            f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        role_table.setMinimumHeight(180)
        role_layout.addWidget(role_table, 1)
        dash_tables.addWidget(role_panel)

        dash_tables.setSizes([400, 400])
        layout.addWidget(dash_tables, 1)
        return widget

    def _build_comparison_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        combo_style = f"""
            QComboBox {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px; padding: 4px 8px;
                font-size: 12px; min-width: 160px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                selection-background-color: {COLORS['bg_dark']};
            }}
        """

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Class:"))
        self._class_combo = QComboBox()
        self._class_combo.setStyleSheet(combo_style)
        self._class_combo.currentIndexChanged.connect(self._refresh_comparison)
        filter_row.addWidget(self._class_combo)

        filter_row.addSpacing(20)
        filter_row.addWidget(QLabel("Role:"))
        self._role_combo = QComboBox()
        self._role_combo.addItems(["Auto", "Healer", "Tank", "DPS"])
        self._role_combo.setStyleSheet(combo_style)
        self._role_combo.currentIndexChanged.connect(self._refresh_comparison)
        filter_row.addWidget(self._role_combo)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        self._comparison_tabs = QTabWidget()

        # Trends sub-tab
        trends_widget = QWidget()
        trends_layout = QVBoxLayout(trends_widget)
        trends_layout.setContentsMargins(0, 4, 0, 0)
        self._comparison_chart_container = QVBoxLayout()
        trends_layout.addLayout(self._comparison_chart_container)
        trends_layout.addStretch()
        self._comparison_tabs.addTab(trends_widget, "Trends")

        # Breakdown sub-tab
        breakdown_widget = QWidget()
        breakdown_layout = QVBoxLayout(breakdown_widget)
        breakdown_layout.setContentsMargins(0, 4, 0, 0)
        self._comparison_model = HistoryTableModel()
        comparison_table = QTableView()
        comparison_table.setModel(self._comparison_model)
        comparison_table.setAlternatingRowColors(True)
        comparison_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        comparison_table.setSortingEnabled(True)
        comparison_table.verticalHeader().setVisible(False)
        comparison_table.horizontalHeader().setStretchLastSection(True)
        comparison_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        comparison_table.setStyleSheet(
            f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        breakdown_layout.addWidget(comparison_table, 1)
        self._comparison_tabs.addTab(breakdown_widget, "Breakdown")

        layout.addWidget(self._comparison_tabs, 1)
        return widget

    # ── Group CRUD ──

    def _load_groups(self):
        self._group_list.clear()
        try:
            with PerformanceDB() as db:
                groups = db.get_all_raid_groups()
                self._all_character_names = [
                    c.name for c in db.get_all_characters()]
            for g in groups:
                days_str = ", ".join(DAY_ABBREV.get(d, d) for d in g.raid_days)
                label = f"{g.name}  ({len(g.members)} members)"
                if days_str:
                    label += f"  [{days_str}]"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, g.id)
                self._group_list.addItem(item)
        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            self.status_message.emit(f"Error loading groups: {e}")

    def _create_group(self):
        name, ok = QInputDialog.getText(
            self, "New Raid Group", "Group name:")
        if not ok or not name.strip():
            return
        try:
            with PerformanceDB() as db:
                db.create_raid_group(name.strip())
            self._load_groups()
            for i in range(self._group_list.count()):
                item = self._group_list.item(i)
                if name.strip() in item.text():
                    self._group_list.setCurrentItem(item)
                    break
            self.status_message.emit(f"Created raid group: {name.strip()}")
        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            QMessageBox.warning(self, "Error", f"Could not create group:\n{e}")

    def _delete_group(self):
        current = self._group_list.currentItem()
        if not current:
            return
        group_id = current.data(Qt.ItemDataRole.UserRole)
        name = current.text().split("  (")[0]

        reply = QMessageBox.question(
            self, "Delete Raid Group",
            f"Delete raid group \"{name}\"?\n\nThis will not delete any character data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            with PerformanceDB() as db:
                db.delete_raid_group(group_id)
            self._current_group_id = None
            self._header_widget.setVisible(False)
            self._tabs.setVisible(False)
            self._no_selection_label.setVisible(True)
            self._load_groups()
            self.status_message.emit(f"Deleted raid group: {name}")
        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            QMessageBox.critical(self, "Error", f"Failed to delete group:\n{e}")

    def _rename_group(self):
        if not self._current_group_id:
            return
        name, ok = QInputDialog.getText(
            self, "Rename Raid Group", "New name:",
            text=self._group_name_label.text())
        if not ok or not name.strip():
            return
        try:
            with PerformanceDB() as db:
                db.update_raid_group(self._current_group_id, name=name.strip())
            self._group_name_label.setText(name.strip())
            self._load_groups()
            for i in range(self._group_list.count()):
                item = self._group_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_group_id:
                    self._group_list.setCurrentItem(item)
                    break
            self.status_message.emit(f"Renamed group to: {name.strip()}")
        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            QMessageBox.warning(self, "Error", f"Could not rename:\n{e}")

    # ── Group selection ──

    def _on_group_selected(self, current, previous):
        if not current:
            return
        group_id = current.data(Qt.ItemDataRole.UserRole)
        self._show_group(group_id)

    def _show_group(self, group_id: int):
        try:
            with PerformanceDB() as db:
                group = db.get_raid_group(group_id)
                self._all_character_names = [
                    c.name for c in db.get_all_characters()]
            if not group:
                return

            self._current_group_id = group_id
            self._no_selection_label.setVisible(False)
            self._header_widget.setVisible(True)
            self._tabs.setVisible(True)

            self._group_name_label.setText(group.name)

            for day, cb in self._day_checkboxes.items():
                cb.blockSignals(True)
                cb.setChecked(day in group.raid_days)
                cb.blockSignals(False)

            self._members_list.clear()
            for name in group.members:
                self._members_list.addItem(name)

            self._refresh_available_list(group.members)
            self._load_raids_for_group(group.raid_days)
            self._load_dashboard(group_id)
            self._load_class_list(group_id)
        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            self.status_message.emit(f"Error loading group: {e}")

    def _refresh_available_list(self, current_members: list[str]):
        self._available_list.clear()
        member_set = set(current_members)
        search = self._member_search.text().lower()
        for name in self._all_character_names:
            if name not in member_set:
                if not search or search in name.lower():
                    self._available_list.addItem(name)

    def _filter_add_list(self, text: str):
        current_members = [
            self._members_list.item(i).text()
            for i in range(self._members_list.count())
        ]
        self._refresh_available_list(current_members)

    # ── Member management ──

    def _add_member(self):
        if not self._current_group_id:
            return
        selected = self._available_list.selectedItems()
        if not selected:
            return
        try:
            with PerformanceDB() as db:
                for item in selected:
                    db.add_raid_group_member(self._current_group_id, item.text())
            self._show_group(self._current_group_id)
            self._refresh_group_list_label()
            self.status_message.emit(f"Added {len(selected)} member(s)")
        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            QMessageBox.warning(self, "Error", f"Could not add member:\n{e}")

    def _remove_member(self):
        if not self._current_group_id:
            return
        selected = self._members_list.selectedItems()
        if not selected:
            return
        try:
            with PerformanceDB() as db:
                for item in selected:
                    db.remove_raid_group_member(self._current_group_id, item.text())
            self._show_group(self._current_group_id)
            self._refresh_group_list_label()
            self.status_message.emit(f"Removed {len(selected)} member(s)")
        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            QMessageBox.warning(self, "Error", f"Could not remove member:\n{e}")

    def _refresh_group_list_label(self):
        self._load_groups()
        for i in range(self._group_list.count()):
            item = self._group_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self._current_group_id:
                self._group_list.blockSignals(True)
                self._group_list.setCurrentItem(item)
                self._group_list.blockSignals(False)
                break

    # ── Raid size filtering ──

    @staticmethod
    def _filter_by_raid_size(rows: list[dict], mode: int) -> list[dict]:
        if mode == 0:
            return rows
        if mode == 1:
            return [r for r in rows if r.get("raid_size") is not None and r["raid_size"] <= 15]
        return [r for r in rows if r.get("raid_size") is not None and r["raid_size"] > 15]

    def _on_raid_size_changed(self):
        if self._current_group_id:
            self._load_dashboard(self._current_group_id)
            self._refresh_comparison()

    # ── Dashboard ──

    def _load_dashboard(self, group_id: int):
        try:
            with PerformanceDB() as db:
                perf_trend = db.get_group_performance_trend(group_id)
                attendance = db.get_group_attendance(group_id)
                role_coverage = db.get_group_role_coverage(group_id)

            mode = self._raid_size_combo.currentIndex()
            perf_trend = self._filter_by_raid_size(perf_trend, mode)

            if self._perf_chart_widget:
                self._perf_chart_container.removeWidget(self._perf_chart_widget)
                self._perf_chart_widget.deleteLater()
                self._perf_chart_widget = None

            if perf_trend:
                self._perf_chart_widget = build_group_performance_chart(perf_trend)
                self._perf_chart_container.addWidget(self._perf_chart_widget)

            if attendance:
                self._attendance_model.set_data(
                    attendance,
                    ["name", "player_class", "attended", "total_raids", "attendance_pct"])
            else:
                self._attendance_model.set_data([], [])

            if role_coverage:
                self._role_model.set_data(
                    role_coverage,
                    ["name", "player_class", "healer", "tank", "dps"])
            else:
                self._role_model.set_data([], [])

        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            self.status_message.emit(f"Error loading dashboard: {e}")

    # ── Raids ──

    def _load_raids_for_group(self, raid_days: list[str]):
        if not raid_days:
            self._raids_list_widget.load_raids(raids=[])
            return
        day_names = [d for d in raid_days if d in DAYS_OF_WEEK]
        self._raids_list_widget.set_day_filter(day_names)
        self._raids_list_widget.load_raids()

    # ── Raid days ──

    def _on_raid_days_changed(self):
        if not self._current_group_id:
            return
        days = [day for day, cb in self._day_checkboxes.items() if cb.isChecked()]
        try:
            with PerformanceDB() as db:
                db.update_raid_group(self._current_group_id, raid_days=days)
            self._load_raids_for_group(days)
            self._refresh_group_list_label()
        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            self.status_message.emit(f"Error saving raid days: {e}")

    # ── Class comparison ──

    def _load_class_list(self, group_id: int):
        self._class_combo.blockSignals(True)
        current = self._class_combo.currentText()
        self._class_combo.clear()
        try:
            with PerformanceDB() as db:
                classes = db.get_group_classes(group_id)
            for cls in classes:
                self._class_combo.addItem(cls)
            idx = self._class_combo.findText(current)
            if idx >= 0:
                self._class_combo.setCurrentIndex(idx)
        except (sqlite3.Error, KeyError, ValueError, TypeError):
            pass
        self._class_combo.blockSignals(False)
        self._refresh_comparison()

    def _refresh_comparison(self):
        if not self._current_group_id:
            return
        class_name = self._class_combo.currentText()
        if not class_name:
            self._comparison_model.set_data([], [])
            self._clear_comparison_chart()
            return

        role_text = self._role_combo.currentText()
        role = None if role_text == "Auto" else role_text.lower()

        try:
            with PerformanceDB() as db:
                trend_data = db.get_class_comparison_trend(
                    self._current_group_id, class_name, role=role)
                summary = db.get_class_comparison_summary(
                    self._current_group_id, class_name)

            mode = self._raid_size_combo.currentIndex()
            trend_data = self._filter_by_raid_size(trend_data, mode)

            self._clear_comparison_chart()
            if trend_data:
                metric_keys = {r["metric_key"] for r in trend_data}
                metric_key = metric_keys.pop() if len(metric_keys) == 1 else "damage"
                chart = build_class_comparison_chart(trend_data, metric_key)
                self._comparison_chart_widget = chart
                self._comparison_chart_container.addWidget(chart)

            if summary:
                metric_key = summary[0].get("metric_key", "")
                metric_label = {
                    "healing": "Avg Healing",
                    "damage": "Avg Damage",
                    "mitigation": "Avg Mitigation %",
                }.get(metric_key, "Avg Performance")

                rows = []
                for s in summary:
                    rows.append({
                        "Name": s["name"],
                        "Class": s["player_class"],
                        "Raids": s["raids"],
                        metric_label: (
                            f"{s['avg_performance']:,.0f}"
                            if metric_key != "mitigation"
                            else f"{s['avg_performance']:.1f}%"
                        ),
                        "Best": (
                            f"{s['best']:,.0f}"
                            if metric_key != "mitigation"
                            else f"{s['best']:.1f}%"
                        ),
                        "Worst": (
                            f"{s['worst']:,.0f}"
                            if metric_key != "mitigation"
                            else f"{s['worst']:.1f}%"
                        ),
                        "Consistency": f"{s['consistency']:.1f}%",
                        "Consumes/Raid": s["consumable_compliance"],
                    })
                cols = ["Name", "Class", "Raids", metric_label,
                        "Best", "Worst", "Consistency", "Consumes/Raid"]
                self._comparison_model.set_data(rows, cols)
            else:
                self._comparison_model.set_data([], [])

        except (sqlite3.Error, KeyError, ValueError, TypeError) as e:
            self.status_message.emit(f"Error loading comparison: {e}")

    def _clear_comparison_chart(self):
        if self._comparison_chart_widget:
            self._comparison_chart_container.removeWidget(self._comparison_chart_widget)
            self._comparison_chart_widget.deleteLater()
            self._comparison_chart_widget = None

    # ── Lifecycle ──

    def showEvent(self, event):
        super().showEvent(event)
        self._load_groups()
