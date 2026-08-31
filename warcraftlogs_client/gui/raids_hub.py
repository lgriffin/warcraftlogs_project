"""
Raids hub — consolidates Download, Browse, Raid Diff, and Reference views
into a single tabbed interface.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .download_view import DownloadView
from .raid_diff_view import RaidDiffView
from .raids_view import RaidsView
from .reference_view import ReferenceView
from .styles import COMMON_STYLES


class RaidsHub(QWidget):
    status_message = Signal(str)
    open_raid = Signal(str)
    raid_downloaded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.download_view = DownloadView()
        self.raids_view = RaidsView()
        self.raid_diff_view = RaidDiffView()
        self.reference_view = ReferenceView()

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        self.setStyleSheet(COMMON_STYLES)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.addTab(self.download_view, "Download")
        self._tabs.addTab(self.raids_view, "Browse")
        self._tabs.addTab(self.raid_diff_view, "Raid Diff")
        self._tabs.addTab(self.reference_view, "Reference")
        layout.addWidget(self._tabs)

    def _connect_signals(self):
        self.download_view.status_message.connect(self.status_message)
        self.download_view.raid_downloaded.connect(self._on_raid_downloaded)
        self.download_view.open_raid.connect(self.open_raid)

        self.raids_view.status_message.connect(self.status_message)
        self.raids_view.open_raid.connect(self.open_raid)

        self.raid_diff_view.status_message.connect(self.status_message)

        self.reference_view.status_message.connect(self.status_message)
        self.reference_view.open_raid.connect(self.open_raid)

    def _on_raid_downloaded(self):
        self.raid_downloaded.emit()
