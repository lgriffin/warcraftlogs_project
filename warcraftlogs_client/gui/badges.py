"""
Toads badges drawn as small round icons: the badge's glyph in a ring coloured by its tier's item quality.

Earned badges are drawn in colour; badges not earned yet are dimmed, so a player can see what is next.
The tooltip carries the detail: tier, count, stacks and what the next tier needs.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..services.badges import Badge
from .styles import COLORS

QUALITIES = ("uncommon", "rare", "epic", "legendary")


def badge_tooltip(badge: Badge) -> str:
    lines = [f"{badge.name}: {badge.tier_name}" if badge.earned else f"{badge.name}: not earned yet"]
    lines.append(f"{badge.description}: {badge.display}")
    if badge.stacks > 1:
        lines.append(f"Earned x{badge.stacks}")
    if badge.next_at is not None:
        lines.append(f"{badge.next_tier} at {badge.next_at:,}")
    return "\n".join(lines)


class BadgeChip(QLabel):
    """One badge as a small round icon."""

    def __init__(self, badge: Badge, size: int = 26, parent=None):
        super().__init__(badge.glyph, parent)
        self.badge = badge
        self.setObjectName(f"badge:{badge.id}")
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip(badge_tooltip(badge))
        ring = COLORS[f"quality_{badge.quality}"] if badge.quality in QUALITIES else COLORS["border"]
        faded = "" if badge.earned else f"color: {COLORS['text_dim']};"
        self.setStyleSheet(
            f"background-color: {COLORS['bg_input']}; border: 2px solid {ring}; border-radius: {size // 2}px;"
            f" font-size: {max(size // 2, 9)}px; padding: 0; {faded}"
        )


class BadgeStrip(QWidget):
    """A row of badge icons."""

    def __init__(self, badges: list[Badge] | None = None, size: int = 26, parent=None):
        super().__init__(parent)
        self._size = size
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self.chips: list[BadgeChip] = []
        self.set_badges(badges or [])

    def set_badges(self, badges: list[Badge]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        # Earned badges first, best tier first; rule order breaks ties.
        ordered = sorted(badges, key=lambda b: -b.tier)
        self.chips = [BadgeChip(b, self._size, self) for b in ordered]
        for chip in self.chips:
            self._layout.addWidget(chip)
        self._layout.addStretch()
