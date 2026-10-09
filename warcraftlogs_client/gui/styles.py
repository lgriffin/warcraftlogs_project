"""
Shared styles for the application, drawn from the active theme's palette.

``COLORS``, ``CLASS_COLORS`` and ``SERIES`` hold the active palette's tokens (``wcl_app.themes``). ``apply_palette``
swaps them in place, so every widget built afterwards draws in the new theme; widgets already on screen keep the
colours they were built with, which is why switching theme rebuilds the main window.
"""

from PySide6.QtGui import QColor, QPalette

from ..services import Palette, build_palette

COLORS: dict[str, str] = {}
CLASS_COLORS: dict[str, str] = {}
SERIES: list[str] = []
_active: list[Palette] = []


def apply_palette(palette: Palette) -> None:
    """Make ``palette`` the one every widget built from now on draws with."""
    COLORS.clear()
    COLORS.update(palette.colors)
    CLASS_COLORS.clear()
    CLASS_COLORS.update(palette.class_colors)
    SERIES[:] = palette.series
    _active[:] = [palette]


def active_palette() -> Palette:
    return _active[0]


apply_palette(build_palette())


def qt_palette() -> QPalette:
    """The active theme as a Qt palette, for the widgets no style sheet reaches (menus, native dialogs)."""
    roles = {
        QPalette.ColorRole.Window: "bg_dark",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "bg_input",
        QPalette.ColorRole.AlternateBase: "bg_card",
        QPalette.ColorRole.ToolTipBase: "bg_card",
        QPalette.ColorRole.ToolTipText: "text",
        QPalette.ColorRole.PlaceholderText: "text_dim",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "bg_card",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.BrightText: "text_header",
        QPalette.ColorRole.Highlight: "accent",
        QPalette.ColorRole.HighlightedText: "on_accent",
        QPalette.ColorRole.Link: "accent",
    }
    palette = QPalette()
    for role, token in roles.items():
        palette.setColor(role, QColor(COLORS[token]))
    return palette


def app_styles() -> str:
    """The application-wide style sheet: tooltips, which no widget's own sheet reaches."""
    return f"""
        QToolTip {{
            background-color: {COLORS["bg_card"]};
            color: {COLORS["text"]};
            border: 1px solid {COLORS["border"]};
            padding: 4px 8px;
            font-size: 12px;
        }}
    """


def common_styles() -> str:
    """The style sheet every page starts from, in the active theme."""
    return f"""
    QWidget {{
        color: {COLORS["text"]};
        font-family: "Segoe UI", sans-serif;
    }}
    QLabel {{
        color: {COLORS["text"]};
    }}
    QLineEdit {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        padding: 8px 12px;
        font-size: 13px;
    }}
    QLineEdit:focus {{
        border-color: {COLORS["accent"]};
    }}
    QPushButton {{
        background-color: {COLORS["accent"]};
        color: {COLORS["on_accent"]};
        border: none;
        border-radius: 4px;
        padding: 8px 20px;
        font-size: 13px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {COLORS["accent_hover"]};
    }}
    QPushButton:disabled {{
        background-color: {COLORS["bg_hover"]};
        color: {COLORS["text_dim"]};
    }}
    QPushButton[secondary="true"] {{
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
    }}
    QPushButton[secondary="true"]:hover {{
        background-color: {COLORS["bg_hover"]};
        border-color: {COLORS["accent_dim"]};
    }}
    QComboBox {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    QComboBox:focus {{
        border-color: {COLORS["accent"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        selection-background-color: {COLORS["bg_hover"]};
        selection-color: {COLORS["text_header"]};
    }}
    QCheckBox {{
        color: {COLORS["text"]};
        spacing: 8px;
        font-size: 13px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
    }}
    QProgressBar {{
        background-color: {COLORS["bg_input"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        text-align: center;
        color: {COLORS["text"]};
        font-size: 11px;
        height: 20px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS["accent"]};
        border-radius: 3px;
    }}
    QTabWidget::pane {{
        background-color: {COLORS["bg_card"]};
        border: 1px solid {COLORS["border"]};
        border-top: none;
    }}
    QTabBar::tab {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text_dim"]};
        padding: 12px 24px;
        border: 1px solid {COLORS["border"]};
        border-bottom: none;
        margin-right: 2px;
        font-size: 12px;
    }}
    QTabBar::tab:selected {{
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text_gold"]};
        border-bottom: 2px solid {COLORS["accent"]};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {COLORS["bg_hover"]};
    }}
    QTabBar QToolButton {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text_gold"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 3px;
        padding: 4px;
        margin: 2px;
    }}
    QTabBar QToolButton:hover {{
        background-color: {COLORS["bg_hover"]};
        color: {COLORS["accent"]};
    }}
    QTableView {{
        background-color: {COLORS["bg_card"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        gridline-color: {COLORS["border"]};
        font-size: 12px;
        selection-background-color: {COLORS["bg_hover"]};
    }}
    QTableView::item {{
        padding: 6px 10px;
    }}
    QHeaderView::section {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text_gold"]};
        border: 1px solid {COLORS["border"]};
        padding: 6px 8px;
        font-size: 12px;
        font-weight: bold;
    }}
    QSpinBox {{
        background-color: {COLORS["bg_input"]};
        color: {COLORS["text"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    QSpinBox:focus {{
        border-color: {COLORS["accent"]};
    }}
    QGroupBox {{
        color: {COLORS["text_gold"]};
        border: 1px solid {COLORS["border"]};
        border-radius: 6px;
        margin-top: 14px;
        padding-top: 18px;
        font-size: 13px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
    }}
    QScrollArea {{
        border: none;
    }}
    QMessageBox {{
        background-color: {COLORS["bg_card"]};
    }}
    QMessageBox QLabel {{
        color: {COLORS["text"]};
        font-size: 13px;
        min-width: 300px;
    }}
    QMessageBox QPushButton {{
        min-width: 80px;
    }}
    QScrollBar:horizontal {{
        background-color: {COLORS["bg_mid"]};
        height: 12px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {COLORS["accent_dim"]};
        border-radius: 4px;
        min-width: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {COLORS["accent"]};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar:vertical {{
        background-color: {COLORS["bg_mid"]};
        width: 12px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background-color: {COLORS["accent_dim"]};
        border-radius: 4px;
        min-height: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {COLORS["accent"]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
"""
