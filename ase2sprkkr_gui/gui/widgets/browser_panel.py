"""Session-independent entry points for browsing durable calculation data."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QPushButton, QVBoxLayout, QWidget


class BrowserPanel(QGroupBox):
    """Request durable browsers owned by the application composition root."""

    projectBrowserRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Browse", parent)

        layout = QVBoxLayout(self)
        self.project_browser_button = QPushButton("Project Browser…", self)
        self.project_browser_button.clicked.connect(
            lambda _checked=False: self.projectBrowserRequested.emit()
        )
        layout.addWidget(self.project_browser_button)
