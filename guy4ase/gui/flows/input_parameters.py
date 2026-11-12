"""Shared file workflows for transactional input-parameter editors."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ase2sprkkr import InputParameters
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.input_parameters.session import InputParametersSession

_INPUT_FILE_FILTER = "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)"


def choose_and_load_input_parameters(
    session: InputParametersSession,
    parent: QWidget | None,
    *,
    compatible_tasks: Iterable[str] = (),
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
    compatible_tasks: Iterable[str] = (),
) -> bool:
    """Parse an input file and install it without leaking editor-family policy."""
    path = Path(file_path).resolve()
    try:
        parameters = InputParameters.from_file(path)
    except Exception as exc:  # noqa: BLE001 - parser errors are heterogeneous.
        return _load_error(parent, exc)

    expected_task = session.task_name.lower()
    allowed = {expected_task, *(str(task).lower() for task in compatible_tasks)}
    actual_task_name = parameters.task_name
    if actual_task_name is None:
        return _load_error(
            parent,
            "The input file does not resolve to a known SPR-KKR task.",
        )
    actual_task = actual_task_name.lower()
    if actual_task not in allowed:
        expected = "/".join(sorted(task.upper() for task in allowed))
        return _load_error(
            parent,
            f"Expected {expected} input parameters, got {actual_task.upper()}.",
        )

    session.replace_parameters(
        parameters,
        text=f"Load {path.name}",
        source_page="load",
    )
    return True


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
