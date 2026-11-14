from __future__ import annotations

from typing import Any, Optional, Tuple

import numpy as np
from ase2sprkkr.ase.build import aperiodic_times
from ase2sprkkr.ase.build import rotate as rotate_by_hkl
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.plots.lattice import plot_atoms_preview
from ase2sprkkr_gui.physics.lattice import scale_lattice_to_lengths


def _plot_unit_vectors(ax, lattice: np.ndarray, vector_lengths: np.ndarray) -> None:
    lattice_lengths = np.linalg.norm(lattice, axis=1)
    if np.isclose(lattice_lengths, 0.0).any():
        return

    use_lengths = np.asarray(vector_lengths, dtype=float)
    if use_lengths.shape != (3,) or np.isclose(use_lengths, 0.0).any():
        return

    colors = ('#d62728', '#2ca02c', '#1f77b4')
    labels = ('â', 'b̂', 'ĉ')
    tips = []

    for vector, length, color, label, vector_length in zip(lattice, lattice_lengths, colors, labels, use_lengths):
        unit = vector / length
        tip = unit * float(vector_length)
        tips.append(tip)
        ax.quiver(
            0.0,
            0.0,
            0.0,
            tip[0],
            tip[1],
            tip[2],
            color=color,
            linewidth=1.8,
            arrow_length_ratio=0.2,
        )
        ax.text(tip[0], tip[1], tip[2], f" {label}", color=color, fontsize=9)

    if tips:
        tips_arr = np.asarray(tips, dtype=float)
        x_limits = ax.get_xlim()
        y_limits = ax.get_ylim()
        z_limits = ax.get_zlim()
        ax.set_xlim(min(x_limits[0], tips_arr[:, 0].min()), max(x_limits[1], tips_arr[:, 0].max()))
        ax.set_ylim(min(y_limits[0], tips_arr[:, 1].min()), max(y_limits[1], tips_arr[:, 1].max()))
        ax.set_zlim(min(z_limits[0], tips_arr[:, 2].min()), max(z_limits[1], tips_arr[:, 2].max()))


class _ScaleDialog(QDialog):
    def __init__(
        self,
        a0: float,
        b0: float,
        c0: float,
        *,
        base_lattice,
        preview_atoms: Optional[Any] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Scale Structure")
        self._updating = False
        self._base_lattice = np.asarray(base_lattice, dtype=float)
        self._preview_atoms = None if preview_atoms is None else preview_atoms.copy()
        self._base_lengths = {
            "a": float(a0),
            "b": float(b0),
            "c": float(c0),
        }
        self._length_spins: dict[str, QDoubleSpinBox] = {}
        self._relative_spins: dict[str, QDoubleSpinBox] = {}

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)

        grid.addWidget(QLabel("Axis"), 0, 0)
        grid.addWidget(QLabel("Absolute (Å)"), 0, 1)
        grid.addWidget(QLabel("Relative scale"), 0, 2)
        grid.addWidget(QLabel("Reset"), 0, 3)

        for row, axis in enumerate(("a", "b", "c"), start=1):
            base = self._base_lengths[axis]

            length_spin = QDoubleSpinBox(self)
            length_spin.setDecimals(6)
            length_spin.setRange(1e-6, 1e6)
            length_spin.setValue(base)
            length_spin.setSingleStep(max(abs(base) * 0.05, 0.01))

            relative_spin = QDoubleSpinBox(self)
            relative_spin.setDecimals(6)
            relative_spin.setRange(1e-6, 1e6)
            relative_spin.setValue(1.0)
            relative_spin.setSingleStep(0.05)

            reset_btn = QPushButton("Reset", self)

            grid.addWidget(QLabel(axis), row, 0)
            grid.addWidget(length_spin, row, 1)
            grid.addWidget(relative_spin, row, 2)
            grid.addWidget(reset_btn, row, 3)

            self._length_spins[axis] = length_spin
            self._relative_spins[axis] = relative_spin

            length_spin.valueChanged.connect(
                lambda value, ax=axis: self._on_absolute_changed(ax, float(value))
            )
            relative_spin.valueChanged.connect(
                lambda value, ax=axis: self._on_relative_changed(ax, float(value))
            )
            reset_btn.clicked.connect(lambda _checked=False, ax=axis: self._reset_axis(ax))

        info = QLabel("Changing absolute updates relative scale and vice versa.")
        layout.addWidget(info)

        self._figure = Figure(figsize=(4.2, 3.2), tight_layout=True)
        self._canvas = FigureCanvas(self._figure)
        self._ax = self._figure.add_subplot(111, projection='3d')
        layout.addWidget(self._canvas)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_preview()

    def _on_absolute_changed(self, axis: str, absolute_value: float) -> None:
        if self._updating:
            return
        base = self._base_lengths[axis]
        if base <= 0:
            return
        self._updating = True
        try:
            self._relative_spins[axis].setValue(absolute_value / base)
        finally:
            self._updating = False
        self._update_preview()

    def _on_relative_changed(self, axis: str, relative_value: float) -> None:
        if self._updating:
            return
        base = self._base_lengths[axis]
        self._updating = True
        try:
            self._length_spins[axis].setValue(base * relative_value)
        finally:
            self._updating = False
        self._update_preview()

    def _reset_axis(self, axis: str) -> None:
        self._updating = True
        try:
            self._length_spins[axis].setValue(self._base_lengths[axis])
            self._relative_spins[axis].setValue(1.0)
        finally:
            self._updating = False
        self._update_preview()

    def _update_preview(self) -> None:
        current_lengths = np.array(self.values(), dtype=float)
        lattice = scale_lattice_to_lengths(self._base_lattice, current_lengths)

        preview = None
        if self._preview_atoms is not None:
            preview = self._preview_atoms.copy()
            preview.set_cell(lattice, scale_atoms=True)

        original_lengths = np.array([
            self._base_lengths['a'],
            self._base_lengths['b'],
            self._base_lengths['c'],
        ], dtype=float)

        def _extra(ax, _atoms, plotted_lattice) -> None:
            if plotted_lattice is None:
                return
            _plot_unit_vectors(ax, np.asarray(plotted_lattice, dtype=float), original_lengths)

        plot_atoms_preview(
            self._ax,
            preview,
            canvas=self._canvas,
            fallback_lattice=lattice,
            extra_draw=_extra,
        )

    def values(self) -> Tuple[float, float, float]:
        return (
            float(self._length_spins["a"].value()),
            float(self._length_spins["b"].value()),
            float(self._length_spins["c"].value()),
        )


