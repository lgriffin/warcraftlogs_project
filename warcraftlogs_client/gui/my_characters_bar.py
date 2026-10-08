"""The main character and claimed alts at the top of My Character: one click jumps to a favourite."""

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..services import MyCharacters, MyCharactersService, PlayerRef
from .styles import COLORS


class MyCharactersBar(QWidget):
    """Shows the signed-in user's main and alts as buttons, and claims or releases the character on screen.

    ``service`` builds a fresh ``MyCharactersService`` on every reload, so signing in or out in Settings applies
    the next time the page is shown.
    """

    character_chosen = Signal(object)  # PlayerRef
    status_message = Signal(str)

    def __init__(self, service: Callable[[], MyCharactersService], parent=None):
        super().__init__(parent)
        self._service_factory = service
        self._service: MyCharactersService | None = None
        self._mine = MyCharacters()
        self._current: PlayerRef | None = None
        self._buttons: list[QPushButton] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._owner_label = QLabel("")
        self._owner_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(self._owner_label)

        self._favourites_row = QHBoxLayout()
        self._favourites_row.setSpacing(6)
        self._empty_label = QLabel("No main yet: look up your character below, then Set as main.")
        self._empty_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        self._favourites_row.addWidget(self._empty_label)
        self._favourites_row.addStretch()
        layout.addLayout(self._favourites_row)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._main_btn = QPushButton("Set as main")
        self._main_btn.clicked.connect(self._on_set_main)
        self._claim_btn = QPushButton("Claim as alt")
        self._claim_btn.clicked.connect(self._on_claim)
        self._release_btn = QPushButton("Release")
        self._release_btn.setToolTip("Stop claiming this character")
        self._release_btn.clicked.connect(self._on_release)
        for btn in (self._main_btn, self._claim_btn, self._release_btn):
            btn.setProperty("secondary", True)
            btn.setFixedHeight(30)
            actions.addWidget(btn)
        actions.addStretch()
        layout.addLayout(actions)
        self._update_actions()

    # ── State ──

    @property
    def characters(self) -> MyCharacters:
        return self._mine

    @property
    def owner(self) -> str | None:
        """Whose characters are shown: a Discord id or ``LOCAL``; None before the first reload."""
        return self._service.owner if self._service is not None else None

    def reload(self) -> MyCharacters:
        """Re-read who is signed in and their characters."""
        self._service = self._service_factory()
        who = self._service.owner_name
        self._owner_label.setText(
            f"Signed in as {who}" if who else "Not signed in: these stay on this computer until you sign in"
        )
        self._show(self._service.current())
        return self._mine

    def set_current(self, ref: PlayerRef | None) -> None:
        """The character the page is showing, which the action buttons act on."""
        self._current = ref
        self._update_actions()
        self._highlight()

    # ── Drawing ──

    def _show(self, mine: MyCharacters) -> None:
        self._mine = mine
        for btn in self._buttons:
            self._favourites_row.removeWidget(btn)
            btn.deleteLater()
        self._buttons = []
        for i, ref in enumerate(mine.favourites):
            is_main = ref == mine.main
            btn = QPushButton(f"★ {ref.name}" if is_main else ref.name)
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setToolTip(f"{'Main' if is_main else 'Alt'}: {ref.label}")
            btn.clicked.connect(lambda _checked=False, r=ref: self._choose(r))
            self._favourites_row.insertWidget(i, btn)
            self._buttons.append(btn)
        self._empty_label.setVisible(not self._buttons)
        self._update_actions()
        self._highlight()

    def _highlight(self) -> None:
        for btn, ref in zip(self._buttons, self._mine.favourites, strict=True):
            btn.setChecked(ref == self._current)

    def _update_actions(self) -> None:
        ref = self._current
        self._main_btn.setEnabled(ref is not None and ref != self._mine.main)
        self._claim_btn.setEnabled(ref is not None and self._mine.main is not None and ref not in self._mine)
        self._release_btn.setEnabled(ref is not None and ref in self._mine)

    # ── Actions ──

    def _choose(self, ref: PlayerRef) -> None:
        self.set_current(ref)
        self.character_chosen.emit(ref)

    def _change(self, action: Callable[[MyCharactersService, PlayerRef], MyCharacters], message: str) -> None:
        if self._current is None:
            return
        if self._service is None:
            self.reload()
        try:
            self._show(action(self._service, self._current))
        except OSError as e:
            self.status_message.emit(f"Could not save your characters: {e}")
            return
        self.status_message.emit(message.format(name=self._current.name))

    def _on_set_main(self) -> None:
        self._change(MyCharactersService.set_main, "{name} is now your main")

    def _on_claim(self) -> None:
        self._change(MyCharactersService.claim, "Claimed {name} as an alt")

    def _on_release(self) -> None:
        self._change(MyCharactersService.release, "Released {name}")
