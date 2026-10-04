"""
Settings section for the Toads Hub link (phase 4): paste the one-time code the Toads bot gave you.

Everything goes through ``BridgeService``: linking redeems the code and publishes this app's raid profiles,
"Publish profiles" sends them again after a change, and unlinking forgets the app here and on the Hub. Each call
runs on a daemon thread so a slow Hub never freezes the window; no file or token is read here.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..services import BridgeService
from .styles import COLORS

LINK = "Link"
UNLINK = "Unlink"
PUBLISH = "Publish profiles"
WORKING = "Working..."
NOT_LINKED = "Not linked. In Discord, ask the Toads bot for a link code and paste it here."
CODE_HINT = "Code from the Toads bot, like 7KQ2-M9XD"


def linked_text(name: str, hub_url: str) -> str:
    return f"Linked to {hub_url} as {name}"


class _Relay(QObject):
    """Carries a Hub call's outcome from its thread back to the UI thread."""

    done = Signal(str)
    failed = Signal(str)


class HubPanel(QWidget):
    status_message = Signal(str)

    def __init__(self, bridge: BridgeService, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._busy = False
        self._relay = _Relay(self)
        self._relay.done.connect(self._on_done)
        self._relay.failed.connect(self._on_failed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox("Toads Hub")
        group_layout = QVBoxLayout(group)
        desc = QLabel(
            "Link this app to the Toads Hub so the bot can run your raid profiles. The code proves it is yours; "
            "only your profiles are sent, never your raids or Warcraft Logs keys."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        group_layout.addWidget(desc)
        self.status = QLabel()
        self.status.setWordWrap(True)
        group_layout.addWidget(self.status)
        row = QHBoxLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText(CODE_HINT)
        self.code_input.returnPressed.connect(self._link_or_unlink)
        row.addWidget(self.code_input, 1)
        self.link_button = QPushButton()
        self.link_button.setFixedHeight(32)
        self.link_button.clicked.connect(self._link_or_unlink)
        row.addWidget(self.link_button)
        self.publish_button = QPushButton(PUBLISH)
        self.publish_button.setFixedHeight(32)
        self.publish_button.clicked.connect(self._publish)
        row.addWidget(self.publish_button)
        group_layout.addLayout(row)
        layout.addWidget(group)
        self._show_link()

    def _show_link(self) -> None:
        link = self._bridge.current()
        if link is not None:
            self.status.setText(linked_text(link.member.name, link.hub_url))
            self.status.setStyleSheet(f"color: {COLORS['success']}; font-size: 13px;")
        else:
            self.status.setText(NOT_LINKED)
            self.status.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 13px;")
        self.code_input.setVisible(link is None)
        self.link_button.setText(UNLINK if link is not None else LINK)
        self.link_button.setEnabled(not self._busy)
        self.publish_button.setVisible(link is not None)
        self.publish_button.setEnabled(not self._busy)

    def _link_or_unlink(self) -> None:
        if self._bridge.is_linked():
            self._run(lambda: "Hub link forgotten" if self._bridge.unlink() else "Hub link forgotten here only")
            return
        code = self.code_input.text().strip()
        if not code:
            self.status.setText(CODE_HINT)
            return

        def link() -> str:
            linked = self._bridge.link(code)
            return f"Linked to the Toads Hub as {linked.member.name}"

        self._run(link)

    def _publish(self) -> None:
        def publish() -> str:
            self._bridge.publish()
            return "Raid profiles published to the Toads Hub"

        self._run(publish)

    def _run(self, call: Callable[[], str]) -> None:
        if self._busy:
            return
        self._busy = True
        self.link_button.setText(WORKING)
        self._show_busy()
        threading.Thread(target=self._call, args=(call,), daemon=True).start()

    def _show_busy(self) -> None:
        self.link_button.setEnabled(False)
        self.publish_button.setEnabled(False)

    def _call(self, call: Callable[[], str]) -> None:
        try:
            message = call()
        except Exception as e:  # shown to the user: a bad or expired code, an unreachable Hub, no Hub configured
            self._emit(self._relay.failed, str(e))
        else:
            self._emit(self._relay.done, message)

    @staticmethod
    def _emit(signal, value: str) -> None:
        with contextlib.suppress(RuntimeError):  # the panel closed while the Hub answered
            signal.emit(value)

    def _on_done(self, message: str) -> None:
        self._busy = False
        self.code_input.clear()
        self._show_link()
        self.status_message.emit(message)

    def _on_failed(self, error: str) -> None:
        self._busy = False
        self._show_link()
        self.status.setText(error)
        self.status.setStyleSheet(f"color: {COLORS['error']}; font-size: 13px;")
        self.status_message.emit("Toads Hub link failed")

    def use_config(self, config: dict) -> None:
        """Pick up a newly saved config.json, for ``toads_hub_url``."""
        self._bridge.config = dict(config)
