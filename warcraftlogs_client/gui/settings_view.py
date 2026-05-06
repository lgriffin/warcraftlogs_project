"""
Settings view — configure credentials, thresholds, and database.
"""

import json
import os
import sqlite3

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QSpinBox, QMessageBox, QFormLayout,
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont

from .styles import COMMON_STYLES, COLORS


class SettingsView(QWidget):
    status_message = Signal(str)

    from .. import paths as _paths
    CONFIG_PATH = str(_paths.get_config_path())

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(COMMON_STYLES)
        self._build_ui()
        self._load_current_config()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {COLORS['bg_dark']}; }}
            QScrollArea > QWidget > QWidget {{ background-color: {COLORS['bg_dark']}; }}
        """)
        outer.addWidget(scroll)

        container = QWidget()
        container.setStyleSheet(f"background-color: {COLORS['bg_dark']};")
        scroll.setWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QLabel("Settings")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['text_header']};")
        layout.addWidget(header)

        # ── API Credentials ──
        creds_group = QGroupBox("WarcraftLogs API Credentials")
        creds_layout = QFormLayout(creds_group)
        creds_layout.setSpacing(12)
        creds_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.client_id_input = QLineEdit()
        self.client_id_input.setPlaceholderText("Client ID from WarcraftLogs")
        creds_layout.addRow("Client ID:", self.client_id_input)

        self.client_secret_input = QLineEdit()
        self.client_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.client_secret_input.setPlaceholderText("Client Secret")
        creds_layout.addRow("Client Secret:", self.client_secret_input)

        self.report_id_input = QLineEdit()
        self.report_id_input.setPlaceholderText("Default report ID")
        creds_layout.addRow("Default Report ID:", self.report_id_input)

        self.guild_id_input = QLineEdit()
        self.guild_id_input.setPlaceholderText("e.g. 774065")
        creds_layout.addRow("Guild ID:", self.guild_id_input)

        self.guild_name_input = QLineEdit()
        self.guild_name_input.setPlaceholderText("e.g. Amicable")
        creds_layout.addRow("Guild Name:", self.guild_name_input)

        self.guild_server_input = QLineEdit()
        self.guild_server_input.setPlaceholderText("e.g. Gehennas")
        creds_layout.addRow("Guild Server:", self.guild_server_input)

        # Show/hide secret toggle
        self.show_secret_btn = QPushButton("Show")
        self.show_secret_btn.setFixedWidth(80)
        self.show_secret_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['border']};
            }}
        """)
        self.show_secret_btn.clicked.connect(self._toggle_secret_visibility)
        creds_layout.addRow("", self.show_secret_btn)

        env_note = QLabel(
            "Credentials can also be set via environment variables:\n"
            "WARCRAFTLOGS_CLIENT_ID, WARCRAFTLOGS_CLIENT_SECRET"
        )
        env_note.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        env_note.setWordWrap(True)
        creds_layout.addRow(env_note)

        layout.addWidget(creds_group)

        # ── Role Thresholds ──
        thresh_group = QGroupBox("Role Detection Thresholds")
        thresh_layout = QFormLayout(thresh_group)
        thresh_layout.setSpacing(12)
        thresh_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.healer_threshold = QSpinBox()
        self.healer_threshold.setRange(0, 10_000_000)
        self.healer_threshold.setSingleStep(5000)
        self.healer_threshold.setSuffix(" healing")
        thresh_layout.addRow("Min Healer Healing:", self.healer_threshold)

        self.tank_min_taken = QSpinBox()
        self.tank_min_taken.setRange(0, 10_000_000)
        self.tank_min_taken.setSingleStep(10000)
        self.tank_min_taken.setSuffix(" damage")
        thresh_layout.addRow("Min Tank Damage Taken:", self.tank_min_taken)

        self.tank_min_mitigation = QSpinBox()
        self.tank_min_mitigation.setRange(0, 100)
        self.tank_min_mitigation.setSingleStep(5)
        self.tank_min_mitigation.setSuffix("%")
        thresh_layout.addRow("Min Tank Mitigation:", self.tank_min_mitigation)

        sep = QLabel("10-Man Raid Overrides")
        sep.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold; margin-top: 8px;")
        thresh_layout.addRow(sep)

        self.healer_threshold_10 = QSpinBox()
        self.healer_threshold_10.setRange(0, 10_000_000)
        self.healer_threshold_10.setSingleStep(50000)
        self.healer_threshold_10.setSuffix(" healing")
        thresh_layout.addRow("Min Healer Healing (10-man):", self.healer_threshold_10)

        self.tank_min_taken_10 = QSpinBox()
        self.tank_min_taken_10.setRange(0, 10_000_000)
        self.tank_min_taken_10.setSingleStep(50000)
        self.tank_min_taken_10.setSuffix(" damage")
        thresh_layout.addRow("Min Tank Damage Taken (10-man):", self.tank_min_taken_10)

        layout.addWidget(thresh_group)

        # ── Data Management ──
        data_group = QGroupBox("Data Management")
        data_layout = QVBoxLayout(data_group)

        db_path = str(self._paths.get_db_path())
        exists = os.path.exists(db_path)
        size = ""
        if exists:
            size_bytes = os.path.getsize(db_path)
            if size_bytes < 1024:
                size = f" ({size_bytes} bytes)"
            else:
                size = f" ({size_bytes / 1024:.1f} KB)"

        db_info = QLabel(f"Database: {db_path}{size}")
        db_info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        db_info.setWordWrap(True)
        data_layout.addWidget(db_info)

        data_note = QLabel(
            "Clears all raid history from the database and removes cached API responses.\n"
            "Raids will need to be re-downloaded and re-analyzed."
        )
        data_note.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        data_note.setWordWrap(True)
        data_layout.addWidget(data_note)

        clear_all_btn = QPushButton("Clear All Data")
        clear_all_btn.setFixedWidth(160)
        clear_all_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['error']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #c0392b;
            }}
        """)
        clear_all_btn.clicked.connect(self._clear_all_data)
        data_layout.addWidget(clear_all_btn)

        layout.addWidget(data_group)

        # ── Save button ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("Save Settings")
        save_btn.setFixedWidth(160)
        save_btn.clicked.connect(self._save_config)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

    def _toggle_secret_visibility(self):
        if self.client_secret_input.echoMode() == QLineEdit.EchoMode.Password:
            self.client_secret_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_secret_btn.setText("Hide")
        else:
            self.client_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_secret_btn.setText("Show")

    def _load_current_config(self):
        if not os.path.exists(self.CONFIG_PATH):
            self.healer_threshold.setValue(40000)
            self.tank_min_taken.setValue(150000)
            self.tank_min_mitigation.setValue(40)
            self.healer_threshold_10.setValue(400000)
            self.tank_min_taken_10.setValue(300000)
            self.guild_id_input.setText("774065")
            return

        try:
            with open(self.CONFIG_PATH, "r") as f:
                config = json.load(f)

            self.client_id_input.setText(config.get("client_id", ""))
            self.client_secret_input.setText(config.get("client_secret", ""))
            self.report_id_input.setText(config.get("report_id", ""))
            self.guild_id_input.setText(str(config.get("guild_id", 774065)))
            self.guild_name_input.setText(config.get("guild_name", ""))
            self.guild_server_input.setText(config.get("guild_server", ""))

            thresholds = config.get("role_thresholds", {})
            self.healer_threshold.setValue(thresholds.get("healer_min_healing", 40000))
            self.tank_min_taken.setValue(thresholds.get("tank_min_taken", 150000))
            self.tank_min_mitigation.setValue(thresholds.get("tank_min_mitigation", 40))
            self.healer_threshold_10.setValue(thresholds.get("healer_min_healing_10", 400000))
            self.tank_min_taken_10.setValue(thresholds.get("tank_min_taken_10", 300000))

        except (json.JSONDecodeError, OSError, KeyError, ValueError) as e:
            QMessageBox.warning(self, "Config Error", f"Could not load config.json:\n{e}")

    def _save_config(self):
        config = {}

        # Preserve existing values if present
        if os.path.exists(self.CONFIG_PATH):
            try:
                with open(self.CONFIG_PATH, "r") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        client_id = self.client_id_input.text().strip()
        client_secret = self.client_secret_input.text().strip()

        if not client_id or not client_secret:
            QMessageBox.warning(self, "Missing Credentials",
                                "Client ID and Client Secret are required.")
            return

        config["client_id"] = client_id
        config["client_secret"] = client_secret
        config["report_id"] = self.report_id_input.text().strip()
        try:
            config["guild_id"] = int(self.guild_id_input.text().strip())
        except ValueError:
            config["guild_id"] = 0
        config["guild_name"] = self.guild_name_input.text().strip()
        config["guild_server"] = self.guild_server_input.text().strip()
        config["role_thresholds"] = {
            "healer_min_healing": self.healer_threshold.value(),
            "tank_min_taken": self.tank_min_taken.value(),
            "tank_min_mitigation": self.tank_min_mitigation.value(),
            "healer_min_healing_10": self.healer_threshold_10.value(),
            "tank_min_taken_10": self.tank_min_taken_10.value(),
        }
        try:
            with open(self.CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=4)

            # Reset the config manager so changes take effect immediately
            from ..config import get_config_manager
            get_config_manager(self.CONFIG_PATH)

            QMessageBox.information(self, "Saved", "Settings saved successfully.")
            self.status_message.emit("Settings saved")
        except (json.JSONDecodeError, OSError) as e:
            QMessageBox.critical(self, "Save Error", f"Could not save config.json:\n{e}")

    def _clear_all_data(self):
        from PySide6.QtWidgets import QInputDialog
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Confirm Clear All Data")
        dlg.setLabelText(
            "This will permanently delete ALL raid history, character data,\n"
            "and cached API responses.\n\n"
            "Type 'I am Toad' to confirm:"
        )
        dlg.setStyleSheet(f"""
            QInputDialog, QLabel, QLineEdit, QPushButton {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text']};
            }}
            QLineEdit {{
                background-color: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 10px;
            }}
        """)
        ok = dlg.exec()
        text = dlg.textValue()
        if not ok or text.strip() != "I am Toad":
            self.status_message.emit("Clear cancelled")
            return
        try:
            from ..database import PerformanceDB
            with PerformanceDB() as db:
                db.clear_all()

            from ..cache import clear_response_cache
            cache_count = clear_response_cache()

            QMessageBox.information(
                self, "Cleared",
                f"Database cleared and {cache_count} cached API responses removed.")
            self.status_message.emit(f"All data cleared ({cache_count} cache files)")
        except (sqlite3.Error, OSError) as e:
            QMessageBox.critical(self, "Error", f"Failed to clear data:\n{e}")
