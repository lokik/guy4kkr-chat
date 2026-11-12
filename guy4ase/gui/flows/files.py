"""Qt file orchestration around the workspace document controller."""
from __future__ import annotations

import re
from pathlib import Path

from ase.io import read as ase_read
from ase.io import write as ase_write
from ase.io.formats import ioformats
from ase2sprkkr import InputParameters
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from guy4ase.gui.application.recent_files import RecentFiles, RecentKind
from guy4ase.gui.application.result_loading import (
    LoadedResult,
    PotentialVersionChanged,
    load_potential_atoms,
    load_result_file,
)
from guy4ase.gui.application.workspace_controller import ResultAdoption, WorkspaceController
from guy4ase.gui.flows.structure_candidates import (
    load_structure_candidate,
    structure_open_filter,
)
from guy4ase.gui.flows.structures import warn_if_structure_kind_is_unknown
from guy4ase.gui.misc.modal_task import run_modal_task
from guy4ase.gui.misc.structure_wait import document_change_applied


_POTENTIAL_SUFFIXES = {".pot", ".pot_new"}


def _read_structure_file(path: Path):
    """Read a structure, keeping a POT file's potential authoritative in atoms."""
    if path.suffix.lower() in _POTENTIAL_SUFFIXES and path.exists():
        return load_potential_atoms(path)
    return ase_read(path)


def _show_potential_warning(adoption: ResultAdoption, parent: QWidget) -> None:
    if adoption.potential_error is None:
        return
    QMessageBox.warning(
        parent,
        "Potential Load Warning",
        "The result was loaded, but its potential could not be loaded:\n"
        f"{adoption.potential_error}",
    )


def _show_input_parameters_warning(adoption: ResultAdoption, parent: QWidget) -> None:
    if adoption.input_parameters_error is None:
        return
    QMessageBox.warning(
        parent,
        "Input Parameters Load Warning",
        "The result was loaded, but its input parameters could not be loaded:\n"
        f"{adoption.input_parameters_error}",
    )


def choose_and_load_structure(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Load Structure File",
        "",
        structure_open_filter(),
    )
    return bool(file_path and load_structure(controller, recent_files, file_path, parent))


def load_structure(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    structure_generation = controller.structure_generation
    directory_generation = controller.directory_generation
    path = Path(file_path).resolve()
    candidate = load_structure_candidate(path, parent, reader=_read_structure_file)
    if candidate is None:
        return False
    atoms = candidate.atoms

    potential_path = str(path) if path.suffix.lower() in _POTENTIAL_SUFFIXES else None
    change = controller.replace_structure(
        atoms,
        potential_path=potential_path,
        directory=str(path.parent),
        expected_structure_generation=structure_generation,
        expected_directory_generation=directory_generation,
    )
    if not document_change_applied(parent, change):
        return False
    warn_if_structure_kind_is_unknown(atoms, parent)
    recent_files.remember("structure", file_path)
    return True


def choose_and_load_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Load Input File",
        "",
        "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)",
    )
    return bool(
        file_path
        and load_input_parameters(controller, recent_files, file_path, parent)
    )


def load_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    input_generation = controller.input_parameters_generation
    directory_generation = controller.directory_generation
    path = Path(file_path).resolve()
    try:
        parameters = run_modal_task(
            parent,
            lambda: InputParameters.from_file(path),
            title="Loading Input",
            label="Reading input parameters…",
        )
    except Exception as exc:  # noqa: BLE001 - parser errors are presented
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load input parameters:\n{exc}",
        )
        return False

    change = controller.replace_input_parameters(
        parameters,
        directory=str(path.parent),
        expected_input_parameters_generation=input_generation,
        expected_directory_generation=directory_generation,
    )
    if not document_change_applied(parent, change):
        return False
    recent_files.remember("input", file_path)
    return True


def choose_and_load_output(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "Load SPRKKR Output File",
        "",
        "SPRKKR Output Files (*.out *.log *.txt);;All Files (*)",
    )
    return bool(file_path and load_output(controller, recent_files, file_path, parent))


def _read_output(file_path: str | Path, parent: QWidget) -> LoadedResult | None:
    try:
        return run_modal_task(
            parent,
            lambda: load_result_file(file_path),
            title="Loading Result",
            label="Parsing SPR-KKR output…",
        )
    except Exception as exc:  # noqa: BLE001 - backend readers vary
        QMessageBox.critical(
            parent,
            "Load Error",
            f"Failed to load SPR-KKR output:\n{exc}",
        )
        return None


