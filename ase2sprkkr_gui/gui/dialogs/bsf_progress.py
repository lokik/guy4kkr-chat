"""BSF INFO page driven entirely by ase2sprkkr native parser events."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget

from ase2sprkkr.outputs.readers.bsf import BsfProgressParser


class BsfProgressPage(QWidget):
    """Live E-k / k-k milestones; native stdout has no trustworthy percentage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.parser = BsfProgressParser(on_info=self._on_info)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Latest INFO", self))

        self.last_info = QLabel("Preparing BSF calculation...", self)
        self.last_info.setWordWrap(True)
        self.last_info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.last_info)

        self.rank_progress_label = QLabel(
            "Approximate progress of the reporting MPI rank", self
        )
        self.rank_progress_label.hide()
        layout.addWidget(self.rank_progress_label)

        self.progress = QProgressBar(self)
        self.progress.setFormat("%p%")
        self.progress.hide()
        layout.addWidget(self.progress)
        self._rank_total: int | None = None

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
        if kind == "bsf_rank_progress":
            self._rank_total = data.total
            self.progress.setRange(0, data.total)
            # IE is printed when its k-loop begins; completed loops = entered-1.
            self.progress.setValue(data.completed)
            self.rank_progress_label.show()
            self.progress.show()
        elif kind == "bsf_finished" and self._rank_total:
            self.progress.setValue(self._rank_total)

    def consume(self, text: str, kind: str) -> None:
        if kind.lower() not in {"err", "stderr"} and text:
            self.parser.feed(text)
