"""
Raid Groups view — create and manage raid groups, assign characters,
and view raids matching the group's scheduled days.
"""

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QSplitter,
    QCheckBox, QGroupBox, QMessageBox, QTableView, QHeaderView,
    QInputDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS
from .table_models import HistoryTableModel
from ..database import PerformanceDB


DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_ABBREV = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
              "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun"}
DAY_INDEX = {name: i for i, name in enumerate(DAYS_OF_WEEK)}


class RaidGroupView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMMON_STYLES)
        self._current_group_id = None
        self._all_character_names = []
        self._build_ui()

    def _build_ui(self):
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

        self._no_selection_label = QLabel("Select or create a raid group to get started.")
        self._no_selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_selection_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 14px; padding: 40px;")
        right_layout.addWidget(self._no_selection_label)

        self._detail_widget = QWidget()
        detail_layout = QVBoxLayout(self._detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(12)

        # Group name header
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
        detail_layout.addLayout(name_row)

        # Raid days
        days_group = QGroupBox("Raid Days")
        days_layout = QHBoxLayout(days_group)
        days_layout.setSpacing(12)

        self._day_checkboxes = {}
        for day in DAYS_OF_WEEK:
            cb = QCheckBox(DAY_ABBREV[day])
            cb.setStyleSheet("font-size: 12px;")
            cb.toggled.connect(self._on_raid_days_changed)
            self._day_checkboxes[day] = cb
            days_layout.addWidget(cb)
        days_layout.addStretch()
        detail_layout.addWidget(days_group)

        # Members section
        members_group = QGroupBox("Members")
        members_layout = QVBoxLayout(members_group)

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

        # Available characters
        avail_panel = QWidget()
        avail_layout = QVBoxLayout(avail_panel)
        avail_layout.setContentsMargins(0, 0, 4, 0)
        avail_label = QLabel("Available Characters")
        avail_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        avail_layout.addWidget(avail_label)
        self._available_list = QListWidget()
        self._available_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
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

        # Current members
        current_panel = QWidget()
        current_layout = QVBoxLayout(current_panel)
        current_layout.setContentsMargins(4, 0, 0, 0)
        current_label = QLabel("Group Members")
        current_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        current_layout.addWidget(current_label)
        self._members_list = QListWidget()
        self._members_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
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
        detail_layout.addWidget(members_group, 1)

        # Matching raids section
        raids_group = QGroupBox("Raids on Group Days")
        raids_layout = QVBoxLayout(raids_group)
        self._matching_raids_model = HistoryTableModel()
        raids_table = QTableView()
        raids_table.setModel(self._matching_raids_model)
        raids_table.setAlternatingRowColors(True)
        raids_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        raids_table.verticalHeader().setVisible(False)
        raids_table.horizontalHeader().setStretchLastSection(True)
        raids_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        raids_table.setStyleSheet(
            f"QTableView {{ alternate-background-color: {COLORS['bg_dark']}; }}")
        raids_table.setMaximumHeight(220)
        raids_layout.addWidget(raids_table)
        detail_layout.addWidget(raids_group)

        self._detail_widget.setVisible(False)
        right_layout.addWidget(self._detail_widget, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([260, 740])

        layout.addWidget(splitter, 1)

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
        except Exception as e:
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
        except Exception as e:
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
            self._detail_widget.setVisible(False)
            self._no_selection_label.setVisible(True)
            self._load_groups()
            self.status_message.emit(f"Deleted raid group: {name}")
        except Exception as e:
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
        except Exception as e:
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
            self._detail_widget.setVisible(True)

            self._group_name_label.setText(group.name)

            for day, cb in self._day_checkboxes.items():
                cb.blockSignals(True)
                cb.setChecked(day in group.raid_days)
                cb.blockSignals(False)

            self._members_list.clear()
            for name in group.members:
                self._members_list.addItem(name)

            self._refresh_available_list(group.members)
            self._load_matching_raids(group.raid_days)
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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

    # ── Raid days ──

    def _on_raid_days_changed(self):
        if not self._current_group_id:
            return
        days = [day for day, cb in self._day_checkboxes.items() if cb.isChecked()]
        try:
            with PerformanceDB() as db:
                db.update_raid_group(self._current_group_id, raid_days=days)
            self._load_matching_raids(days)
            self._refresh_group_list_label()
        except Exception as e:
            self.status_message.emit(f"Error saving raid days: {e}")

    def _load_matching_raids(self, raid_days: list[str]):
        if not raid_days:
            self._matching_raids_model.set_data([], [])
            return
        try:
            allowed_indices = {DAY_INDEX[d] for d in raid_days if d in DAY_INDEX}
            with PerformanceDB() as db:
                all_raids = db.get_raid_list(limit=200)

            matching = []
            for raid in all_raids:
                from datetime import datetime
                try:
                    dt = datetime.fromisoformat(raid["raid_date"])
                    if dt.weekday() in allowed_indices:
                        matching.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "day": dt.strftime("%A"),
                            "title": raid["title"],
                            "report_id": raid["report_id"],
                        })
                except (ValueError, TypeError):
                    continue

            cols = ["date", "day", "title", "report_id"]
            self._matching_raids_model.set_data(matching, cols)
        except Exception as e:
            self.status_message.emit(f"Error loading matching raids: {e}")

    # ── Lifecycle ──

    def showEvent(self, event):
        super().showEvent(event)
        self._load_groups()
