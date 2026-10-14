"""
First-run setup: walks a new user through creating Warcraft Logs API keys, then finding their guild.

Opens on start-up while there are no keys, and from Settings ("Run setup"). Everything goes through
``OnboardingService``: the keys are checked against Warcraft Logs before the guild step, and nothing is saved until
Finish (or "Skip", which keeps the keys without a guild). Each Warcraft Logs call runs on a daemon thread, as the
Toads Hub panel's do, so a slow answer never freezes the window.
"""

from __future__ import annotations

import contextlib
import threading
import webbrowser
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..services import GuildMatch, OnboardingService, SetupError
from ..services.onboarding import KEYS_URL, REDIRECT_URL, REGIONS
from .styles import COLORS, common_styles

CHECKING = "Checking..."
SEARCHING = "Searching..."
KEYS_OK = "Keys accepted by Warcraft Logs."
GUILD_HINT = "Link to your guild's page or one of its reports, or the guild's name"
# The Warcraft Logs sites a guild can be on, as the site picker shows them.
SITES: tuple[tuple[str, str], ...] = (
    ("fresh", "Anniversary (fresh.warcraftlogs.com)"),
    ("classic", "Classic Era (classic.warcraftlogs.com)"),
    ("sod", "Season of Discovery (sod.warcraftlogs.com)"),
    ("retail", "Retail (www.warcraftlogs.com)"),
)

KEY_STEPS = (
    "1. Sign in to Warcraft Logs and open your API clients page.",
    '2. Choose "Create Client". Give it any name, like "Raid Analyzer", paste the redirect URL below and leave '
    '"Public Client" unticked.',
    "3. Copy the Client ID and Client Secret it shows you into the boxes below.",
)
GUILD_HELP = (
    "Open your guild on Warcraft Logs and paste the page's link here, or paste a link to any report your guild "
    "logged. You can also type the guild's name and pick its server and region."
)


def found_text(guild: GuildMatch) -> str:
    return f"Found {guild.label}, guild id {guild.id}."


class _Relay(QObject):
    """Carries a Warcraft Logs call's outcome from its thread back to the UI thread."""

    done = Signal(object)
    failed = Signal(str)


