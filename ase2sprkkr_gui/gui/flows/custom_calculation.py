"""Standalone custom task and input-file flows without workspace IP documents."""
from __future__ import annotations

from pathlib import Path

from ase2sprkkr import InputParameters
from ase2sprkkr.sprkkr.input_sources import existing_potential_files, load_existing_potential_input
from ase2sprkkr.sprkkr.executables import resolve_task_executable, task_system_error
from ase2sprkkr.sprkkr.sprkkr_atoms import system_kind_for_atoms
from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.workspace_controller import (
    CalculationRequest, WorkspaceController,
)
from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.dialogs.task_chooser import TaskChooserDialog
from ase2sprkkr_gui.gui.flows import calculation as calculation_flow
from ase2sprkkr_gui.gui.input_parameters.dataset import apply_default_dataset
from ase2sprkkr_gui.gui.input_parameters.tasks import is_guided_task
from ase2sprkkr_gui.gui.input_parameters.task_preferences import native_task_name
from ase2sprkkr_gui.gui.misc.modal_task import run_modal_task


_INPUT_FILTER = "SPR-KKR input files (*.inp *.in *.txt);;All files (*)"


def calculation_unavailable_reason(
    controller: WorkspaceController,
    parameters: InputParameters,
    *,
    file_source_directory: Path | None = None,
) -> str | None:
    """Check geometry/readiness without banning unsupported input editing."""
    task = parameters.task_definition
    if task is None:
        return "The input does not resolve to a registered SPR-KKR task."
    if controller.atoms is None:
        try:
            resolve_task_executable(task, parameters)
            existing_potential_files(
                parameters, file_source_directory or controller.directory or Path.cwd(),
            )
        except (OSError, ValueError) as error:
            return str(error)
        return None
    kind = system_kind_for_atoms(controller.atoms)
    reason = task_system_error(task, kind)
    if reason:
        return reason
    if kind == "embedded":
        if not controller.can_run_embedding():
            return "Attach a native host potential before running an embedded calculation."
        if controller.embedding_host_scf_status() == "START":
            return "Converge the host potential before running an embedded calculation."
    if task.name.upper() != "SCF" and controller.potential is None:
        return "This task requires an existing SPR-KKR potential."
    return None


def _custom_input_dialog(
    controller: WorkspaceController,
    parent: QWidget,
    parameters: InputParameters,
    input_directory: Path | None,
    *,
    recent_files: RecentFiles | None = None,
) -> QDialog:
    """Construct the editor on the GUI thread before hiding the load dialog."""
    source_directory = None
    if controller.atoms is None:
        source_directory = Path(input_directory or controller.directory or Path.cwd()).resolve()
    directory = source_directory or controller.directory or input_directory
    task = parameters.task_name

    def explanation(candidate):
        return calculation_unavailable_reason(
            controller, candidate, file_source_directory=source_directory,
        )

    if task is not None and is_guided_task(task):
        dialog = GuidedInputParametersDialog(
            task, parameters, parent=parent, atoms=controller.atoms,
            calculation_unavailable_reason=explanation,
            file_source_directory=source_directory,
            directory=directory,
            recent_files=recent_files,
        )
    else:
        dialog = InputParametersDialog(
            parameters, parent=parent, atoms=controller.atoms,
            calculation_mode=True,
            calculation_unavailable_reason=explanation,
            file_source_directory=source_directory,
            directory=directory,
            recent_files=recent_files,
        )
    return dialog


def edit_custom_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    parameters: InputParameters,
    *,
    input_directory: Path | None = None,
    track_launch_monitor=None,
    project_repository=None,
    prepared_dialog: QDialog | None = None,
) -> bool:
    """Edit an isolated input file, then optionally submit a single run."""
    expected_generation = controller.structure_generation
    source_directory = None
    if controller.atoms is None:
        source_directory = Path(input_directory or controller.directory or Path.cwd()).resolve()
    dialog = prepared_dialog if prepared_dialog is not None else _custom_input_dialog(
        controller, parent, parameters, input_directory,
        recent_files=recent_files,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return True  # The file may have been saved even if running was cancelled.

    parameters = dialog.parameters()
    if source_directory is None:
        request = calculation_flow._one_off_task_request(
            controller, parameters,
            expected_structure_generation=expected_generation, parent=parent,
        )
    else:
        try:
            source = load_existing_potential_input(parameters, source_directory)
            parameters = source.parameters
        except Exception as exc:  # noqa: BLE001 - native potential parsers expose varied errors
            QMessageBox.critical(parent, "Cannot Use Input Potentials", str(exc))
            return False
        request = CalculationRequest(
            atoms=source.potential.atoms,
            input_parameters=parameters,
            directory=str(source_directory),
            structure_id=None,
            state_id=None,
            potential=False,
            file_source=source,
        )
    if request is None:
        return False
    calculation_flow.run_calculation(
        controller, recent_files, parent,
        request_override=request,
        position_like_window="guided-input",
        track_launch_monitor=track_launch_monitor,
        project_repository=project_repository,
    )
    return True


def load_custom_input(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    path: str | Path,
    *,
    track_launch_monitor=None,
    project_repository=None,
) -> bool:
    """Read input into a local editor session, never a workspace document."""
    path = Path(path).expanduser().resolve()
    def prepare_editor(parameters: InputParameters):
        dialog = _custom_input_dialog(
            controller, parent, parameters, path.parent, recent_files=recent_files,
        )
        # Publishing recent history refreshes workflow action cards. Do this
        # before closing Working, rather than blocking the GUI afterwards.
        recent_files.remember("input", path)
        return parameters, dialog

    try:
        parameters, dialog = run_modal_task(
            parent, lambda: InputParameters.from_file(path),
            title="Loading Input", label="Preparing input editor…",
            on_success=prepare_editor,
        )
    except Exception as exc:  # noqa: BLE001 - parser errors vary by input schema
        QMessageBox.critical(parent, "Cannot Load Input", str(exc))
        return False
    return edit_custom_parameters(
        controller, recent_files, parent, parameters,
        input_directory=path.parent,
        prepared_dialog=dialog,
        track_launch_monitor=track_launch_monitor,
        project_repository=project_repository,
    )


def choose_custom_input(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    *,
    track_launch_monitor=None,
    project_repository=None,
) -> bool:
    path, _ = QFileDialog.getOpenFileName(
        parent, "Load SPR-KKR Input File", "", _INPUT_FILTER
    )
    return bool(path and load_custom_input(
        controller, recent_files, parent, path,
        track_launch_monitor=track_launch_monitor,
        project_repository=project_repository,
    ))


def choose_custom_task(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    *,
    dataset_default_mode: str,
    track_launch_monitor=None,
    project_repository=None,
) -> bool:
    picker = TaskChooserDialog(
        controller.atoms, parent, settings=getattr(parent, "settings", None),
    )
    if picker.exec() != QDialog.DialogCode.Accepted or not picker.selected_task:
        return False
    try:
        parameters = InputParameters.for_task(native_task_name(picker.selected_task))
        apply_default_dataset(parameters, dataset_default_mode, controller.atoms)
    except Exception as exc:  # noqa: BLE001 - native task registry definitions vary
        QMessageBox.critical(parent, "Cannot Create Custom Input", str(exc))
        return False
    return edit_custom_parameters(
        controller, recent_files, parent, parameters,
        track_launch_monitor=track_launch_monitor,
        project_repository=project_repository,
    )
