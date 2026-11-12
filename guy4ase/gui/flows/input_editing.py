"""Expert-mode input-parameter use cases over the current workspace."""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.expert_input import (
    edit_input_parameters,
    select_input_parameters,
)
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.misc.structure_wait import document_change_applied


def create_input_parameters(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    dataset_default_mode: str,
    task: str = "scf",
) -> bool:
    """Create parameters for a task from the current read-only structure."""
    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation
    parameters = select_input_parameters(
        controller.atoms,
        parent=parent,
        task=task,
        dataset_default_mode=dataset_default_mode,
    )
    if parameters is None:
        return False
    return document_change_applied(
        parent,
        controller.replace_input_parameters(
            parameters,
            expected_input_parameters_generation=input_generation,
            expected_structure_generation=structure_generation,
        ),
    )


def edit_current_input_parameters(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    create_task: str | None = "scf",
    show_changed_only: bool = False,
    dataset_default_mode: str | None = None,
) -> bool:
    """Edit current parameters and commit only against captured dependencies."""
    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation
    parameters = controller.input_parameters
    if parameters is None:
        if create_task is None:
            return False
        if dataset_default_mode is None:
            raise ValueError("dataset_default_mode is required when creating parameters")
        return create_input_parameters(
            controller,
            parent,
            task=create_task,
            dataset_default_mode=dataset_default_mode,
        )

    atoms = controller.atoms
    parameters = parameters.copy(copy_values=True)

    edited = edit_input_parameters(
        parameters,
        parent=parent,
        show_changed_only=show_changed_only,
        atoms=atoms,
    )
    if edited is None:
        return False
    return document_change_applied(
        parent,
        controller.replace_input_parameters(
            edited,
            expected_input_parameters_generation=input_generation,
            expected_structure_generation=structure_generation,
        ),
    )


def load_and_edit_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    """Load workspace input parameters and immediately open the expert editor."""
    if not file_flows.choose_and_load_input_parameters(
        controller,
        recent_files,
        parent,
    ):
        return False
    return edit_current_input_parameters(
        controller,
        parent,
        create_task=None,
        show_changed_only=True,
    )