def _dim(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
    return label


def _secondary(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("secondary", True)
    return button


class _Background(QObject):
    """Runs one call at a time off the UI thread and hands its result or ``SetupError`` message back."""

    def __init__(self, parent: QObject, done: Callable[[Any], None], failed: Callable[[str], None]):
        super().__init__(parent)
        self.busy = False
        self._relay = _Relay(self)
        self._relay.done.connect(self._finish)
        self._relay.failed.connect(self._fail)
        self._done = done
        self._failed = failed

    def run(self, call: Callable[[], Any]) -> bool:
        if self.busy:
            return False
        self.busy = True
        threading.Thread(target=self._call, args=(call,), daemon=True).start()
        return True

    def _call(self, call: Callable[[], Any]) -> None:
        try:
            result = call()
        except SetupError as e:
            self._emit(self._relay.failed, str(e))
        except Exception as e:  # shown to the user; the thread must always report back
            self._emit(self._relay.failed, f"Something went wrong: {e}")
        else:
            self._emit(self._relay.done, result)

    @staticmethod
    def _emit(signal, value: Any) -> None:
        with contextlib.suppress(RuntimeError):  # the window closed while Warcraft Logs answered
            signal.emit(value)

    def _finish(self, result: Any) -> None:
        self.busy = False
        self._done(result)

    def _fail(self, error: str) -> None:
        self.busy = False
        self._failed(error)


class GuildFinder(QWidget):
    """Finds a guild on Warcraft Logs from a link, a report or a name. Used by setup and by Settings."""

    changed = Signal(object)  # the GuildMatch found, or None after a search that found nothing

    def __init__(self, service: OnboardingService, keys: Callable[[], tuple[str, str]], parent=None):
        super().__init__(parent)
        self._service = service
        self._keys = keys
        self.guild: GuildMatch | None = None
        self._worker = _Background(self, self._on_found, self._on_failed)
        self._asked: tuple[str, str, Any, Any] | None = None  # the inputs the running search was asked with

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(_dim(GUILD_HELP))

        row = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText(GUILD_HINT)
        self.query_input.returnPressed.connect(self.search)
        row.addWidget(self.query_input, 1)
        self.find_button = QPushButton("Find")
        self.find_button.setFixedWidth(110)
        self.find_button.clicked.connect(self.search)
        row.addWidget(self.find_button)
        layout.addLayout(row)

        form = QFormLayout()
        form.setSpacing(8)
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("e.g. Gehennas (only needed for a name)")
        form.addRow("Server:", self.server_input)
        self.region_combo = QComboBox()
        for region in REGIONS:
            self.region_combo.addItem(region.upper(), region)
        form.addRow("Region:", self.region_combo)
        self.site_combo = QComboBox()
        for version, label in SITES:
            self.site_combo.addItem(label, version)
        index = self.site_combo.findData(self._configured_site())
        self.site_combo.setCurrentIndex(max(index, 0))
        self.site_combo.setToolTip("Which Warcraft Logs site to search by name; a link picks its own")
        form.addRow("Site:", self.site_combo)
        layout.addLayout(form)

        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.result)

    def _configured_site(self) -> str:
        try:
            return self._service.site()
        except SetupError:
            return "fresh"

    def search(self) -> None:
        text = self.query_input.text()
        server = self.server_input.text()
        region = self.region_combo.currentData()
        site = self.site_combo.currentData()
        client_id, secret = self._keys()
        self._asked = self._inputs()

        def find() -> GuildMatch:
            return self._service.find_guild(text, client_id, secret, server=server, region=region, game_version=site)

        if self._worker.run(find):
            self.find_button.setEnabled(False)
            self.find_button.setText(SEARCHING)
            self._say(SEARCHING, "text_dim")

    def _inputs(self) -> tuple[str, str, Any, Any]:
        return (
            self.query_input.text(),
            self.server_input.text(),
            self.region_combo.currentData(),
            self.site_combo.currentData(),
        )

    def _on_found(self, guild: GuildMatch) -> None:
        self._idle()
        if self._inputs() != self._asked:  # edited while Warcraft Logs answered: the answer is for other input
            self._on_failed("The search changed while it ran. Press Find again.")
            return
        self.guild = guild
        self._say(found_text(guild), "success")
        self.changed.emit(guild)

    def _on_failed(self, error: str) -> None:
        self._idle()
        self.guild = None
        self._say(error, "error")
        self.changed.emit(None)

    def _idle(self) -> None:
        self.find_button.setEnabled(True)
        self.find_button.setText("Find")

    def _say(self, text: str, colour: str) -> None:
        self.result.setText(text)
        self.result.setStyleSheet(f"color: {COLORS[colour]}; font-size: 12px;")


class SetupWizard(QDialog):
    """Two steps, API keys then guild; ``saved`` says what was kept when it closes having saved."""

    saved = Signal(str)

    KEYS, GUILD = 0, 1

    def __init__(self, service: OnboardingService, parent=None, open_url: Callable[[str], Any] = webbrowser.open):
        super().__init__(parent)
        self._service = service
        self._open_url = open_url
        self._checker = _Background(self, self._on_keys_ok, self._on_keys_failed)
        self.setWindowTitle("Set up WarcraftLogs Analyzer")
        self.setMinimumWidth(620)
        self.setStyleSheet(common_styles() + f"QDialog {{ background-color: {COLORS['bg_card']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._keys_page())
        self.pages.addWidget(self._guild_page())
        layout.addWidget(self.pages, 1)

        buttons = QHBoxLayout()
        self.later_button = _secondary("Set up later")
        self.later_button.clicked.connect(self.reject)
        buttons.addWidget(self.later_button)
        self.back_button = _secondary("Back")
        self.back_button.clicked.connect(lambda: self._show(self.KEYS))
        buttons.addWidget(self.back_button)
        buttons.addStretch()
        self.skip_button = _secondary("Skip guild")
        self.skip_button.setToolTip("Save the keys now and pick a guild later in Settings")
        self.skip_button.clicked.connect(lambda: self._finish(None))
        buttons.addWidget(self.skip_button)
        self.next_button = QPushButton("Check keys")
        self.next_button.setMinimumWidth(130)
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self._next)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        client_id, secret = service.saved_keys()
        self.client_id_input.setText(client_id)
        self.secret_input.setText(secret)
        self._show(self.KEYS)

    # ── Pages ──

    def _keys_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._header("Connect to Warcraft Logs"))
        layout.addWidget(
            _dim(
                "The app reads your raids through the Warcraft Logs API, which needs a free API client of your own. "
                "Creating one takes a minute:"
            )
        )
        for step in KEY_STEPS:
            label = QLabel(step)
            label.setWordWrap(True)
            layout.addWidget(label)

        links = QHBoxLayout()
        self.open_keys_button = QPushButton("Open Warcraft Logs")
        self.open_keys_button.clicked.connect(lambda: self._open_url(KEYS_URL))
        links.addWidget(self.open_keys_button)
        self.redirect_label = QLineEdit(REDIRECT_URL)
        self.redirect_label.setReadOnly(True)
        self.redirect_label.setToolTip("The redirect URL to give your Warcraft Logs client")
        links.addWidget(self.redirect_label, 1)
        self.copy_redirect_button = _secondary("Copy")
        self.copy_redirect_button.clicked.connect(self._copy_redirect)
        links.addWidget(self.copy_redirect_button)
        layout.addLayout(links)

        form = QFormLayout()
        form.setSpacing(10)
        self.client_id_input = QLineEdit()
        self.client_id_input.setPlaceholderText("Client ID")
        form.addRow("Client ID:", self.client_id_input)
        secret_row = QHBoxLayout()
        self.secret_input = QLineEdit()
        self.secret_input.setPlaceholderText("Client Secret")
        self.secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_input.returnPressed.connect(self._next)
        secret_row.addWidget(self.secret_input, 1)
        self.show_secret_button = _secondary("Show")
        self.show_secret_button.setFixedWidth(80)
        self.show_secret_button.clicked.connect(self._toggle_secret)
        secret_row.addWidget(self.show_secret_button)
        form.addRow("Client Secret:", secret_row)
        layout.addLayout(form)

        self.keys_status = QLabel()
        self.keys_status.setWordWrap(True)
        layout.addWidget(self.keys_status)
        layout.addStretch()
        return page

    def _guild_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._header("Find your guild"))
        self.finder = GuildFinder(self._service, self._keys)
        self.finder.changed.connect(lambda _guild: self._show(self.GUILD))
        layout.addWidget(self.finder)
        layout.addStretch()
        return page

    @staticmethod
    def _header(text: str) -> QLabel:
        header = QLabel(text)
        header.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['accent']};")
        return header

    # ── Steps ──

    def _keys(self) -> tuple[str, str]:
        return self.client_id_input.text(), self.secret_input.text()

    def _show(self, page: int) -> None:
        self.pages.setCurrentIndex(page)
        on_keys = page == self.KEYS
        self.later_button.setVisible(on_keys)
        self.back_button.setVisible(not on_keys)
        self.skip_button.setVisible(not on_keys)
        if on_keys:
            self.next_button.setText(CHECKING if self._checker.busy else "Check keys")
            self.next_button.setEnabled(not self._checker.busy)
        else:
            self.next_button.setText("Finish")
            self.next_button.setEnabled(self.finder.guild is not None)

    def _next(self) -> None:
        if self.pages.currentIndex() == self.GUILD:
            if self.finder.guild is not None:
                self._finish(self.finder.guild)
            return
        client_id, secret = self._keys()
        if self._checker.run(lambda: self._service.check_keys(client_id, secret)):
            self.next_button.setEnabled(False)
            self.next_button.setText(CHECKING)
            self._say(CHECKING, "text_dim")

    def _on_keys_ok(self, _result: object) -> None:
        self._say(KEYS_OK, "success")
        self._show(self.GUILD)
        self.finder.query_input.setFocus()

    def _on_keys_failed(self, error: str) -> None:
        self._say(error, "error")
        self._show(self.KEYS)

    def _finish(self, guild: GuildMatch | None) -> None:
        client_id, secret = self._keys()
        try:
            self._service.save(client_id, secret, guild)
        except SetupError as e:
            self.finder.result.setText(str(e))
            self.finder.result.setStyleSheet(f"color: {COLORS['error']}; font-size: 12px;")
            return
        self.saved.emit(f"Setup saved: imports now come from {guild.label}" if guild else "Setup saved: API keys kept")
        self.accept()

    def _say(self, text: str, colour: str) -> None:
        self.keys_status.setText(text)
        self.keys_status.setStyleSheet(f"color: {COLORS[colour]}; font-size: 12px;")

    def _toggle_secret(self) -> None:
        hidden = self.secret_input.echoMode() == QLineEdit.EchoMode.Password
        self.secret_input.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_secret_button.setText("Hide" if hidden else "Show")

    def _copy_redirect(self) -> None:
        QGuiApplication.clipboard().setText(REDIRECT_URL)
        self.copy_redirect_button.setText("Copied")


class GuildFinderDialog(QDialog):
    """Settings' "Find guild": the setup's guild step on its own, with the keys Settings holds."""

    def __init__(self, service: OnboardingService, keys: Callable[[], tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find your guild")
        self.setMinimumWidth(560)
        self.setStyleSheet(common_styles() + f"QDialog {{ background-color: {COLORS['bg_card']}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        self.finder = GuildFinder(service, keys)
        layout.addWidget(self.finder)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = _secondary("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.use_button = QPushButton("Use this guild")
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self.accept)
        buttons.addWidget(self.use_button)
        layout.addLayout(buttons)
        self.finder.changed.connect(lambda guild: self.use_button.setEnabled(guild is not None))

    @property
    def guild(self) -> GuildMatch | None:
        return self.finder.guild
