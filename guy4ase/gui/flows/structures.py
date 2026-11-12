"""Stateless Qt workflows for creating and transforming structures."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ase2sprkkr.bindings.empty_spheres import add_empty_spheres
from PyQt6.QtWidgets import QMessageBox, QWidget

from guy4ase.ase.element_assignment import ElementAssignmentDraft
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.structures.build_2d import select_build_2d_structure
from guy4ase.gui.dialogs.structures.database import select_structure_prototype
from guy4ase.gui.dialogs.structures.element_assignment import select_site_elements
from guy4ase.gui.dialogs.structures.empty_spheres import select_empty_spheres_parameters
from guy4ase.gui.dialogs.structures.online_database import select_online_structure
from guy4ase.gui.dialogs.structures.spacegroup_selector import (
    select_spacegroup,
    select_spacegroup_from_prototype,
)
from guy4ase.gui.flows.structure_candidates import (
    create_structure_candidate,
    create_structure_from_database_candidate,
    download_structure_candidate,
)
from guy4ase.gui.misc.dialog_flow import DialogAction, chain_dialogs
from guy4ase.gui.misc.structure_wait import document_change_applied
from guy4ase.physics.lattice import detect_structure_kind


class _EmptySpheresBackendError(RuntimeError):
    """Expected failure reported by the external empty-sphere finder."""


def warn_if_structure_kind_is_unknown(atoms: Any, parent: QWidget) -> None:
    """Explain that loaded atoms are not a supported bulk/layered document."""
    if detect_structure_kind(atoms) != "unknown":
        return
    QMessageBox.warning(
        parent,
        "Unknown Structure Type",
        "The loaded structure could not be recognized as a supported "
        "3D bulk or SPR-KKR 2D layered structure. Check its periodic "
        "boundary conditions and, for a 2D structure, its left, central, "
        "and right regions before calculating.",
    )


def edit_current_structure(
    controller: WorkspaceController,
    parent: QWidget,
    editor: Callable[..., Any],
    *,
    error_title: str,
) -> bool:
    """Edit a detached copy of the current structure and publish on success."""
    generation = controller.structure_generation
    if controller.atoms is None:
        QMessageBox.information(
            parent, "No Structure", "Load or create a structure first."
        )
        return False

    change = controller.apply_structure_edit(
        lambda candidate: editor(candidate, parent=parent),
        expected_structure_generation=generation,
    )
    if change is None:
        return False
    return document_change_applied(parent, change)


def edit_site_elements(
    controller: WorkspaceController,
    parent: QWidget,
) -> bool:
    """Edit site occupations and commit the accepted draft transactionally."""
    generation = controller.structure_generation
    atoms = controller.atoms
    if atoms is None:
        QMessageBox.information(
            parent, "No Structure", "Load or create a structure first."
        )
        return False
    draft = ElementAssignmentDraft(atoms)

    result = select_site_elements(draft, parent=parent, apply=False)
    if result is None or result == DialogAction.BACK:
        return False

    change = controller.apply_structure_edit(
        lambda candidate: result.apply(candidate),
        expected_structure_generation=generation,
    )
    if change is None:
        return False
    return document_change_applied(parent, change)


def create_structure(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    generation = controller.structure_generation
    candidate = create_structure_candidate(
        parent,
        chain=chain_dialogs,
        spacegroup_selector=select_spacegroup,
        site_selector=select_site_elements,
    )
    if candidate is None:
        return None
    atoms = candidate.atoms
    change = controller.replace_structure(
        atoms,
        expected_structure_generation=generation,
    )
    if not document_change_applied(parent, change):
        return None
    return atoms


def create_structure_from_database(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    generation = controller.structure_generation
    candidate = create_structure_from_database_candidate(
        parent,
        chain=chain_dialogs,
        prototype_selector=select_structure_prototype,
        spacegroup_selector=select_spacegroup_from_prototype,
        site_selector=select_site_elements,
    )
    if candidate is None:
        return None
    atoms = candidate.atoms
    change = controller.replace_structure(
        atoms,
        expected_structure_generation=generation,
    )
    if not document_change_applied(parent, change):
        return None
    warn_if_structure_kind_is_unknown(atoms, parent)
    return atoms


def download_structure(
    controller: WorkspaceController, parent: QWidget
) -> Any | None:
    generation = controller.structure_generation
    candidate = download_structure_candidate(
        parent,
        selector=select_online_structure,
    )
    if candidate is None:
        return None
    atoms = candidate.atoms
    change = controller.replace_structure(
        atoms,
        expected_structure_generation=generation,
    )
    if not document_change_applied(parent, change):
        return None
    warn_if_structure_kind_is_unknown(atoms, parent)
    return atoms



def create_2d_from_new_structure(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    *,
    surface_mode: bool = False,
) -> Any | None:
    """Create a detached 3D candidate, then publish exactly one chosen result."""
    generation = controller.structure_generation
    candidate = create_structure_candidate(
        parent,
        chain=chain_dialogs,
        spacegroup_selector=select_spacegroup,
        site_selector=select_site_elements,
    )
    if candidate is None:
        return None

    bulk = candidate.atoms
    result = select_build_2d_structure(
        bulk.copy(),
        parent=parent,
        recent_files=recent_files,
        surface_mode=surface_mode,
    )
    if result is None:
        answer = QMessageBox.question(
            parent,
            "Keep 3D Structure?",
            "The 2D structure was not created. Keep the newly created "
            "3D structure instead? Choose No to discard it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        result = bulk

    change = controller.replace_structure(
        result,
        expected_structure_generation=generation,
    )
    if not document_change_applied(parent, change):
        return None
    return result


def build_2d_structure(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    *,
    surface_mode: bool = False,
) -> Any | None:
    generation = controller.structure_generation
    if controller.atoms is None:
        QMessageBox.information(
            parent, "No Structure", "Load or create a structure first."
        )
        return None
    if not controller.can_build_2d():
        QMessageBox.information(
            parent,
            "Build 2D Structure",
            "Build 2D Structure requires a 3D periodic bulk structure.",
        )
        return None

    def edit(candidate: Any, *, parent: QWidget | None = None) -> Any | None:
        return select_build_2d_structure(
            candidate,
            parent=parent,
            recent_files=recent_files,
            surface_mode=surface_mode,
        )

    change = controller.apply_structure_edit(
        lambda candidate: edit(candidate, parent=parent),
        expected_structure_generation=generation,
    )
    if change is None:
        return None
    if not document_change_applied(parent, change):
        return None
    return controller.atoms


def update_empty_spheres(
    controller: WorkspaceController, parent: QWidget
) -> bool:
    """Find empty spheres explicitly and publish the resulting structure."""
    if controller.empty_spheres_action() is None:
        QMessageBox.information(
            parent,
            "Empty Spheres",
            "Empty spheres cannot be updated for the current structure.",
        )
        return False

    generation = controller.structure_generation
    previous_state = controller.empty_spheres
    recalculate = previous_state is not None
    initial_parameters = (
        previous_state.parameters if previous_state is not None else None
    )
    parameters = select_empty_spheres_parameters(
        initial=initial_parameters, parent=parent
    )
    if parameters is None:
        return False

    if controller.structure_change_requires_scf_restart():
        answer = QMessageBox.question(
            parent,
            "Reset SCF State?",
            (
                "Changing empty spheres changes the site configuration. "
                "If this search adds or removes empty spheres, the current "
                "potential will no longer be active and a new SCF sequence "
                "will be required. Existing calculation results are kept.\n\n"
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

    def edit(atoms: Any, previous_count: int) -> tuple[Any, int, bool]:
        structure_changed = False
        if previous_count:
            if previous_count > len(atoms):
                raise ValueError(
                    "Stored empty-sphere provenance no longer matches the structure."
                )
            trailing = atoms.sites[-previous_count:]
            if not all(site.is_vacuum() for site in trailing):
                raise ValueError(
                    "Previously generated empty spheres are no longer the trailing sites."
                )
            del atoms[-previous_count:]
            structure_changed = True

        base_count = len(atoms)
        try:
            updated = add_empty_spheres(atoms, method="inhouse", **parameters)
        except Exception as exc:  # noqa: BLE001 - optional finder/backend boundary
            raise _EmptySpheresBackendError(str(exc)) from exc
        if updated is None:
            updated = atoms
        count = len(updated) - base_count
        structure_changed = structure_changed or updated is not atoms or count != 0
        return updated, count, structure_changed

    try:
        change = controller.update_empty_spheres(
            edit,
            expected_structure_generation=generation,
            parameters=parameters,
        )
    except _EmptySpheresBackendError as exc:
        QMessageBox.critical(
            parent,
            "Empty Spheres Error",
            f"Failed to update empty spheres:\n{exc}",
        )
        return False

    if not document_change_applied(parent, change):
        return False

    if controller.empty_spheres_added == 0:
        QMessageBox.information(
            parent,
            "Empty Spheres",
            (
                "No empty spheres were found. Previously generated empty spheres "
                "were removed."
                if recalculate
                else "No empty spheres were found for this structure."
            ),
        )
    return True
