"""A compact structure preview used by the two-sided 2D builder."""
from __future__ import annotations

from typing import Any

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.plots.lattice import plot_atoms_preview


class StructurePane(QWidget):
    """Display and expose actions for one structure in the 2D builder.

    The pane owns only presentation state. Transform semantics, error handling
    and coordination with the other pane remain responsibilities of the
    surrounding dialog.
    """

    scaleRequested = pyqtSignal()
    rotateRequested = pyqtSignal()
    matchAxisRequested = pyqtSignal()

    def __init__(
        self,
        atoms: Any | None = None,
        *,
        empty_text: str | None = None,
        show_formula: bool = False,
        figure_size: tuple[float, float] = (4.0, 3.2),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._atoms: Any | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        preview_row = QHBoxLayout()
        root.addLayout(preview_row, 1)

        self.figure = Figure(figsize=figure_size)
        self.canvas = FigureCanvas(self.figure)
        self.axes = self.figure.add_subplot(111, projection="3d")

        self._preview_stack: QStackedWidget | None = None
        if empty_text is None:
            preview_row.addWidget(self.canvas, 1)
        else:
            self._preview_stack = QStackedWidget(self)
            empty_label = QLabel(empty_text)
            empty_label.setStyleSheet("font-size: 14pt; color: palette(mid);")
            empty_label.setMinimumHeight(220)
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._preview_stack.addWidget(empty_label)
            self._preview_stack.addWidget(self.canvas)
            preview_row.addWidget(self._preview_stack, 1)

        controls = QVBoxLayout()
        self.scale_button = QPushButton("Scale...")
        self.scale_button.clicked.connect(self.scaleRequested)
        controls.addWidget(self.scale_button)
        self.rotate_button = QPushButton("Rotate...")
        self.rotate_button.clicked.connect(self.rotateRequested)
        controls.addWidget(self.rotate_button)
        self.match_axis_button = QPushButton("Match Other Axis")
        self.match_axis_button.clicked.connect(self.matchAxisRequested)
        controls.addWidget(self.match_axis_button)
        controls.addStretch(1)
        preview_row.addLayout(controls)

        lattice_box = QGroupBox("Lattice vectors")
        lattice_layout = QGridLayout(lattice_box)
        self._lattice_labels: list[list[QLabel]] = []
        for row_index in range(3):
            row: list[QLabel] = []
            lattice_layout.addWidget(
                QLabel(f"{chr(ord('a') + row_index)}:"), row_index, 0
            )
            for column_index in range(3):
                label = QLabel("–")
                label.setAlignment(
                    Qt.AlignmentFlag.AlignRight
                    | Qt.AlignmentFlag.AlignVCenter
                )
                lattice_layout.addWidget(
                    label, row_index, column_index + 1
                )
                row.append(label)
            self._lattice_labels.append(row)
        root.addWidget(lattice_box)

        self._formula_label = QLabel("") if show_formula else None
        if self._formula_label is not None:
            root.addWidget(self._formula_label)

        self.set_atoms(atoms)
        self.set_match_enabled(False)

    def set_atoms(self, atoms: Any | None) -> None:
        """Replace the displayed structure and refresh all pane presentation."""
        self._atoms = atoms
        present = atoms is not None
        self.scale_button.setEnabled(present)
        self.rotate_button.setEnabled(present)
        if self._preview_stack is not None:
            self._preview_stack.setCurrentIndex(1 if present else 0)
        if self._formula_label is not None:
            formula = atoms.get_chemical_formula() if present else ""
            self._formula_label.setText(f"Formula: {formula}" if formula else "")
        if present:
            plot_atoms_preview(self.axes, atoms, canvas=self.canvas)
        elif self._preview_stack is None:
            self.axes.clear()
            self.canvas.draw_idle()
        self.refresh_lattice()

    @property
    def atoms(self) -> Any | None:
        """Return the structure currently represented by the pane."""
        return self._atoms

    def refresh_lattice(self) -> None:
        """Update lattice values while clearing any mismatch highlighting."""
        if self.atoms is None:
            for row in self._lattice_labels:
                for label in row:
                    label.setText("–")
                    label.setStyleSheet("")
            return

        cell = np.asarray(self.atoms.get_cell(), dtype=float)
        for row_index, row in enumerate(self._lattice_labels):
            for column_index, label in enumerate(row):
                label.setText(f"{cell[row_index, column_index]:.6f}")
                label.setStyleSheet("")

    def highlight_axis(self, axis: int, highlighted: bool) -> None:
        """Highlight one lattice-vector row as mismatched."""
        for row_index, row in enumerate(self._lattice_labels):
            style = (
                "color: #b00020;"
                if highlighted and row_index == axis
                else ""
            )
            for label in row:
                label.setStyleSheet(style)

    def set_match_enabled(self, enabled: bool) -> None:
        self.match_axis_button.setEnabled(enabled and self.atoms is not None)