class _RepeatDialog(QDialog):
    def __init__(self, *, atoms: Optional[Any] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Repeat Structure")
        self._preview_atoms = atoms.copy() if atoms is not None else None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.nx_spin = QDoubleSpinBox(self)
        self.ny_spin = QDoubleSpinBox(self)
        self.nz_spin = QDoubleSpinBox(self)

        for spin in (self.nx_spin, self.ny_spin, self.nz_spin):
            spin.setDecimals(6)
            spin.setRange(1.0, 1e6)
            spin.setValue(1.0)
            spin.setSingleStep(0.5)

        form.addRow("Nx:", self.nx_spin)
        form.addRow("Ny:", self.ny_spin)
        form.addRow("Nz:", self.nz_spin)

        self.nx_spin.valueChanged.connect(lambda _value: self._update_preview())
        self.ny_spin.valueChanged.connect(lambda _value: self._update_preview())
        self.nz_spin.valueChanged.connect(lambda _value: self._update_preview())

        info = QLabel("Supports fractional repeats (e.g., 2.5).")
        layout.addWidget(info)

        self._figure = Figure(figsize=(4.2, 3.2), tight_layout=True)
        self._canvas = FigureCanvas(self._figure)
        self._ax = self._figure.add_subplot(111, projection='3d')
        layout.addWidget(self._canvas)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_preview()

    def values(self) -> Tuple[float, float, float]:
        return float(self.nx_spin.value()), float(self.ny_spin.value()), float(self.nz_spin.value())

    def _update_preview(self) -> None:
        repeated = None
        if self._preview_atoms is not None:
            try:
                repeated = aperiodic_times(self._preview_atoms.copy(), list(self.values()))
            except Exception:
                repeated = None

        plot_atoms_preview(self._ax, repeated, canvas=self._canvas)


class _RotateDialog(QDialog):
    def __init__(self, *, atoms: Optional[Any] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Rotate Structure (Miller hkl)")
        self._preview_atoms = atoms.copy() if atoms is not None else None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.h_spin = QSpinBox(self)
        self.k_spin = QSpinBox(self)
        self.l_spin = QSpinBox(self)

        for spin in (self.h_spin, self.k_spin, self.l_spin):
            spin.setRange(-1000, 1000)
            spin.setValue(1)

        form.addRow("h:", self.h_spin)
        form.addRow("k:", self.k_spin)
        form.addRow("l:", self.l_spin)

        self._validation_label = QLabel("")
        layout.addWidget(self._validation_label)

        self._figure = Figure(figsize=(4.2, 3.2), tight_layout=True)
        self._canvas = FigureCanvas(self._figure)
        self._ax = self._figure.add_subplot(111, projection='3d')
        layout.addWidget(self._canvas)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self.h_spin.valueChanged.connect(self._update_state)
        self.k_spin.valueChanged.connect(self._update_state)
        self.l_spin.valueChanged.connect(self._update_state)
        self._update_state()

    def _update_state(self) -> None:
        h, k, l = self.values()
        is_valid = not (h == 0 and k == 0 and l == 0)
        ok_btn = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setEnabled(is_valid)
        self._validation_label.setText("" if is_valid else "h, k, l cannot all be zero.")
        self._update_preview()

    def _update_preview(self) -> None:
        rotated = None
        h, k, l = self.values()
        if self._preview_atoms is not None and not (h == 0 and k == 0 and l == 0):
            try:
                rotated = rotate_by_hkl(self._preview_atoms.copy(), (h, k, l))
            except Exception:
                rotated = None

        plot_atoms_preview(self._ax, rotated, canvas=self._canvas)

    def values(self) -> Tuple[int, int, int]:
        return int(self.h_spin.value()), int(self.k_spin.value()), int(self.l_spin.value())


def select_scale_lengths(
    *,
    a0: float,
    b0: float,
    c0: float,
    base_lattice,
    preview_atoms: Optional[Any] = None,
    parent: Optional[QWidget] = None,
) -> Optional[Tuple[float, float, float]]:
    dlg = _ScaleDialog(
        a0,
        b0,
        c0,
        base_lattice=base_lattice,
        preview_atoms=preview_atoms,
        parent=parent,
    )
    if dlg.exec() != int(QDialog.DialogCode.Accepted):
        return None
    return dlg.values()


def select_repeat_factors(*, atoms: Optional[Any] = None, parent: Optional[QWidget] = None) -> Optional[Tuple[float, float, float]]:
    dlg = _RepeatDialog(atoms=atoms, parent=parent)
    if dlg.exec() != int(QDialog.DialogCode.Accepted):
        return None
    return dlg.values()


def select_rotate_hkl(*, atoms: Optional[Any] = None, parent: Optional[QWidget] = None) -> Optional[Tuple[int, int, int]]:
    dlg = _RotateDialog(atoms=atoms, parent=parent)
    if dlg.exec() != int(QDialog.DialogCode.Accepted):
        return None
    return dlg.values()


def scale_atoms(atoms: Any, *, parent: Optional[QWidget] = None) -> Optional[Any]:
    cell = atoms.get_cell()
    current_lengths = cell.lengths()
    values = select_scale_lengths(
        a0=float(current_lengths[0]),
        b0=float(current_lengths[1]),
        c0=float(current_lengths[2]),
        base_lattice=np.array(cell, dtype=float),
        preview_atoms=atoms,
        parent=parent,
    )
    if values is None:
        return None

    a_new, b_new, c_new = values
    new_lengths = np.array([a_new, b_new, c_new], dtype=float)
    scaled_cell = scale_lattice_to_lengths(cell, new_lengths)

    result = atoms.copy()
    result.set_cell(scaled_cell, scale_atoms=True)
    return result


def repeat_atoms(atoms: Any, *, parent: Optional[QWidget] = None) -> Optional[Any]:
    values = select_repeat_factors(atoms=atoms, parent=parent)
    if values is None:
        return None

    nx, ny, nz = values
    factors = np.array([nx, ny, nz], dtype=float)
    if (factors < 1.0).any():
        raise ValueError("Repeat factors Nx, Ny, Nz must be greater than or equal to 1.")

    return aperiodic_times(atoms.copy(), factors.tolist())


def rotate_atoms(atoms: Any, *, parent: Optional[QWidget] = None) -> Optional[Any]:
    values = select_rotate_hkl(atoms=atoms, parent=parent)
    if values is None:
        return None

    h, k, l = values
    if h == 0 and k == 0 and l == 0:
        raise ValueError("h, k, l cannot all be zero.")

    return rotate_by_hkl(atoms.copy(), (h, k, l))
