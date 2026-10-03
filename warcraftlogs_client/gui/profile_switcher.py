"""
Raid profile switcher for the top bar: pick which raids the app reads (PROF-09).

The choices and the switch go through ``ProfileService``; the view never reads the profile file itself.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from ..services import ProfileService
from .styles import COLORS

ALL_RAIDS = "All raids"


class ProfileSwitcher(QWidget):
    """A combo of the saved profiles plus "All raids", and the active profile's guild raid count."""

    profile_changed = Signal(str)  # the active profile's name, or ALL_RAIDS

    def __init__(self, service: ProfileService, parent=None):
        super().__init__(parent)
        self._service = service
        self._loading = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setToolTip("Raid profile: which raids every view counts")
        self.combo.setMinimumWidth(160)
        self.combo.setStyleSheet(
            f"QComboBox {{ background-color: {COLORS['bg_input']}; color: {COLORS['text']};"
            f" border: 1px solid {COLORS['border']}; border-radius: 4px; padding: 4px 8px; }}"
        )
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent;")
        layout.addWidget(self.combo)
        layout.addWidget(self.count_label)
        self.combo.currentIndexChanged.connect(self._on_index_changed)
        self.reload()

    def reload(self) -> None:
        """Refill the combo from the saved profiles, selecting the active one."""
        self._loading = True
        try:
            self.combo.clear()
            self.combo.addItem(ALL_RAIDS, None)
            profiles = self._service.profiles()
            for profile in profiles.profiles:
                self.combo.addItem(profile.name, profile.slug)
            self.combo.setCurrentIndex(max(self.combo.findData(profiles.active), 0) if profiles.active else 0)
            self._service.apply()
        finally:
            self._loading = False
        self._show_count()

    def active_name(self) -> str:
        active = self._service.active()
        return active.name if active is not None else ALL_RAIDS

    def _on_index_changed(self, index: int) -> None:
        if self._loading or index < 0:
            return
        self._service.activate(self.combo.itemData(index))
        self._show_count()
        self.profile_changed.emit(self.active_name())

    def _show_count(self) -> None:
        count = self._service.raid_count()
        self.count_label.setText(f"{count} raid{'s' if count != 1 else ''}")
