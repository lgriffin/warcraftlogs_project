"""
Settings sections for who this app belongs to and which era its raids are from (phase 2.3).

"Discord account" links the app to a Discord identity through ``IdentityService`` (the browser sign-in runs off the
UI thread); "Raid eras" tags raids stored before eras were recorded through ``ProfileService.backfill_eras()``, so
profiles can tell Classic, TBC and Era raids apart. Neither reads a token or profile file itself.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..services import IdentityService, ProfileService
from .styles import COLORS

SIGN_IN = "Sign in with Discord"
SIGN_OUT = "Sign out"
WAITING = "Waiting for Discord..."
NOT_LINKED = "Not linked"
TAG_RAIDS = "Tag stored raids"
TAGGING = "Tagging..."
# How long the browser sign-in may take before it gives up.
LINK_TIMEOUT_SECONDS = 300.0


def linked_text(display_name: str) -> str:
    return f"Linked to {display_name}"


def tagged_text(count: int) -> str:
    if count == 0:
        return "Every stored raid already has its era"
    return f"Tagged {count} raid{'s' if count != 1 else ''} with their era"


class _LinkRelay(QObject):
    """Carries the sign-in result from its thread back to the UI thread."""

    linked = Signal(object)  # DiscordIdentity
    failed = Signal(str)


class _TagWorker(QThread):
    tagged = Signal(int)
    failed = Signal(str)

    def __init__(self, profiles: ProfileService, parent=None):
        super().__init__(parent)
        self._profiles = profiles

    def run(self):
        try:
            self.tagged.emit(self._profiles.backfill_eras())
        except (sqlite3.Error, OSError, RuntimeError) as e:
            self.failed.emit(str(e))


class IdentityPanel(QWidget):
    """The Discord account and raid era sections of Settings."""

    status_message = Signal(str)
    # A tag pass changed raids, or may have: each raid is saved as it is tagged, so a pass that fails part way
    # through has still changed the ones before. The window recounts the profile and refreshes the scoped views.
    eras_changed = Signal()

    def __init__(self, identity: IdentityService, profiles: ProfileService, parent=None):
        super().__init__(parent)
        self._identity = identity
        self._profiles = profiles
        self._tag_worker: _TagWorker | None = None
        self._relay = _LinkRelay(self)
        self._relay.linked.connect(self._on_linked)
        self._relay.failed.connect(self._on_link_failed)
        self._linking = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._discord_group())
        layout.addWidget(self._eras_group())
        self._show_identity()

    def _discord_group(self) -> QGroupBox:
        group = QGroupBox("Discord Account")
        group_layout = QVBoxLayout(group)
        desc = QLabel(
            "Link this app to your Discord account so the Toads bot and Hub know whose analyzer it is. "
            "Only your Discord name and id are kept."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        group_layout.addWidget(desc)
        row = QHBoxLayout()
        self.discord_status = QLabel()
        self.discord_status.setStyleSheet("font-size: 13px;")
        row.addWidget(self.discord_status)
        row.addStretch()
        self.discord_button = QPushButton()
        self.discord_button.setFixedHeight(32)
        self.discord_button.clicked.connect(self._toggle_link)
        row.addWidget(self.discord_button)
        group_layout.addLayout(row)
        return group

    def _eras_group(self) -> QGroupBox:
        group = QGroupBox("Raid Eras")
        group_layout = QVBoxLayout(group)
        desc = QLabel(
            "Raid profiles pick raids by game version and expansion. Raids stored before those were recorded "
            "have neither, so every profile shows them; tagging fills both in from the zone and the configured site."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        group_layout.addWidget(desc)
        row = QHBoxLayout()
        self.tag_status = QLabel("")
        self.tag_status.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        row.addWidget(self.tag_status)
        row.addStretch()
        self.tag_button = QPushButton(TAG_RAIDS)
        self.tag_button.setFixedHeight(32)
        self.tag_button.clicked.connect(self._start_tagging)
        row.addWidget(self.tag_button)
        group_layout.addLayout(row)
        return group

    # ── Discord ──

    def _show_identity(self) -> None:
        current = self._identity.current()
        if current is not None:
            self.discord_status.setText(linked_text(current.display_name))
            self.discord_status.setStyleSheet(f"color: {COLORS['success']}; font-size: 13px;")
            self.discord_button.setText(SIGN_OUT)
        else:
            self.discord_status.setText(NOT_LINKED)
            self.discord_status.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 13px;")
            self.discord_button.setText(SIGN_IN)
        self.discord_button.setEnabled(True)

    def _toggle_link(self) -> None:
        if self._identity.is_linked():
            self._identity.unlink()
            self._show_identity()
            self.status_message.emit("Signed out of Discord")
            return
        if self._linking:
            return
        self._linking = True
        self.discord_button.setEnabled(False)
        self.discord_button.setText(WAITING)
        self.status_message.emit("Opening the browser for Discord sign-in...")
        # A daemon thread rather than a QThread: the sign-in waits on the browser, and closing the app mid-wait
        # must not block on it.
        threading.Thread(target=self._link, daemon=True).start()

    def _link(self) -> None:
        try:
            identity = self._identity.link(timeout=LINK_TIMEOUT_SECONDS)
        except Exception as e:  # shown to the user: not configured, timed out, refused or a network failure
            self._emit(self._relay.failed, str(e))
        else:
            self._emit(self._relay.linked, identity)

    @staticmethod
    def _emit(signal, value) -> None:
        with contextlib.suppress(RuntimeError):  # the panel closed while the browser was open
            signal.emit(value)

    def _on_linked(self, identity) -> None:
        self._linking = False
        self._show_identity()
        self.status_message.emit(f"Signed in to Discord as {identity.display_name}")

    def _on_link_failed(self, error: str) -> None:
        self._linking = False
        self._show_identity()
        self.discord_status.setText(error)
        self.discord_status.setStyleSheet(f"color: {COLORS['error']}; font-size: 13px;")
        self.status_message.emit("Discord sign-in failed")

    def use_config(self, config: dict) -> None:
        """Pick up a newly saved config.json: the Discord app id for sign-in, the configured host for tagging."""
        self._identity.config = dict(config)
        if self._profiles.ctx is not None:
            self._profiles.ctx.config.update(config)

    # ── Raid eras ──

    def _start_tagging(self) -> None:
        if self._tag_worker is not None:
            return
        self.tag_button.setEnabled(False)
        self.tag_button.setText(TAGGING)
        worker = _TagWorker(self._profiles, self)
        worker.tagged.connect(self._on_tagged)
        worker.failed.connect(self._on_tag_failed)
        worker.finished.connect(self._on_tag_finished)
        self._tag_worker = worker
        worker.start()

    def _on_tagged(self, count: int) -> None:
        self.tag_status.setText(tagged_text(count))
        self.status_message.emit(tagged_text(count))
        if count:
            self.eras_changed.emit()

    def _on_tag_failed(self, error: str) -> None:
        self.tag_status.setText(f"Tagging failed: {error}")
        self.status_message.emit("Tagging stored raids failed")
        self.eras_changed.emit()

    def _on_tag_finished(self) -> None:
        if self._tag_worker is not None:
            self._tag_worker.deleteLater()
        self._tag_worker = None
        self.tag_button.setEnabled(True)
        self.tag_button.setText(TAG_RAIDS)

    def wait_for_tagging(self) -> None:
        """Block until a running tag pass ends; the window calls this before it closes."""
        if self._tag_worker is not None:
            self._tag_worker.wait()

    def closeEvent(self, event):
        self.wait_for_tagging()
        super().closeEvent(event)