def _finish_output_load(
    adoption: ResultAdoption,
    recent_files: RecentFiles,
    file_path: str | Path,
    parent: QWidget,
) -> None:
    recent_files.remember("output", file_path)
    _show_potential_warning(adoption, parent)
    _show_input_parameters_warning(adoption, parent)


def load_output(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    """Import an output into result history without changing the workspace."""
    loaded = _read_output(file_path, parent)
    if loaded is None:
        return False
    adoption = controller.adopt_external_result(loaded, select_result=True)
    _finish_output_load(adoption, recent_files, file_path, parent)
    return True


def continue_output(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    """Import or reuse an output and make its reusable calculation state active."""
    structure_generation = controller.structure_generation
    directory_generation = controller.directory_generation
    loaded = _read_output(file_path, parent)
    if loaded is None:
        return False

    adoption = controller.adopt_external_result(loaded, select_result=True)
    record = adoption.record
    if record is None:
        return False

    state = controller.result_store.state_for_result(record)
    if state is None:
        QMessageBox.warning(
            parent,
            "Cannot Continue Calculation",
            "The selected result has no reusable calculation state.",
        )
        _finish_output_load(adoption, recent_files, file_path, parent)
        return False

    if controller.state_id != state.id:
        try:
            change = controller.use_result_state(
                record.id,
                expected_structure_generation=structure_generation,
            )
        except (ValueError, PotentialVersionChanged) as exc:
            QMessageBox.warning(
                parent,
                "Cannot Continue Calculation",
                f"The selected result cannot be restored:\n{exc}",
            )
            _finish_output_load(adoption, recent_files, file_path, parent)
            return False
        if not document_change_applied(parent, change):
            _finish_output_load(adoption, recent_files, file_path, parent)
            return False

    if loaded.directory is not None and not document_change_applied(
        parent,
        controller.change_directory(
            loaded.directory,
            expected_directory_generation=directory_generation,
        ),
    ):
        _finish_output_load(adoption, recent_files, file_path, parent)
        return False
    _finish_output_load(adoption, recent_files, file_path, parent)
    return True


def save_structure(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    atoms = controller.atoms
    if atoms is None:
        return False
    formats = {
        " ".join(f"*.{ext}" for ext in file_format.extensions): file_format.name
        for file_format in ioformats.values()
        if file_format.extensions
    }
    formats["*"] = "All Files"
    file_path, selected_filter = QFileDialog.getSaveFileName(
        parent,
        "Save Structure File",
        "",
        ";;".join(f"{name} ({patterns})" for patterns, name in formats.items()),
    )
    if not file_path:
        return False
    match = re.search(r"\*\.(\w+)", selected_filter)
    if match and not file_path.lower().endswith(f".{match.group(1)}"):
        file_path += f".{match.group(1)}"

    path = Path(file_path).resolve()
    try:
        ase_write(path, atoms)
    except Exception as exc:  # noqa: BLE001 - backend writers vary
        QMessageBox.critical(
            parent, "Save Error", f"Failed to save structure:\n{exc}"
        )
        return False
    recent_files.remember("structure", file_path)
    return True


def save_input_parameters(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    parent: QWidget,
) -> bool:
    parameters = controller.input_parameters
    if parameters is None:
        return False
    file_path, _ = QFileDialog.getSaveFileName(
        parent,
        "Save Input File",
        "",
        "SPRKKR Input Files (*.inp *.in *.txt);;All Files (*)",
    )
    if not file_path:
        return False
    try:
        parameters.to_file(Path(file_path).resolve())
    except Exception as exc:  # noqa: BLE001 - backend writers vary
        QMessageBox.critical(
            parent,
            "Save Error",
            f"Failed to save input parameters:\n{exc}",
        )
        return False
    recent_files.remember("input", file_path)
    return True


def open_recent(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    kind: RecentKind,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    if not Path(file_path).exists():
        QMessageBox.warning(parent, "Missing File", f"File not found:\n{file_path}")
        recent_files.forget(kind, file_path)
        return False
    loaders = {
        "structure": load_structure,
        "input": load_input_parameters,
        "output": load_output,
    }
    return loaders[kind](controller, recent_files, file_path, parent)


def continue_recent(
    controller: WorkspaceController,
    recent_files: RecentFiles,
    kind: RecentKind,
    file_path: str | Path,
    parent: QWidget,
) -> bool:
    """Continue from a recent item instead of merely reopening an output."""
    if not Path(file_path).exists():
        QMessageBox.warning(parent, "Missing File", f"File not found:\n{file_path}")
        recent_files.forget(kind, file_path)
        return False
    if kind == "output":
        return continue_output(controller, recent_files, file_path, parent)
    return open_recent(controller, recent_files, kind, file_path, parent)
