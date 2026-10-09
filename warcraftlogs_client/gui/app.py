"""
Application entry point for the WarcraftLogs Analyzer GUI.
"""

import logging
import sys

from PySide6.QtWidgets import QApplication
from wcl_core import paths
from wcl_core.common.log import configure_logging, get_logger

from ..services import AppearanceService, Theme
from ..version import __version__
from .home_view import desktop_context
from .main_window import MainWindow
from .styles import app_styles, apply_palette, qt_palette

logger = get_logger(__name__)


def apply_theme(app: QApplication, theme: Theme) -> None:
    """Make ``theme`` the app's: every widget built from now on, and the app-wide palette and tooltips."""
    apply_palette(theme.palette)
    app.setPalette(qt_palette())
    app.setStyleSheet(app_styles())


def saved_theme() -> Theme | None:
    """The signed-in user's saved theme, or None (the classic dark look) when it cannot be read."""
    try:
        return AppearanceService.desktop(desktop_context()).theme()
    except (OSError, ValueError) as e:
        logger.warning("Could not read the saved theme: %s", e)
        return None


class WindowHost:
    """Owns the main window, and rebuilds it when Settings applies a new theme.

    Widgets take their colours when they are built, so a new theme means a new window: it opens where the old one
    was, on Settings, and the old one closes (stopping its workers as a normal close does).
    """

    def __init__(self, app: QApplication):
        self.app = app
        self.window = self._open()

    def _open(self) -> MainWindow:
        window = MainWindow()
        window.theme_changed.connect(self.rebuild)
        return window

    def rebuild(self, theme: Theme) -> MainWindow:
        apply_theme(self.app, theme)
        old = self.window
        self.window = self._open()
        self.window.setGeometry(old.geometry())
        self.window._show_settings()
        if old.isMaximized():
            self.window.showMaximized()
        else:
            self.window.show()
        old.close()
        old.deleteLater()
        return self.window


def run():
    configure_logging(logging.DEBUG)
    paths.ensure_first_run_config()
    app = QApplication(sys.argv)
    app.setApplicationName("WarcraftLogs Analyzer")
    app.setApplicationVersion(__version__)

    theme = saved_theme()
    if theme is not None:
        apply_theme(app, theme)
    else:
        app.setPalette(qt_palette())
        app.setStyleSheet(app_styles())

    host = WindowHost(app)
    host.window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
