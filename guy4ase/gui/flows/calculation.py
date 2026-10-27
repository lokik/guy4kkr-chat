"""Stateless Qt workflow for running and recording a calculation."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.application.execution_profiles import profile_description
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import PotentialVersionChanged
from guy4ase.gui.application.window_geometry import window_placement
from guy4ase.gui.application.workspace_controller import (
    CalculationNotReady,
    WorkspaceController,
)
from guy4ase.gui.dialogs.expert_input import edit_input_parameters
from guy4ase.gui.dialogs.guided_input import (
    GuidedInputParametersDialog,
    GuidedTaskUnavailable,
    select_guided_input_parameters,
)
from guy4ase.gui.dialogs.profiles import ProfileSelectionDialog, RunIdentification
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow
from guy4ase.gui.input_parameters.dataset import dataset_value
from guy4ase.gui.input_parameters.tasks import is_guided_task
from guy4ase.gui.misc.structure_wait import document_change_applied

LaunchMonitorTracker = Callable[[SprkkrRunWindow], None]


def choose_working_directory(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    title: str = "Select Calculation Directory",
) -> bool:
    """Choose and publish the workspace calculation directory."""
    generation = controller.directory_generation
    start_directory = controller.directory or str(Path.home())
    directory = QFileDialog.getExistingDirectory(
        parent,
        title,
        start_directory,
    )
    if not directory:
        return False
    return document_change_applied(
        parent,
        controller.change_directory(
            str(directory),
            expected_directory_generation=generation,
        ),
    )


def _position_like_window(window: QWidget, window_id: str | None) -> None:
    """Reuse another managed window's top-left corner, not its size."""
    if window_id is None:
        return
    placement = window_placement(
        window,
        window_id,
        default_size=(window.width(), window.height()),
    )
    window.move(placement.geometry.topLeft())


def _select_profile(
    parent: QWidget,
    *,
    input_parameters,
    directory: str | None = None,
    position_like_window: str | None = None,
) -> tuple[bool, str | None, RunIdentification | None, str | None]:
    """Choose execution, run identifiers and the working directory together."""
    dialog = ProfileSelectionDialog(
        parent, input_parameters=input_parameters, directory=directory
    )
    _position_like_window(dialog, position_like_window)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return False, None, None, None
    return True, dialog.profile_name(), dialog.identification(), dialog.directory_name()


def _apply_run_identification(parameters, identification: RunIdentification | None) -> None:
    """Apply run-only overrides to the request's isolated parameter snapshot."""
    if identification is None:
        return
    if dataset_value(parameters) != identification.dataset:
        parameters.CONTROL.DATASET.set(identification.dataset)
    current_adsi = parameters.CONTROL.ADSI()
    if ("" if current_adsi is None else str(current_adsi)) != identification.adsi:
        parameters.CONTROL.ADSI.set(identification.adsi)


def run_calculation(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    *,
    select_profile: bool = True,
    profile_name: str | None = None,
    position_like_window: str | None = None,
    track_launch_monitor: LaunchMonitorTracker | None = None,
) -> SprkkrRunWindow | None:
    """Choose execution, run a task and record its immutable provenance.

    ``position_like_window`` optionally reuses another managed window's top-left
    corner for the profile picker and run window. ``track_launch_monitor``
    transfers ownership of an application-level top-level monitor before its
    worker starts; standalone callers that omit it retain ordinary parent
    ownership.
    """
    identification = None
    if select_profile:
        # Resolve the directory only after input-parameter editing. Cancelling
        # execution setup must not change the workspace.
        if (
            controller.atoms is None
            or controller.input_parameters is None
            or controller.structure_id is None
            or controller.state_id is None
        ):
            return None
        directory_generation = controller.directory_generation
        accepted, profile_name, identification, directory = _select_profile(
            parent,
            input_parameters=controller.input_parameters,
            directory=controller.directory,
            position_like_window=position_like_window,
        )
        if not accepted or not directory:
            return None
        if not document_change_applied(
            parent,
            controller.change_directory(
                directory, expected_directory_generation=directory_generation
            ),
        ):
            return None

    try:
        request = controller.create_calculation_request()
    except CalculationNotReady:
        return None
    _apply_run_identification(request.input_parameters, identification)

    def adoption_completed(adoption) -> None:
        if adoption.output_path is not None:
            recent_files.remember("output", adoption.output_path)
        if adoption.potential_error is not None:
            QMessageBox.warning(
                parent,
                "Potential Load Warning",
                "The calculation finished and was recorded, but its potential "
                f"could not be loaded:\n{adoption.potential_error}",
            )

    def finished(loaded) -> None:
        adoption = controller.adopt_calculation_result(
            loaded,
            request=request,
        )
        adoption_completed(adoption)

    try:
        description = profile_description(profile_name)
    except (KeyError, TypeError, ValueError):
        description = None

    window = SprkkrRunWindow(
        request=request,
        profile_name=profile_name,
        profile_description=description,
        parent=None if track_launch_monitor is not None else parent,
        on_finished=finished,
    )
    try:
        if track_launch_monitor is not None:
            track_launch_monitor(window)
        _position_like_window(window, position_like_window)
        window.show()
        window.start()
    except BaseException:
        window.close()
        raise
    return window


