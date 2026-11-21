"""Stateless Qt workflow for running and recording a calculation."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget
from kkrunner.projects import ProjectRepository

from ase2sprkkr_gui.gui.application.execution_profiles import profile_description
from ase2sprkkr_gui.gui.application.potential_version import PotentialFileVersion
from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.result_loading import PotentialVersionChanged
from ase2sprkkr_gui.gui.application.window_geometry import window_placement
from ase2sprkkr_gui.gui.application.workspace_controller import (
    CalculationNotReady,
    CalculationRequest,
    WorkspaceController,
)
from ase2sprkkr_gui.gui.dialogs.expert_input import edit_input_parameters
from ase2sprkkr_gui.gui.dialogs.guided_input import (
    GuidedInputParametersDialog,
    GuidedTaskUnavailable,
    select_guided_input_parameters,
)
from ase2sprkkr_gui.gui.dialogs.profiles import ProfileSelectionDialog, RunIdentification
from ase2sprkkr_gui.gui.dialogs.run_calculation import SprkkrRunWindow
from ase2sprkkr_gui.gui.application.execution_cancellation import RunCancellation
from ase2sprkkr_gui.gui.application.sprkkr_execution import SprkkrExecution
from ase2sprkkr_gui.gui.input_parameters.dataset import dataset_value
from ase2sprkkr_gui.gui.input_parameters.tasks import is_guided_task
from ase2sprkkr_gui.gui.misc.structure_wait import document_change_applied

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
    project_repository: ProjectRepository | None = None,
    active_project_id: str | None = None,
    position_like_window: str | None = None,
    selected_profile_name: str | None = None,
    initial_identification: RunIdentification | None = None,
    initial_clear_cache: bool = False,
    directory_is_explicit: bool = False,
) -> tuple[bool, str | None, RunIdentification | None, str | None, str | None, bool, bool]:
    """Choose a run or preparation-only operation with the same identifiers."""
    dialog = ProfileSelectionDialog(
        parent,
        input_parameters=input_parameters,
        directory=directory,
        project_repository=project_repository,
        active_project_id=active_project_id,
        selected_profile_name=selected_profile_name,
        initial_identification=initial_identification,
        initial_clear_cache=initial_clear_cache,
        directory_is_explicit=directory_is_explicit,
    )
    _position_like_window(dialog, position_like_window)
    if dialog.exec() != dialog.DialogCode.Accepted:
        return False, None, None, None, None, False, False
    return (
        True, dialog.profile_name(), dialog.identification(),
        dialog.directory_name(), dialog.project_id(), dialog.save_only_selected(),
        dialog.clear_cache_selected(),
    )


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
    initial_identification: RunIdentification | None = None,
    initial_clear_cache: bool = False,
    restore_run_directory: bool = False,
    track_launch_monitor: LaunchMonitorTracker | None = None,
    project_repository: ProjectRepository | None = None,
    request_override: CalculationRequest | None = None,
    on_result_loaded: Callable | None = None,
) -> SprkkrRunWindow | None:
    """Choose execution, run a task and record its immutable provenance.

    ``position_like_window`` optionally reuses another managed window's top-left
    corner for the profile picker and run window. ``track_launch_monitor``
    transfers ownership of an application-level top-level monitor before its
    worker starts; standalone callers that omit it retain ordinary parent
    ownership.
    """
    # Guided actions are not the only entry point (Expert Mode also calls this
    # function). Never submit an embedded run against a START periodic host.
    # A partially converged host is permitted only after explicit confirmation.
    check_host = False
    host_status = None
    if request_override is not None and request_override.potential is False:
        host = getattr(request_override.atoms, "embedding_host", None)
        if host is not None:
            check_host = True
            host_status = host.SCF_INFO.SCFSTATUS()
    elif request_override is None or request_override.potential is None:
        check_host = controller.structure_kind() == "0d" and controller.can_run_embedding()
        if check_host:
            host_status = controller.embedding_host_scf_status()
    if check_host:
        if host_status == "START":
            QMessageBox.information(
                parent, "Host SCF Required",
                "The periodic host potential has not been calculated. "
                "Run Converge Host SCF before starting an embedded calculation.",
            )
            return None
        if host_status != "CONVERGED":
            answer = QMessageBox.warning(
                parent, "Host SCF Not Converged",
                "The periodic host potential is not SCF-converged "
                f"(status: {host_status or 'unknown'}). "
                "Embedding results obtained with this host may be unreliable. "
                "Continue with the embedded calculation?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None

    identification = initial_identification
    project_id = controller.active_project_id
    prepare_only = False
    clear_cache = (
        request_override.clear_cache if request_override is not None
        else initial_clear_cache
    )
    if select_profile:
        # Resolve the directory only after input-parameter editing. Cancelling
        # execution setup must not change the workspace.
        if request_override is None and (
            controller.atoms is None or controller.input_parameters is None
            or controller.structure_id is None or controller.state_id is None
        ):
            return None
        directory_generation = controller.directory_generation
        project_generation = controller.active_project_generation
        initial_directory = controller.directory
        if request_override is not None and not restore_run_directory:
            initial_directory = request_override.directory or initial_directory
        selection = _select_profile(
            parent,
            input_parameters=(request_override.input_parameters if request_override is not None
                              else controller.input_parameters),
            directory=initial_directory,
            project_repository=project_repository,
            active_project_id=project_id,
            position_like_window=position_like_window,
            selected_profile_name=profile_name,
            initial_identification=initial_identification,
            initial_clear_cache=clear_cache,
            directory_is_explicit=restore_run_directory,
        )
        accepted, profile_name, identification, directory, project_id = selection[:5]
        prepare_only = bool(selection[5]) if len(selection) > 5 else False
        clear_cache = bool(selection[6]) if len(selection) > 6 else clear_cache
        if not accepted or not directory:
            return None
        # Selecting a project for a run also makes it the active project.
        # An explicit "Unassigned" selection clears the active project.
        if not document_change_applied(
            parent,
            controller.set_calculation_context(
                directory,
                project_id,
                expected_directory_generation=directory_generation,
                expected_active_project_generation=project_generation,
            ),
        ):
            return None

    try:
        request = (replace(request_override, directory=controller.directory or request_override.directory)
                   if request_override is not None
                   else controller.create_calculation_request())
    except CalculationNotReady:
        return None
    # A submitted run writes the input parameters to its calculation directory.
    # Remember which workspace revision it came from: edits made while the
    # calculation runs must remain unsaved. Explicit request overrides (e.g.
    # host SCF) do not represent the workspace's input-parameter document.
    submitted_input_generation = (
        controller.input_parameters_generation if request_override is None else None
    )
    _apply_run_identification(request.input_parameters, identification)
    request = replace(request, clear_cache=clear_cache)

    if prepare_only:
        execution = SprkkrExecution(
            request, RunCancellation(), profile_name=profile_name,
        )
        try:
            written, input_file, host_file, _output_file = execution.prepare_files()
        except Exception as exc:  # noqa: BLE001 - native writers expose varied errors
            QMessageBox.critical(parent, "Save SPR-KKR Files Failed", str(exc))
            return None
        cluster_file = written.CONTROL.POTFIL_CLU()
        additional = f"\nCluster potential: {cluster_file}" if cluster_file else ""
        if submitted_input_generation is not None:
            controller.mark_input_parameters_saved(submitted_input_generation)
        if input_file is not None:
            recent_files.remember("input", input_file)
        QMessageBox.information(
            parent, "SPR-KKR Files Prepared",
            f"Input: {input_file}\nHost potential: {host_file}{additional}\n"
            "No calculation was started.",
        )
        return None

    def adoption_completed(adoption) -> None:
        recent_files.remember_result(
            adoption.output_path,
            potential_path=(
                adoption.potential_path if adoption.potential_error is None else None
            ),
        )
        if adoption.potential_error is not None:
            QMessageBox.warning(
                parent,
                "Potential Load Warning",
                "The calculation finished and was recorded, but its potential "
                f"could not be loaded:\n{adoption.potential_error}",
            )

    def finished(loaded) -> None:
        adoption = (controller.adopt_calculation_result(loaded, request=request)
                    if on_result_loaded is None else
                    on_result_loaded(loaded, request))
        adoption_completed(adoption)

    def submitted(input_file: str | None) -> None:
        if submitted_input_generation is not None:
            # submit() returned successfully; input files are already written.
            # Later workspace edits retain their own unsaved generation.
            controller.mark_input_parameters_saved(submitted_input_generation)
        if input_file is not None:
            recent_files.remember("input", input_file)

    try:
        description = profile_description(profile_name)
    except (KeyError, TypeError, ValueError):
        description = None

    def back_to_run_setup() -> None:
        # Submission was rejected before the new job started. Open the
        # normal setup dialog again, without discarding the user's last choices.
        # The run identifiers were request-only overrides, not workspace edits.
        run_calculation(
            controller,
            recent_files,
            parent,
            profile_name=profile_name,
            position_like_window=position_like_window,
            initial_identification=identification,
            initial_clear_cache=clear_cache,
            restore_run_directory=True,
            track_launch_monitor=track_launch_monitor,
            project_repository=project_repository,
            request_override=request_override,
            on_result_loaded=on_result_loaded,
        )

    window = SprkkrRunWindow(
        request=request,
        profile_name=profile_name,
        profile_description=description,
        project_id=project_id,
        parent=None if track_launch_monitor is not None else parent,
        on_finished=finished,
        on_submitted=submitted,
        on_back_to_setup=back_to_run_setup if select_profile else None,
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


def _one_off_task_request(
    controller: WorkspaceController,
    parameters,
    *,
    expected_structure_generation,
    parent: QWidget,
    restart_scf: bool = False,
) -> CalculationRequest | None:
    """Build a Guided request without creating an input document in workspace.

    A transient Guided task has the same structure/state provenance as an
    Expert task, but its parameters belong only to this run and its history.
    """
    if controller.structure_generation != expected_structure_generation:
        QMessageBox.warning(
            parent, "Structure Changed",
            "The structure changed while configuring this calculation. "
            "Please choose its parameters again.",
        )
        return None
    if controller.atoms is None or controller.structure_id is None or controller.state_id is None:
        return None
    return CalculationRequest(
        atoms=controller.atoms,
        input_parameters=parameters.copy(copy_values=True),
        directory=controller.directory or "",
        structure_id=controller.structure_id,
        state_id=controller.state_id,
        restart_scf=controller.restarted or restart_scf,
    )


def configure_and_run_task(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    task: str,
    *,
    dataset_default_mode: str,
    restart_scf: bool = False,
    track_launch_monitor: LaunchMonitorTracker | None = None,
    project_repository: ProjectRepository | None = None,
) -> SprkkrRunWindow | None:
    """Configure and run a one-off Guided task without editing workspace inputs."""
    structure_generation = controller.structure_generation
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
            directory=controller.directory,
            recent_files=recent_files,
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
    if controller.structure_kind() == "0d" and not controller.can_run_embedding():
        # The Guided SCF command remains visible for clusters built from ASE
        # geometry. Resolve the external native host only after the user has
        # accepted the parameter editor, without launching a periodic binary.
        from ase2sprkkr_gui.gui.flows.files import ensure_embedded_host_potential

        if not ensure_embedded_host_potential(controller, parent):
            return None
        structure_generation = controller.structure_generation
    request = _one_off_task_request(
        controller, parameters,
        expected_structure_generation=structure_generation, parent=parent,
        restart_scf=restart_scf,
    )
    if request is None:
        return None
    return run_calculation(
        controller,
        recent_files,
        parent,
        position_like_window="guided-input",
        track_launch_monitor=track_launch_monitor,
        project_repository=project_repository,
        request_override=request,
    )


def configure_and_run_host_scf(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
    *,
    dataset_default_mode: str,
    restart_host_scf: bool = False,
    track_launch_monitor: LaunchMonitorTracker | None = None,
    project_repository: ProjectRepository | None = None,
) -> SprkkrRunWindow | None:
    """Run periodic host SCF without replacing the embedded cluster workspace.

    On completion, adopt the host Potential into the *current* cluster if it
    still refers to the host used for the launch, even if cluster sites have
    been edited meanwhile. The independent periodic result is also recorded.
    """
    from ase2sprkkr import Potential

    cluster = controller.atoms
    host = getattr(cluster, "embedding_host", None)
    if controller.structure_kind() != "0d" or not isinstance(host, Potential):
        QMessageBox.warning(
            parent, "Host Potential Required",
            "Attach a periodic SPR-KKR host potential before calculating its SCF.",
        )
        return None
    if restart_host_scf and controller.embedding_host_scf_status() == "START":
        QMessageBox.information(
            parent, "Host SCF Not Started",
            "The host has no previous SCF cycle to restart. "
            "Use Converge Host SCF instead.",
        )
        return None

    try:
        parameters = select_guided_input_parameters(
            "scf", parent=parent, atoms=host.atoms,
            dataset_default_mode=dataset_default_mode,
            dataset_prefix="host_",
            directory=controller.directory,
            recent_files=recent_files,
        )
    except GuidedTaskUnavailable as exc:
        QMessageBox.critical(parent, "Task Unavailable", str(exc))
        return None
    if parameters is None:
        return None

    request = CalculationRequest(
        atoms=host.atoms,
        potential=host,
        input_parameters=parameters,
        directory=controller.directory or "",
        structure_id=controller.structure_id,
        state_id=controller.state_id,
        restart_scf=restart_host_scf,
    )

    def adopt_host_result(loaded, _request):
        # The host SCF is a separate periodic calculation, not a cluster
        # result. Keep its own result lineage in the project history.
        adoption = controller.adopt_external_result(loaded)
        try:
            # Result atoms need not carry a Potential attached to themselves.
            # Read the native result instead; a missing/invalid host must never
            # silently replace the cluster's last usable host.
            new_host = loaded.result.potential
            if not isinstance(new_host, Potential):
                raise TypeError("SCF result does not contain a periodic Potential.")
        except Exception as exc:  # noqa: BLE001 - missing or corrupt POTFIL
            QMessageBox.warning(
                parent, "Host Potential Not Loaded",
                "The host calculation has finished, but its resulting potential "
                "could not be loaded. The embedded cluster still uses its "
                f"previous host potential.\n{exc}",
            )
            return adoption
        try:
            adopted = controller.replace_embedding_host_if_current(host, new_host)
        except Exception as exc:  # noqa: BLE001 - reject incomplete/incompatible POTFIL
            QMessageBox.warning(
                parent, "Cannot Update Embedded Host",
                "The new host potential was saved in the result history, but "
                f"could not be attached to the embedded cluster:\n{exc}",
            )
            return adoption
        if not adopted:
            QMessageBox.information(
                parent, "Host SCF Result Saved",
                "The host calculation finished, but the active cluster now uses "
                "a different host (or is no longer open). The result is available "
                "in the calculation history and has not replaced that host.",
            )
        return adoption

    return run_calculation(
        controller, recent_files, parent,
        position_like_window="guided-input",
        track_launch_monitor=track_launch_monitor,
        project_repository=project_repository,
        request_override=request,
        on_result_loaded=adopt_host_result,
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
    project_repository: ProjectRepository | None = None,
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
            directory=controller.directory,
            recent_files=recent_files,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return None
        parameters = dialog.parameters()
        position_like_window = "guided-input"
    else:
        edited = edit_input_parameters(
            parameters, parent=parent, atoms=atoms, directory=controller.directory,
            recent_files=recent_files,
        )
        if edited is None:
            return None
        parameters = edited
        position_like_window = "expert-input"
    request_override = _one_off_task_request(
        controller, parameters,
        expected_structure_generation=structure_generation, parent=parent,
    )
    if request_override is None:
        return None
    return run_calculation(
        controller,
        recent_files,
        parent,
        position_like_window=position_like_window,
        track_launch_monitor=track_launch_monitor,
        project_repository=project_repository,
        request_override=request_override,
    )
