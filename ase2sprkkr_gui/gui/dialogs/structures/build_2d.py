from __future__ import annotations

from typing import Any, Optional

import numpy as np
from ase2sprkkr.sprkkr.build import semiinfinite_system
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.dialogs.structures.source import select_structure_source
from ase2sprkkr_gui.gui.dialogs.structures.transforms import rotate_atoms, scale_atoms
from ase2sprkkr_gui.gui.plots.lattice import plot_structure_axis_projection
from ase2sprkkr_gui.gui.widgets.structures.structure_pane import StructurePane
from ase2sprkkr_gui.physics.lattice import match_structure_axis_length


class Build2DStructureDialog(QDialog):
    def __init__(
        self,
        atoms: Any,
        parent: Optional[QWidget] = None,
        *,
        recent_files: RecentFiles,
        surface_mode: bool = False,
    ):
        super().__init__(parent)
        self._surface_mode = surface_mode
        self._recent_files = recent_files
        self.setWindowTitle("Build 2D Surface" if surface_mode else "Build 2D Structure")
        self.resize(1200, 760)

        self._semiinfinite_atoms: Optional[Any] = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._update_result_preview)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        root.addLayout(top, 1)

        left_group = QGroupBox("Main System")
        left_layout = QVBoxLayout(left_group)
        self.left = StructurePane(atoms.copy(), show_formula=True)
        self.left.scaleRequested.connect(
            lambda: self._transform(self.left, scale_atoms, "Scale (left)")
        )
        self.left.rotateRequested.connect(
            lambda: self._transform(self.left, rotate_atoms, "Rotate (left)")
        )
        self.left.matchAxisRequested.connect(
            lambda: self._match_axis(self.left, self.right, "Match axis (left)")
        )
        left_layout.addWidget(self.left, 1)
        top.addWidget(left_group, 1)

        right_col = QVBoxLayout()
        top.addLayout(right_col, 1)

        right_group = QGroupBox("Replacement System")
        right_layout = QVBoxLayout(right_group)

        self._choose_right_btn = QPushButton("Choose Structure...")
        self._choose_right_btn.setToolTip(
            "Create, download, load, or reuse a recent replacement structure"
        )
        self._choose_right_btn.clicked.connect(self._on_choose_right)
        right_layout.addWidget(self._choose_right_btn)

        self.right = StructurePane(
            empty_text="Vacuum", figure_size=(3.8, 2.8)
        )
        self.right.scaleRequested.connect(
            lambda: self._transform(self.right, scale_atoms, "Scale (right)")
        )
        self.right.rotateRequested.connect(
            lambda: self._transform(self.right, rotate_atoms, "Rotate (right)")
        )
        self.right.matchAxisRequested.connect(
            lambda: self._match_axis(
                self.right, self.left, "Match axis (right)"
            )
        )
        right_layout.addWidget(self.right, 1)
        right_col.addWidget(right_group, 1)

        if self._surface_mode:
            right_group.hide()
            self.left.match_axis_button.hide()

        params_group = QGroupBox("2D Build Parameters")
        params_layout = QFormLayout(params_group)

        self._repeat_left = QDoubleSpinBox(params_group)
        self._repeat_left.setDecimals(6)
        self._repeat_left.setRange(0.0, 30.0)
        self._repeat_left.setValue(0.0)
        self._repeat_left.setKeyboardTracking(False)
        self._repeat_left.valueChanged.connect(self._schedule_result_preview)
        params_layout.addRow("Repeat left:", self._repeat_left)

        self._repeat_right = QDoubleSpinBox(params_group)
        self._repeat_right.setDecimals(6)
        self._repeat_right.setRange(0.0, 30.0)
        self._repeat_right.setValue(0.0)
        self._repeat_right.setKeyboardTracking(False)
        self._repeat_right.valueChanged.connect(self._schedule_result_preview)
        right_repeat_label = (
            "Repeat vacuum:" if self._surface_mode else "Repeat right:"
        )
        params_layout.addRow(right_repeat_label, self._repeat_right)

        self._axis = QComboBox(params_group)
        self._axis.addItem("x", 0)
        self._axis.addItem("y", 1)
        self._axis.addItem("z", 2)
        self._axis.setCurrentIndex(2)
        self._axis.currentIndexChanged.connect(self._schedule_result_preview)
        params_layout.addRow("Axis:", self._axis)

        right_col.addWidget(params_group, 0)

        result_group = QGroupBox("Semiinfinite System")
        result_layout = QVBoxLayout(result_group)
        self._result_fig = Figure(figsize=(4.0, 3.2))
        self._result_canvas = FigureCanvas(self._result_fig)
        self._result_canvas.setMinimumSize(0, 0)
        self._result_canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._result_ax = self._result_fig.add_subplot(111)
        result_layout.addWidget(self._result_canvas, 1)
        root.addWidget(result_group, 1)

        self._status_label = QLabel("")
        root.addWidget(self._status_label)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_ok)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if self._ok_button is not None:
            self._ok_button.setEnabled(False)

        self._update_lattice_panels()
        self._update_result_preview()

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self._status_label.setText(message)
        if error:
            self._status_label.setStyleSheet("color: #b00020;")
        else:
            self._status_label.setStyleSheet("color: #2f6f2f;")

    def _update_lattice_panels(self) -> None:
        self.left.refresh_lattice()
        self.right.refresh_lattice()
        if self.right.atoms is None:
            return

        axis = int(self._axis.currentData())
        left_vec = np.asarray(self.left.atoms.get_cell()[axis], dtype=float)
        right_vec = np.asarray(self.right.atoms.get_cell()[axis], dtype=float)

        left_norm = np.linalg.norm(left_vec)
        right_norm = np.linalg.norm(right_vec)

        matches = False
        if left_norm > 1e-12 and right_norm > 1e-12:
            left_unit = left_vec / left_norm
            right_unit = right_vec / right_norm
            same_direction = np.allclose(left_unit, right_unit, atol=1e-3)
            same_length = np.isclose(
                left_norm, right_norm, rtol=1e-3, atol=1e-3
            )
            matches = bool(same_direction and same_length)

        self.left.highlight_axis(axis, not matches)
        self.right.highlight_axis(axis, not matches)

    def _set_right_atoms(self, atoms: Any) -> None:
        self.right.set_atoms(atoms)
        self.left.set_match_enabled(True)
        self.right.set_match_enabled(True)
        self._structures_changed()

    def _structures_changed(self) -> None:
        self._update_result_preview()

    def _on_choose_right(self) -> None:
        candidate = select_structure_source(
            self,
            recent_files=self._recent_files,
            title="Choose Replacement Structure",
        )
        if candidate is not None:
            self._set_right_atoms(candidate.atoms)

    def _transform(self, pane: StructurePane, operation, description: str) -> None:
        if pane.atoms is None:
            self._set_status(
                f"No structure available for {description.lower()}.", error=True
            )
            return
        updated = operation(pane.atoms, parent=self)
        if updated is None:
            return
        pane.set_atoms(updated)
        self._structures_changed()

    def _match_axis(
        self,
        pane: StructurePane,
        other: StructurePane,
        description: str,
    ) -> None:
        if pane.atoms is None or other.atoms is None:
            self._set_status(
                "No replacement structure to match against.", error=True
            )
            return

        axis = int(self._axis.currentData())
        try:
            updated = match_structure_axis_length(pane.atoms, other.atoms, axis)
        except ValueError as error:
            self._set_status(f"{description} failed: {error}", error=True)
            return

        pane.set_atoms(updated)
        self._structures_changed()

    def _schedule_result_preview(self, _value: Any = None) -> None:
        self._preview_timer.start()

    def _show_preview_error(self, error: ValueError) -> None:
        self._result_ax.clear()
        self._result_ax.set_axis_off()
        message = str(error) if str(error) else type(error).__name__
        self._result_ax.text(
            0.5,
            0.5,
            f"Preview error:\n{message}",
            ha="center",
            va="center",
            wrap=True,
            transform=self._result_ax.transAxes,
        )
        self._result_canvas.draw_idle()
        self._set_status(f"Preview error: {message}", error=True)

    def _update_result_preview(self) -> None:
        self._result_ax.clear()
        self._semiinfinite_atoms = None
        self._update_lattice_panels()
        if self._ok_button is not None:
            self._ok_button.setEnabled(False)

        left_repeat = float(self._repeat_left.value())
        right_repeat = float(self._repeat_right.value())
        repeat = (left_repeat, right_repeat)
        axis = int(self._axis.currentData())
        atoms = self.left.atoms.copy()
        atoms2 = (
            self.right.atoms.copy()
            if self.right.atoms is not None
            else None
        )

        try:
            semi = semiinfinite_system(
                atoms,
                repeat=repeat,
                atoms2=atoms2,
                axis=axis,
            )
        except ValueError as error:
            self._show_preview_error(error)
            return

        plot_structure_axis_projection(
            self._result_ax,
            semi,
            axis,
            canvas=self._result_canvas,
        )
        self._semiinfinite_atoms = semi
        self._set_status("Preview ready.")
        if self._ok_button is not None:
            self._ok_button.setEnabled(True)

    def _on_ok(self) -> None:
        if self._semiinfinite_atoms is None:
            self._set_status("Cannot accept: no valid semiinfinite system.", error=True)
            return
        self.accept()

    def result_atoms(self) -> Optional[Any]:
        if self._semiinfinite_atoms is None:
            return None
        return self._semiinfinite_atoms.copy()


def select_build_2d_structure(
    atoms: Any,
    parent: Optional[QWidget] = None,
    *,
    recent_files: RecentFiles,
    surface_mode: bool = False,
) -> Optional[Any]:
    dialog = Build2DStructureDialog(
        atoms,
        parent=parent,
        recent_files=recent_files,
        surface_mode=surface_mode,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.result_atoms()
