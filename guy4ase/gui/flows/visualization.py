"""Visualization workflows."""
from __future__ import annotations

from typing import Any

from ase import Atoms
from ase.visualize import view as ase_view
from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.viewers import viewer_unavailability
from guy4ase.gui.application.workspace_controller import WorkspaceController


def _visualization_atoms(atoms: Any) -> Atoms | None:
    """Return a plain ASE Atoms snapshot, without SPR-KKR runtime state."""
    if atoms is None:
        return None
    return Atoms(
        numbers=atoms.get_atomic_numbers(),
        positions=atoms.get_positions(),
        cell=atoms.get_cell(),
        pbc=atoms.get_pbc(),
    )


def visualize_structure(
    controller: WorkspaceController,
    settings: ApplicationSettings,
    parent: QWidget,
) -> bool:
    """Open a snapshot of the current structure in the configured ASE viewer."""
    atoms = _visualization_atoms(controller.atoms)
    if atoms is None:
        QMessageBox.information(
            parent,
            "No Structure",
            "Load or create a structure first.",
        )
        return False

    selected = settings.viewer
    reason = viewer_unavailability(selected)
    if reason is None:
        try:
            ase_view(atoms, viewer=selected)
        except Exception as exc:  # noqa: BLE001 - external viewer boundary
            reason = f"{type(exc).__name__}: {exc}"
        else:
            return True

    if selected == "ase":
        QMessageBox.critical(
            parent,
            "Visualization Error",
            f"Could not open the ASE viewer:\n{reason}",
        )
        return False

    answer = QMessageBox.warning(
        parent,
        "Viewer Not Available" if viewer_unavailability(selected) else "Visualization Error",
        (
            f"Could not open the structure with viewer '{selected}':\n"
            f"{reason}\n\n"
            "The viewer may not be installed or configured correctly. "
            "You can change it in Settings → Visualization.\n\n"
            "Open this structure using the ASE viewer instead?"
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False

    try:
        ase_view(atoms, viewer="ase")
    except Exception as exc:  # noqa: BLE001 - ASE viewer boundary
        QMessageBox.critical(
            parent,
            "Visualization Error",
            f"The fallback ASE viewer also failed:\n{type(exc).__name__}: {exc}",
        )
        return False
    return True
