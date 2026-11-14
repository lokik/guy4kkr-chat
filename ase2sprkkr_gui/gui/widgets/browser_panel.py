"""Session-independent actions at the bottom of the expert-mode sidebar."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QStyle, QWidget


class BrowserPanel(QWidget):
    """Expose project browsing and window closing without a redundant group box."""

    projectBrowserRequested = pyqtSignal()
    closeRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.project_browser_button = QPushButton("Project Browser…", self)
        self.project_browser_button.setIcon(
            QIcon.fromTheme(
                "folder-documents",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            )
        )
        self.project_browser_button.clicked.connect(
            lambda _checked=False: self.projectBrowserRequested.emit()
        )
        layout.addWidget(self.project_browser_button, 1)

        self.close_button = QPushButton("Close", self)
        self.close_button.setIcon(
            QIcon.fromTheme(
                "window-close",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton),
            )
        )
        self.close_button.clicked.connect(
            lambda _checked=False: self.closeRequested.emit()
        )
        layout.addWidget(self.close_button)
