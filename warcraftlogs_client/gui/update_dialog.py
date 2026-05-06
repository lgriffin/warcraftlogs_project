"""
Update dialog — shows release notes, downloads update, and triggers install.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from .styles import COLORS, COMMON_STYLES
from ..updater import UpdateInfo, UpdateDownloader, apply_update
from ..version import __version__


class UpdateDialog(QDialog):
    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self._info = info
        self._downloader: UpdateDownloader | None = None
        self._zip_path: str | None = None

        self.setWindowTitle("Update Available")
        self.setMinimumSize(520, 420)
        self.setStyleSheet(COMMON_STYLES + f"""
            QDialog {{
                background-color: {COLORS['bg_card']};
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header = QLabel(f"Version {self._info.version} Available")
        header.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {COLORS['accent']};")
        layout.addWidget(header)

        current = QLabel(f"You have v{__version__}")
        current.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        layout.addWidget(current)

        notes_label = QLabel("What's new:")
        notes_label.setStyleSheet(f"color: {COLORS['text']}; font-weight: bold;")
        layout.addWidget(notes_label)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setMarkdown(self._info.release_notes or "No release notes.")
        self._notes.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-size: 12px;
            }}
        """)
        layout.addWidget(self._notes, 1)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setRange(0, 100)
        layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(f"color: {COLORS['error']}; font-size: 12px;")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._cancel_btn = QPushButton("Not Now")
        self._cancel_btn.setProperty("secondary", True)
        self._cancel_btn.setFixedWidth(100)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)

        self._action_btn = QPushButton("Download && Update")
        self._action_btn.setFixedWidth(180)
        self._action_btn.clicked.connect(self._on_action)
        btn_layout.addWidget(self._action_btn)

        layout.addLayout(btn_layout)

    def _on_cancel(self):
        if self._downloader and self._downloader.isRunning():
            self._downloader.cancel()
            self._downloader.wait(3000)
        self.reject()

    def _on_action(self):
        if self._zip_path:
            self._install()
        else:
            self._start_download()

    def _start_download(self):
        self._action_btn.setEnabled(False)
        self._action_btn.setText("Downloading...")
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._progress_label.setVisible(True)
        self._error_label.setVisible(False)

        self._downloader = UpdateDownloader(self._info, self)
        self._downloader.progress.connect(self._on_progress)
        self._downloader.finished.connect(self._on_download_done)
        self._downloader.error.connect(self._on_download_error)
        self._downloader.start()

    def _on_progress(self, done: int, total: int):
        if total > 0:
            pct = int(done / total * 100)
            self._progress_bar.setValue(pct)
            done_mb = done / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self._progress_label.setText(f"{done_mb:.1f} MB / {total_mb:.1f} MB")

    def _on_download_done(self, zip_path: str):
        self._zip_path = zip_path
        self._progress_bar.setValue(100)
        self._progress_label.setText("Download complete")
        self._action_btn.setText("Install && Restart")
        self._action_btn.setEnabled(True)

    def _on_download_error(self, message: str):
        self._error_label.setText(f"Download failed: {message}")
        self._error_label.setVisible(True)
        self._action_btn.setText("Retry")
        self._action_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        self._zip_path = None

    def _install(self):
        self._action_btn.setEnabled(False)
        self._action_btn.setText("Installing...")
        self._cancel_btn.setEnabled(False)

        try:
            apply_update(self._zip_path)
        except RuntimeError as e:
            self._error_label.setText(str(e))
            self._error_label.setVisible(True)
            self._action_btn.setText("Install && Restart")
            self._action_btn.setEnabled(True)
            self._cancel_btn.setEnabled(True)
            return

        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def closeEvent(self, event):
        self._on_cancel()
        event.accept()
