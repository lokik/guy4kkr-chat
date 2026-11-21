"""Task-specific DOS INFO page driven by ase2sprkkr parser events."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget

from ase2sprkkr.outputs.readers.dos import DosProgressParser


class DosProgressPage(QWidget):
    """Display only explicitly reported DOS energy-point completion."""

    def __init__(
        self, parent: QWidget | None = None, *, total_points: int | None = None
    ) -> None:
        super().__init__(parent)
        self.parser = DosProgressParser(
            on_info=self._on_info, total_points=total_points
        )
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Latest INFO", self))

        self.last_info = QLabel("Preparing DOS calculation...", self)
        self.last_info.setWordWrap(True)
        self.last_info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.last_info)

        self.progress = QProgressBar(self)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.events = QPlainTextEdit(self)
        self.events.setReadOnly(True)
        self.events.setMaximumBlockCount(1024)
        layout.addWidget(self.events, 1)

    def _on_info(self, *, kind: str, data: object) -> None:
        line = self.parser.format_info(kind, data)
        if line is None:
            return
        self.last_info.setText(line)
        self.events.appendPlainText(line)
        if kind == "dos_progress" and data.total is not None:
            self.progress.setRange(0, data.total)
            self.progress.setValue(data.completed)
            self.progress.show()

    def consume(self, text: str, kind: str) -> None:
        if kind.lower() not in {"err", "stderr"} and text:
            self.parser.feed(text)
