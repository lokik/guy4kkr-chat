"""Unit selector for structure dimensions."""
from __future__ import annotations

from typing import Callable, Dict, Iterable

from ase import units as ase_units
from PyQt6.QtWidgets import QComboBox, QWidget

length_units: Dict[str, float] = {
    "Angstrom (Å)": 1.0,
    "Nanometer (nm)": 10.0,
    "Picometer (pm)": 0.01,
    # Match the Tk version semantics: factor is relative to Angstrom
    "Rydberg (Ry)": ase_units.Rydberg / ase_units.Angstrom,
    "Bohr (a0)": ase_units.Bohr / ase_units.Angstrom,
}


def create_units_combo(parent: QWidget | None, callback: Callable[[float], None]) -> QComboBox:
    """Create a QComboBox with length units and invoke callback with the numeric factor on change.

    Args:
        parent: Parent QWidget (or None)
        callback: Function receiving the selected factor (float)
    Returns:
        The configured QComboBox instance.
    """
    combo = QComboBox(parent)
    items: Iterable[str] = list(length_units.keys())
    combo.addItems(items)
    # Default selection
    default_label = "Angstrom (Å)"
    idx = combo.findText(default_label)
    if idx >= 0:
        combo.setCurrentIndex(idx)

    def on_changed(_index: int) -> None:
        label = combo.currentText()
        factor = length_units.get(label, 1.0)
        callback(factor)

    combo.currentIndexChanged.connect(on_changed)
    return combo
