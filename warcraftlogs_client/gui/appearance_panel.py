"""
Settings section for the app's look: dark or light, and a class theme styled after one of the nine vanilla classes.

The choice belongs to whoever is signed in (``AppearanceService``). The class theme starts out following the main's
class; picking a class or "None" overrides that. The preview redraws as the choices change; Apply saves them and asks
the window to rebuild in the new theme.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..services import VANILLA_CLASSES, Appearance, AppearanceService, Palette, Theme, build_palette
from ..services.appearance import FOLLOW_MAIN, NO_CLASS
from ..services.themes import CLASS_STYLES
from .styles import COLORS

APPLY = "Apply theme"
MODES = (("Dark", "dark"), ("Light", "light"))


def follow_main_text(main_class: str | None) -> str:
    return f"Match my main ({main_class})" if main_class else "Match my main (not seen in a raid yet)"


def _swatch(color: str, size: int = 14) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class ThemePreview(QFrame):
    """A small card drawn in a palette that is not applied yet: heading, body text, dim text and a button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("themePreview")
        self.setFixedHeight(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        self.heading = QLabel("Gruul's Lair: 2/2")
        self.body = QLabel("Top healer this week: 1.2M effective healing")
        self.dim = QLabel("Last raid 3 days ago")
        row = QHBoxLayout()
        self.button = QLabel("Analyze")
        self.button.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.button.setFixedSize(QSize(96, 28))
        self.swatches = QLabel()
        row.addWidget(self.button)
        row.addWidget(self.swatches, 1)
        for widget in (self.heading, self.body, self.dim):
            layout.addWidget(widget)
        layout.addLayout(row)

    def show_palette(self, palette: Palette) -> None:
        c = palette.colors
        self.setStyleSheet(
            f"QFrame#themePreview {{ background-color: {c['bg_card']}; border: 1px solid {c['border']};"
            f" border-radius: 6px; }} QLabel {{ background: transparent; border: none; }}"
        )
        self.heading.setStyleSheet(f"color: {c['text_gold']}; font-size: 14px; font-weight: bold;")
        self.body.setStyleSheet(f"color: {c['text']}; font-size: 13px;")
        self.dim.setStyleSheet(f"color: {c['text_dim']}; font-size: 12px;")
        self.button.setStyleSheet(
            f"background-color: {c['accent']}; color: {c['on_accent']}; border-radius: 4px;"
            " font-size: 12px; font-weight: bold;"
        )
        dots = "".join(
            f"<span style='color: {c[t]}; font-size: 18px;'>&#9679;</span> "
            for t in ("accent", "purple", "success", "info", "quality_epic", "quality_legendary")
        )
        self.swatches.setText(dots)
        self.swatches.setTextFormat(Qt.TextFormat.RichText)
        self.swatches.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class AppearancePanel(QGroupBox):
    """Theme picker: mode, class theme, a live preview and Apply."""

    status_message = Signal(str)
    theme_applied = Signal(object)  # Theme

    def __init__(self, service: AppearanceService, parent=None):
        super().__init__("Appearance", parent)
        self.service = service
        self._main_class = service.main_class()
        saved = service.current()

        form = QFormLayout(self)
        form.setSpacing(12)

        self.mode = QComboBox()
        for label, mode in MODES:
            self.mode.addItem(label, mode)
        self.mode.setCurrentIndex(self.mode.findData(saved.mode))
        form.addRow("Mode:", self.mode)

        self.class_theme = QComboBox()
        self.class_theme.setIconSize(QSize(14, 14))
        main_icon = (
            COLORS["accent"] if self._main_class is None else build_palette("dark").class_colors[self._main_class]
        )
        self.class_theme.addItem(_swatch(main_icon), follow_main_text(self._main_class), FOLLOW_MAIN)
        self.class_theme.addItem(_swatch("#c9a42c"), "None (classic gold)", NO_CLASS)
        for name in VANILLA_CLASSES:
            self.class_theme.addItem(_swatch(CLASS_STYLES[name].color), name, name)
        self.class_theme.setCurrentIndex(self.class_theme.findData(saved.class_theme))
        self.class_theme.setToolTip("Colours styled after a vanilla class. Follows your main until you pick one.")
        form.addRow("Class theme:", self.class_theme)

        self.flavour = QLabel()
        self.flavour.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        form.addRow("", self.flavour)

        self.preview = ThemePreview()
        form.addRow("Preview:", self.preview)

        row = QHBoxLayout()
        self.apply_btn = QPushButton(APPLY)
        self.apply_btn.setFixedHeight(32)
        # Its own sheet: the Settings page paints every child's background, which would hide a plain button.
        self.apply_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS["accent"]};
                color: {COLORS["on_accent"]};
                border: none;
                border-radius: 4px;
                padding: 6px 18px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLORS["accent_hover"]}; }}
        """)
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(self.apply_btn)
        note = QLabel("Applying redraws the window. Each Discord account keeps its own theme.")
        note.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        note.setWordWrap(True)
        row.addWidget(note, 1)
        form.addRow(row)

        self.mode.currentIndexChanged.connect(self._refresh_preview)
        self.class_theme.currentIndexChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def chosen(self) -> Appearance:
        return Appearance(mode=self.mode.currentData(), class_theme=self.class_theme.currentData())

    def _refresh_preview(self) -> None:
        theme = self.service.theme(self.chosen())
        self.preview.show_palette(theme.palette)
        style = CLASS_STYLES.get(theme.wow_class) if theme.wow_class else None
        self.flavour.setText(style.flavour if style else "The original WoW-gold look")

    def apply(self) -> Theme:
        try:
            theme = self.service.save(self.chosen())
        except OSError as e:
            self.status_message.emit(f"Could not save the theme: {e}")
            return self.service.theme(self.chosen())
        self.status_message.emit(f"Theme: {theme.label}")
        self.theme_applied.emit(theme)
        return theme
