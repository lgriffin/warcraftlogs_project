"""
Application entry point for the WarcraftLogs Analyzer GUI.
"""

import logging
import sys

from PySide6.QtWidgets import QApplication

from .. import paths
from ..version import __version__
from .main_window import MainWindow
from .styles import COLORS


def run():
    logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
    paths.ensure_first_run_config()
    app = QApplication(sys.argv)
    app.setApplicationName("WarcraftLogs Analyzer")
    app.setApplicationVersion(__version__)

    app.setStyleSheet(f"""
        QToolTip {{
            background-color: {COLORS["bg_card"]};
            color: {COLORS["text"]};
            border: 1px solid {COLORS["border"]};
            padding: 4px 8px;
            font-size: 12px;
        }}
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
