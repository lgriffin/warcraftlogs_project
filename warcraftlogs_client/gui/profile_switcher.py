"""
Raid profile switcher for the top bar: pick which raids the app reads (PROF-09).

The choices and the switch go through ``ProfileService``; the view never reads the profile file itself. The raid
count runs on a worker so a slow database never holds up the window.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from ..services import ProfileService
from .styles import COLORS

ALL_RAIDS = "All raids"
COUNTING = "counting..."
NO_COUNT = "raids unavailable"


def count_text(count: int | None) -> str:
    if count is None:
        return NO_COUNT
    return f"{count} raid{'s' if count != 1 else ''}"


class _CountWorker(QThread):
    counted = Signal(int, object)  # generation, count or None

    def __init__(self, service: ProfileService, generation: int, parent=None):
        super().__init__(parent)
        self._service = service
        self._generation = generation

    def run(self):
        self.counted.emit(self._generation, self._service.raid_count())


class ProfileSwitcher(QWidget):
    """A combo of the saved profiles plus "All raids", and the active profile's guild raid count."""

    profile_changed = Signal(str)  # the active profile's name, or ALL_RAIDS
    count_changed = Signal(str)  # the count label's text once a count lands

    def __init__(self, service: ProfileService, parent=None):
        super().__init__(parent)
        self._service = service
        self._loading = False
        self._generation = 0
        self._workers: list[_CountWorker] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.combo = QComboBox()
        # Home, badges, player pages and the character history and compare views follow the profile; the raid and
        # insight views follow once they move onto services (identity_and_profiles.md, phase 2.3).
        self.combo.setToolTip("Raid profile: Home, badges, player pages and character history count only its raids")
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
        self._start_count()

    def active_name(self) -> str:
        active = self._service.active()
        return active.name if active is not None else ALL_RAIDS

    def _on_index_changed(self, index: int) -> None:
        if self._loading or index < 0:
            return
        self._service.activate(self.combo.itemData(index))
        self.profile_changed.emit(self.active_name())
        self._start_count()

    def _start_count(self) -> None:
        self._generation += 1
        self.count_label.setText(COUNTING)
        worker = _CountWorker(self._service, self._generation, self)
        worker.counted.connect(self._on_counted)
        worker.finished.connect(lambda w=worker: self._forget(w))
        self._workers.append(worker)
        worker.start()

    def _on_counted(self, generation: int, count: int | None) -> None:
        if generation != self._generation:
            return  # a later switch is counting; this result belongs to the previous profile
        self.count_label.setText(count_text(count))
        self.count_changed.emit(self.count_label.text())

    def _forget(self, worker: _CountWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def wait_for_counts(self, msecs: int = 5000) -> None:
        """Let running counts finish before the switcher (their parent) goes away; a running QThread must not be
        destroyed."""
        for worker in list(self._workers):
            worker.wait(msecs)

    def closeEvent(self, event):
        self.wait_for_counts()
        super().closeEvent(event)
