"""Parameters for the explicit XBand empty-sphere search."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


_DEFAULTS = {
    "min_radius": 0.65,
    "max_radius": 2.0,
    "max_spheres": 256,
    "mesh": (24, 24, 24),
}


def _mesh(value: Any) -> tuple[int, int, int]:
    if isinstance(value, int):
        return value, value, value
    try:
        values = tuple(int(item) for item in value)
    except (TypeError, ValueError):
        return _DEFAULTS["mesh"]
    return values if len(values) == 3 else _DEFAULTS["mesh"]


class EmptySpheresDialog(QDialog):
    """Edit parameters passed to ASE2SPRKKR's in-house/XBand finder."""

    def __init__(
        self,
        *,
        initial: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Empty Spheres")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.min_radius = self._radius_spin(float(_DEFAULTS["min_radius"]))
        self.max_radius = self._radius_spin(float(_DEFAULTS["max_radius"]))
        form.addRow("Minimum radius:", self.min_radius)
        form.addRow("Maximum radius:", self.max_radius)

        self.max_spheres = QSpinBox(self)
        self.max_spheres.setRange(1, 100000)
        self.max_spheres.setValue(int(_DEFAULTS["max_spheres"]))
        self.max_spheres.setToolTip("ASE2SPRKKR XBand parameter: max_spheres")
        form.addRow("Maximum number of spheres:", self.max_spheres)

        mesh_widget = QWidget(self)
        mesh_layout = QGridLayout(mesh_widget)
        mesh_layout.setContentsMargins(0, 0, 0, 0)
        self.mesh: list[QSpinBox] = []
        for column, (axis, value) in enumerate(zip("XYZ", _DEFAULTS["mesh"])):
            spin = QSpinBox(mesh_widget)
            spin.setRange(1, 10000)
            spin.setValue(int(value))
            mesh_layout.addWidget(QLabel(axis, mesh_widget), 0, column)
            mesh_layout.addWidget(spin, 1, column)
            self.mesh.append(spin)
        mesh_widget.setToolTip("ASE2SPRKKR XBand parameter: mesh")
        form.addRow("Search mesh:", mesh_widget)

        note = QLabel(
            "These settings are passed to ASE2SPRKKR's in-house XBand "
            "empty-sphere finder.",
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        restore = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if restore is not None:
            restore.clicked.connect(self._restore_defaults)
        layout.addWidget(buttons)

        self._load(initial or {})

    def _radius_spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setDecimals(4)
        spin.setRange(0.0, 100.0)
        spin.setSingleStep(0.05)
        spin.setValue(value)
        spin.setSuffix(" Å")
        return spin

    def _load(self, values: Mapping[str, Any]) -> None:
        self.min_radius.setValue(
            float(values.get("min_radius", _DEFAULTS["min_radius"]))
        )
        self.max_radius.setValue(
            float(values.get("max_radius", _DEFAULTS["max_radius"]))
        )
        self.max_spheres.setValue(
            int(values.get("max_spheres", _DEFAULTS["max_spheres"]))
        )
        mesh = _mesh(values.get("mesh", _DEFAULTS["mesh"]))
        for spin, value in zip(self.mesh, mesh):
            spin.setValue(value)

    def _restore_defaults(self) -> None:
        self._load(_DEFAULTS)

    def parameters(self) -> dict[str, Any]:
        return {
            "min_radius": self.min_radius.value(),
            "max_radius": self.max_radius.value(),
            "max_spheres": self.max_spheres.value(),
            "mesh": tuple(spin.value() for spin in self.mesh),
        }

    def accept(self) -> None:  # type: ignore[override]
        parameters = self.parameters()
        if parameters["min_radius"] > parameters["max_radius"]:
            QMessageBox.warning(
                self,
                "Invalid Empty-Sphere Parameters",
                "Minimum radius cannot exceed maximum radius.",
            )
            return
        super().accept()


def select_empty_spheres_parameters(
    *,
    initial: Mapping[str, Any] | None = None,
    parent: QWidget | None = None,
) -> dict[str, Any] | None:
    dialog = EmptySpheresDialog(initial=initial, parent=parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.parameters()
