"""
Settings section for raid profiles (phase 5): add and delete the profiles the top bar switches between.

A profile names its own game version, guild and site, so the guild and API URL fields above are only the defaults
of "All" and of a profile that leaves them blank. Everything goes through ``ProfileService``; the panel never reads
the profile file or config.json.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..services import IdentityService
from ..services.profiles import GAME_VERSIONS, Profile, ProfileService
from .styles import COLORS

ADD = "Add profile"
DELETE = "Delete"
ANY_SITE = "The default site"
GUILD_NOT_A_NUMBER = "The guild ID is the number in the guild's Warcraft Logs address"
NO_PROFILES = "No raid profiles yet. Add one to see only one game version or guild."


def describe(profile: Profile) -> str:
    """One line per profile: its name, then its site and guild when it names them."""
    parts = [profile.game_version or "default site"]
    if profile.guild_id is not None:
        parts.append(f"guild {profile.guild_id}")
    return f"{profile.name} ({', '.join(parts)})"


class ProfilesPanel(QWidget):
    status_message = Signal(str)
    profiles_changed = Signal()  # the top bar's switcher re-reads the list

    def __init__(self, service: ProfileService, identity: IdentityService | None = None, parent=None):
        super().__init__(parent)
        self._service = service
        self._identity = identity  # who is linked when a profile is added becomes its owner (PROF-05)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox("Raid Profiles")
        group_layout = QVBoxLayout(group)
        desc = QLabel(
            "A profile shows and imports one game version, and can name its own guild. A profile without a guild "
            "uses the Default Guild ID above; one without a game version uses the default site."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        group_layout.addWidget(desc)

        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        self.list.currentItemChanged.connect(self._on_selection)
        group_layout.addWidget(self.list)
        self.empty = QLabel(NO_PROFILES)
        self.empty.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        group_layout.addWidget(self.empty)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. TBC Anniversary")
        form.addRow("Name:", self.name_input)
        self.version_input = QComboBox()
        self.version_input.addItem(ANY_SITE, None)
        for version in GAME_VERSIONS:
            self.version_input.addItem(version, version)
        form.addRow("Game version:", self.version_input)
        self.guild_input = QLineEdit()
        self.guild_input.setPlaceholderText("Blank for the default guild")
        form.addRow("Guild ID:", self.guild_input)
        group_layout.addLayout(form)

        row = QHBoxLayout()
        row.addStretch()
        self.add_button = QPushButton(ADD)
        self.add_button.setFixedHeight(32)
        self.add_button.clicked.connect(self._add)
        row.addWidget(self.add_button)
        self.delete_button = QPushButton(DELETE)
        self.delete_button.setFixedHeight(32)
        self.delete_button.clicked.connect(self._delete)
        row.addWidget(self.delete_button)
        group_layout.addLayout(row)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {COLORS['error']}; font-size: 12px;")
        group_layout.addWidget(self.error)
        layout.addWidget(group)
        self.reload()

    def reload(self) -> None:
        self.list.clear()
        for profile in self._service.list():
            item = QListWidgetItem(describe(profile))
            item.setData(Qt.ItemDataRole.UserRole, profile.slug)
            self.list.addItem(item)
        has_profiles = self.list.count() > 0
        self.list.setVisible(has_profiles)
        self.empty.setVisible(not has_profiles)
        self._on_selection()

    def _on_selection(self, *_args) -> None:
        self.delete_button.setEnabled(self.list.currentItem() is not None)

    def _add(self) -> None:
        guild_text = self.guild_input.text().strip()
        if guild_text and not (guild_text.isascii() and guild_text.isdigit()):
            self.error.setText(GUILD_NOT_A_NUMBER)
            return
        who = self._identity.current() if self._identity is not None else None
        self._service.owner = who.id if who is not None else None
        try:
            profile = self._service.create(
                self.name_input.text(),
                game_version=self.version_input.currentData(),
                guild_id=int(guild_text) if guild_text else None,
            )
        except ValueError as e:  # no name, or a name already in use
            self.error.setText(str(e))
            return
        self.error.clear()
        self.name_input.clear()
        self.guild_input.clear()
        self.version_input.setCurrentIndex(0)
        self._changed(f"Added the {profile.name} profile")

    def _delete(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        name = item.text()
        if self._service.delete(item.data(Qt.ItemDataRole.UserRole)):
            self._changed(f"Deleted {name}")

    def _changed(self, message: str) -> None:
        self.reload()
        self.profiles_changed.emit()
        self.status_message.emit(message)
