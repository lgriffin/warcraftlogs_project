"""
Application entry point for the WarcraftLogs Analyzer GUI.
"""

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from .main_window import MainWindow
from .. import paths
from ..version import __version__


def run():
    paths.ensure_first_run_config()
    app = QApplication(sys.argv)
    app.setApplicationName("WarcraftLogs Analyzer")
    app.setApplicationVersion(__version__)

    app.setStyleSheet("""
        QToolTip {
            background-color: #16213e;
            color: #eee;
            border: 1px solid #2a2a4a;
            padding: 4px 8px;
            font-size: 12px;
        }
    """)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
