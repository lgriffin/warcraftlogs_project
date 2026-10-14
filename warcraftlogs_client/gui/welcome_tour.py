"""The welcome tour: a few cards that dim the window and point at the parts of it a new user needs first.

``WELCOME_STEPS`` is what the tour says; the main window binds each step's key to the page it opens and the widget it
points at (``TourStep``). ``WelcomeTour`` is the overlay: it covers its host window, cuts a hole round the step's
widget, and shows a card beside it with Back, Next and Skip. Esc skips; the arrow keys and Enter move between steps.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .styles import COLORS

START = "Show me around"
NEXT = "Next"
DONE = "Finish"
SKIP = "Skip tour"
BACK = "Back"
# Room between the highlighted widget and the card, and between the card and the window's edge.
GAP = 14
MARGIN = 16
CARD_WIDTH = 380


@dataclass(frozen=True)
class TourCopy:
    """What one step says. ``key`` is how a window binds it to a page and a widget."""

    key: str
    title: str
    body: str


WELCOME_STEPS: tuple[TourCopy, ...] = (
    TourCopy(
        "welcome",
        "Welcome to WarcraftLogs Analyzer",
        "It downloads your guild's raids from Warcraft Logs and breaks down every healer, tank and damage dealer, "
        "fight by fight. This short tour shows where everything is.",
    ),
    TourCopy(
        "settings",
        "Your keys, guild and look",
        "Settings holds your Warcraft Logs API keys and your guild. Run Setup there any time to change them, and "
        "pick a class theme under Appearance.",
    ),
    TourCopy(
        "download",
        "Download your raids",
        "Fetch Guild Reports lists your guild's recent logs; tick the raid days you care about, then Analyze "
        "Selected or Analyze All New. To grab one log, paste its link or code and press Analyze.",
    ),
    TourCopy(
        "browse",
        "Read a raid",
        "Analyzed raids land in Browse. Open one for healing, damage, tanking, consumables and a deep dive into each "
        "fight. Raid Diff and Reference compare two raids, or yours against a top guild's.",
    ),
    TourCopy(
        "search",
        "Find anything",
        "Search (or Ctrl+F) reaches any page or action by name, and your stored raids. Add a tab to jump straight "
        "to it: kara healing lists your Karazhan raids, each opening on its Healers tab. A pasted report link works "
        "too.",
    ),
    TourCopy(
        "character",
        "Choose your character",
        "Characters lists everyone in your raids. In My Character, enter your character's name, server and region, "
        "then Save & Refresh for your rankings. Claim your main and alts to jump between them.",
    ),
    TourCopy(
        "profile",
        "Raid profiles",
        "Raid with more than one team or play more than one era? Make a profile for each in Settings and switch "
        "here; every page then counts only that profile's raids.",
    ),
    TourCopy(
        "export",
        "Share what you find",
        "Export saves the page you are on as a PDF, Markdown or JSON report. Right-click any chart to save it as an "
        "image or copy it.",
    ),
    TourCopy(
        "navigate",
        "Get around fast",
        "Ctrl+1 to Ctrl+5 jump between these sections. You can take this tour again from Settings, or by searching "
        "for it.",
    ),
)


@dataclass(frozen=True)
class TourStep:
    """A step as a window shows it: its words, the widget (or widgets) to point at, and what to open first.

    With no target, or none of its widgets on screen, the card sits in the middle of the window.
    """

    copy: TourCopy
    target: Callable[[], QWidget | Sequence[QWidget] | None] | None = None
    prepare: Callable[[], object] | None = None


def card_position(target: QRect | None, card: QRect, bounds: QRect) -> QPoint:
    """Where the card's top-left goes: below the target, else above, right, left; centred with no target.

    The card stays inside *bounds* (less ``MARGIN``) whatever the target's place.
    """
    if target is None or target.isEmpty():
        return _clamp(_centred(bounds, card), card, bounds)
    centred = _centred(target, card)
    centre_x, centre_y = centred.x(), centred.y()
    options = (
        (bounds.bottom() - MARGIN - target.bottom() - GAP >= card.height(), QPoint(centre_x, target.bottom() + GAP)),
        (
            target.top() - GAP - MARGIN - bounds.top() >= card.height(),
            QPoint(centre_x, target.top() - GAP - card.height()),
        ),
        (bounds.right() - MARGIN - target.right() - GAP >= card.width(), QPoint(target.right() + GAP, centre_y)),
        (
            target.left() - GAP - MARGIN - bounds.left() >= card.width(),
            QPoint(target.left() - GAP - card.width(), centre_y),
        ),
    )
    for fits, place in options:
        if fits:
            return _clamp(place, card, bounds)
    # A target too big for the card to sit beside it: put the card inside it, bottom right.
    return _clamp(QPoint(target.right() - card.width() - GAP, target.bottom() - card.height() - GAP), card, bounds)


def _centred(outer: QRect, card: QRect) -> QPoint:
    return QPoint(outer.x() + (outer.width() - card.width()) // 2, outer.y() + (outer.height() - card.height()) // 2)


def _clamp(point: QPoint, card: QRect, bounds: QRect) -> QPoint:
    x = max(bounds.left() + MARGIN, min(point.x(), bounds.right() - MARGIN - card.width()))
    y = max(bounds.top() + MARGIN, min(point.y(), bounds.bottom() - MARGIN - card.height()))
    return QPoint(x, y)


class WelcomeTour(QWidget):
    """Covers *host* and walks through *steps*; ``finished`` says whether the user reached the last one."""

    finished = Signal(bool)

    def __init__(self, host: QWidget, steps: Sequence[TourStep]):
        super().__init__(host)
        if not steps:
            raise ValueError("A tour needs at least one step")
        self._host = host
        self._steps = list(steps)
        self._index = 0
        self._hole: QRect | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build_card()
        host.installEventFilter(self)

    # ── Building ──

    def _build_card(self) -> None:
        self.card = QFrame(self)
        self.card.setObjectName("tourCard")
        self.card.setFixedWidth(CARD_WIDTH)
        self.card.setStyleSheet(f"""
            QFrame#tourCard {{
                background-color: {COLORS["bg_card"]};
                border: 1px solid {COLORS["accent"]};
                border-radius: 8px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(8)

        self.counter = QLabel()
        self.counter.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        layout.addWidget(self.counter)

        self.title = QLabel()
        self.title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.title.setStyleSheet(f"color: {COLORS['text_gold']};")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setStyleSheet(f"color: {COLORS['text']}; font-size: 12px;")
        layout.addWidget(self.body)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.skip_button = QPushButton(SKIP)
        self.skip_button.setProperty("secondary", True)
        self.skip_button.clicked.connect(self.skip)
        buttons.addWidget(self.skip_button)
        buttons.addStretch()
        self.back_button = QPushButton(BACK)
        self.back_button.setProperty("secondary", True)
        self.back_button.clicked.connect(self.back)
        buttons.addWidget(self.back_button)
        self.next_button = QPushButton(NEXT)
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self.next)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

    # ── Driving ──

    def start(self) -> None:
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()
        self._show_step(0)
        self.setFocus()

    @property
    def index(self) -> int:
        return self._index

    def current(self) -> TourStep:
        return self._steps[self._index]

    def next(self) -> None:
        if self._index == len(self._steps) - 1:
            self._close(completed=True)
        else:
            self._show_step(self._index + 1)

    def back(self) -> None:
        if self._index > 0:
            self._show_step(self._index - 1)

    def skip(self) -> None:
        self._close(completed=False)

    def _show_step(self, index: int) -> None:
        self._index = index
        step = self._steps[index]
        if step.prepare is not None:
            step.prepare()
        last = index == len(self._steps) - 1
        self.counter.setText(f"{index + 1} of {len(self._steps)}")
        self.title.setText(step.copy.title)
        self.body.setText(step.copy.body)
        self.back_button.setVisible(index > 0)
        self.next_button.setText(START if index == 0 and not last else DONE if last else NEXT)
        self.skip_button.setVisible(not last)
        self.place()
        # A page just opened lays its widgets out on the next pass of the event loop: point again once it has.
        QTimer.singleShot(0, self.place)

    def _close(self, completed: bool) -> None:
        self._host.removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.deleteLater()

    # ── Geometry ──

    def target_rect(self) -> QRect | None:
        """Round the step's widgets on screen, in the overlay's coordinates; None when none of them is."""
        step = self.current()
        found = step.target() if step.target is not None else None
        widgets = [found] if isinstance(found, QWidget) else list(found or ())
        area = QRect()
        for widget in widgets:
            if widget.isVisible() and not widget.size().isEmpty():
                area = area.united(QRect(widget.mapTo(self._host, QPoint(0, 0)), widget.size()))
        if area.isEmpty():
            return None
        area = area.adjusted(-6, -6, 6, 6).intersected(self.rect())
        return None if area.isEmpty() else area

    def place(self) -> None:
        if not self.isVisible():
            return
        self.setGeometry(self._host.rect())
        self._hole = self.target_rect()
        self.card.adjustSize()
        self.card.move(card_position(self._hole, self.card.rect(), self.rect()))
        self.card.raise_()
        self.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            QTimer.singleShot(0, self.place)
        return False

    # ── Painting and input ──

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if self._hole is not None:
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self._hole), 6, 6)
            shade = shade.subtracted(hole)
        painter.fillPath(shade, QColor(0, 0, 0, 150))
        if self._hole is not None:
            painter.setPen(QPen(QColor(COLORS["accent"]), 2))
            painter.drawRoundedRect(QRectF(self._hole), 6, 6)
        painter.end()

    def mousePressEvent(self, event) -> None:
        event.accept()  # the window underneath waits until the tour is over

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.skip()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.next()
        elif key == Qt.Key.Key_Left:
            self.back()
        else:
            super().keyPressEvent(event)
