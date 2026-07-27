"""
Background worker for fetching per-encounter, per-player data.

Used by EncounterDeepDiveView to load cast timelines, resource data,
and buff/cooldown data without blocking the UI.
"""

from PySide6.QtCore import QThread, Signal

from ..client import WarcraftLogsClient
from ..models import (
    CooldownSynergyAnalysis,
    EncounterSummary,
    PlayerCastTimeline,
    PlayerResourceAnalysis,
    RaidComposition,
)


class EncounterCastWorker(QThread):
    progress = Signal(str)
    finished = Signal(list)  # list[PlayerCastTimeline]
    error = Signal(str)

    def __init__(
        self,
        client: WarcraftLogsClient,
        report_id: str,
        encounter: EncounterSummary,
        composition: RaidComposition,
        player_class: str,
        parent=None,
    ):
        super().__init__(parent)
        self._client = client
        self._report_id = report_id
        self._encounter = encounter
        self._composition = composition
        self._player_class = player_class

    def run(self):
        try:
            from ..analysis import build_class_cast_timelines

            def on_progress(msg):
                self.progress.emit(msg)

            result = build_class_cast_timelines(
                self._client,
                self._report_id,
                self._encounter,
                self._composition,
                self._player_class,
                progress_callback=on_progress,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class EncounterResourceWorker(QThread):
    progress = Signal(str)
    finished = Signal(list)  # list[PlayerResourceAnalysis]
    error = Signal(str)

    def __init__(
        self,
        client: WarcraftLogsClient,
        report_id: str,
        encounter: EncounterSummary,
        composition: RaidComposition,
        consumable_usage: list,
        parent=None,
    ):
        super().__init__(parent)
        self._client = client
        self._report_id = report_id
        self._encounter = encounter
        self._composition = composition
        self._consumable_usage = consumable_usage

    def run(self):
        try:
            from ..analysis import analyze_resource_waste

            def on_progress(msg):
                self.progress.emit(msg)

            result = analyze_resource_waste(
                self._client,
                self._report_id,
                self._encounter,
                self._composition,
                self._consumable_usage,
                progress_callback=on_progress,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class EncounterCooldownWorker(QThread):
    progress = Signal(str)
    finished = Signal(CooldownSynergyAnalysis)
    error = Signal(str)

    def __init__(
        self,
        client: WarcraftLogsClient,
        report_id: str,
        encounter: EncounterSummary,
        composition: RaidComposition,
        parent=None,
    ):
        super().__init__(parent)
        self._client = client
        self._report_id = report_id
        self._encounter = encounter
        self._composition = composition

    def run(self):
        try:
            from ..analysis import analyze_cooldown_synergy

            def on_progress(msg):
                self.progress.emit(msg)

            result = analyze_cooldown_synergy(
                self._client,
                self._report_id,
                self._encounter,
                self._composition,
                progress_callback=on_progress,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")