def configure_and_run_task(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    task: str,
    *,
    dataset_default_mode: str,
    track_launch_monitor: LaunchMonitorTracker | None = None,
) -> SprkkrRunWindow | None:
    """Configure one Guided task, commit it, choose execution, and run it."""
    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation
    atoms = controller.atoms
    if atoms is None:
        QMessageBox.information(
            parent,
            "No Structure",
            "Load or create a structure first.",
        )
        return None

    try:
        parameters = select_guided_input_parameters(
            task,
            parent=parent,
            atoms=atoms,
            dataset_default_mode=dataset_default_mode,
        )
    except GuidedTaskUnavailable as exc:
        QMessageBox.critical(
            parent,
            "Task Unavailable",
            str(exc),
        )
        return None

    if parameters is None:
        return None
    if not document_change_applied(
        parent,
        controller.replace_input_parameters(
            parameters,
            expected_input_parameters_generation=input_generation,
            expected_structure_generation=structure_generation,
        ),
    ):
        return None
    return run_calculation(
        controller,
        recent_files,
        parent,
        position_like_window="guided-input",
        track_launch_monitor=track_launch_monitor,
    )


def show_new_calculation_source_required(parent: QWidget) -> None:
    """Explain why a structure with multiple provenance branches needs selection."""
    QMessageBox.information(
        parent,
        "Select Calculation State",
        "This structure has multiple calculation branches. Select the result state "
        "you want to reuse first, then choose Use for New Calculation.",
    )


def use_for_new_calculation(
    controller: WorkspaceController,
    parent: QWidget,
    *,
    result_id: int | None = None,
    expected_potential: PotentialFileVersion | None = None,
) -> bool:
    """Confirm and atomically branch from the active or historical structure."""
    generation = controller.structure_generation
    answer = QMessageBox.question(
        parent,
        "Use for New Calculation?",
        "Keep the selected structure and reusable potential as starting density, "
        "reset the SCF stage, and use it for a new calculation?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False

    try:
        change = controller.use_for_new_calculation(
            result_id=result_id,
            expected_potential=expected_potential,
            expected_structure_generation=generation,
        )
    except PotentialVersionChanged as exc:
        QMessageBox.warning(
            parent,
            "Potential Changed",
            "The potential changed while the operation was being confirmed. "
            f"Please try again.\n{exc}",
        )
        return False
    return document_change_applied(parent, change)


def recompute_result(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    result_id: int,
    *,
    track_launch_monitor: LaunchMonitorTracker | None = None,
) -> SprkkrRunWindow | None:
    """Re-run historical settings on the state active in the workspace.

    Historical input parameters are only an editable starting point. Structure
    and potential always come from the current workspace, so selecting an old
    result never silently switches calculation lineage.
    """
    record = controller.result_store.result(result_id)
    if record.input_parameters is None:
        return None

    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation
    atoms = controller.atoms
    if atoms is None:
        return None

    try:
        parameters = record.input_parameters.copy(copy_values=True)
        task_name = parameters.task_name
    except AttributeError:
        return None

    position_like_window: str
    if is_guided_task(task_name):
        dialog = GuidedInputParametersDialog(
            task_name,
            parameters,
            parent=parent,
            atoms=atoms,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return None
        parameters = dialog.parameters()
        position_like_window = "guided-input"
    else:
        edited = edit_input_parameters(parameters, parent=parent, atoms=atoms)
        if edited is None:
            return None
        parameters = edited
        position_like_window = "expert-input"

    if not document_change_applied(
        parent,
        controller.replace_input_parameters(
            parameters,
            expected_input_parameters_generation=input_generation,
            expected_structure_generation=structure_generation,
        ),
    ):
        return None
    return run_calculation(
        controller,
        recent_files,
        parent,
        position_like_window=position_like_window,
        track_launch_monitor=track_launch_monitor,
    )
