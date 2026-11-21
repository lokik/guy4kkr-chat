"""Shared file workflows for transactional input-parameter editors."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ase2sprkkr import InputParameters
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.dialogs.input_file import InputFileEditor
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession

_INPUT_FILE_FILTER = "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)"


def choose_and_load_input_parameters(
    session: InputParametersSession,
    parent: QWidget | None,
    *,
    compatible_tasks: Iterable[str] | None = None,
) -> bool:
    """Choose an input file and install it as one session transaction."""
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Load SPRKKR Input File",
        "",
        _INPUT_FILE_FILTER,
    )
    return bool(
        file_path
        and load_input_parameters(
            session,
            file_path,
            parent,
            compatible_tasks=compatible_tasks,
        )
    )


def _load_error(parent: QWidget | None, exception: Exception | str) -> bool:
    QMessageBox.critical(
        parent,
        "Load Error",
        f"Failed to load input parameters:\n{exception}",
    )
    return False


def load_input_parameters(
    session: InputParametersSession,
    file_path: str | Path,
    parent: QWidget | None,
    *,
    compatible_tasks: Iterable[str] | None = None,
) -> bool:
    """Parse input within a session schema; Guided may restrict its task family."""
    path = Path(file_path).resolve()
    try:
        parameters = InputParameters.from_file(path)
    except Exception as exc:  # noqa: BLE001 - parser errors are heterogeneous.
        return _load_error(parent, exc)

    expected_task = session.task_name.lower()
    allowed = (
        {expected_task, *(str(task).lower() for task in compatible_tasks)}
        if compatible_tasks is not None else None
    )
    actual_task_name = parameters.task_name
    if actual_task_name is None:
        return _load_error(
            parent,
            "The input file does not resolve to a known SPR-KKR task.",
        )
    actual_task = actual_task_name.lower()
    if allowed is not None and actual_task not in allowed:
        expected = "/".join(sorted(task.upper() for task in allowed))
        return _load_error(
            parent,
            f"Expected {expected} input parameters, got {actual_task.upper()}.",
        )

    try:
        session.replace_parameters(
            parameters,
            text=f"Load {path.name}",
            source_page="load",
        )
    except ValueError as exc:
        return _load_error(parent, exc)
    return True


def choose_and_save_input_parameters(
    parameters: InputParameters,
    parent: QWidget | None,
    *,
    atoms=None,
    directory: str | Path | None = None,
    recent_files: RecentFiles | None = None,
) -> bool:
    """Save a detached input snapshot, independently of the workspace and run."""
    file_path, _ = QFileDialog.getSaveFileName(
        parent,
        "Save SPRKKR Input File",
        "",
        _INPUT_FILE_FILTER,
    )
    if not file_path:
        return False
    try:
        save_input_parameters_to_path(
            parameters, file_path, atoms=atoms, directory=directory,
        )
    except Exception as exc:  # noqa: BLE001 - native serializers have diverse failures
        QMessageBox.critical(parent, "Save Input Failed", str(exc))
        return False
    if recent_files is not None:
        recent_files.remember("input", file_path)
    return True


def save_input_parameters_to_path(
    parameters: InputParameters,
    file_path: str | Path,
    *,
    atoms=None,
    directory: str | Path | None = None,
) -> None:
    """Write a detached input snapshot for the intended calculation directory."""
    path = Path(file_path).expanduser()
    parameters.directory = directory or parameters.directory or path.absolute().parent
    parameters.save_to_file(
        path, atoms=atoms if atoms is not None else False, validate="set",
    )


def edit_input_parameters_file(
    session: InputParametersSession,
    parent: QWidget | None,
) -> None:
    """Edit generated input text and apply a valid result transactionally."""
    editor = InputFileEditor(
        session.result(),
        parent,
        apply_parameters=lambda parameters: session.replace_parameters(
            parameters,
            text="Edit input file",
            source_page="input_file",
        ),
    )
    editor.exec()
