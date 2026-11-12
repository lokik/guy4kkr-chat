"""Behavioral regressions for revisioned workspace values."""
from __future__ import annotations

from threading import Event, Thread
from types import SimpleNamespace

from ase import Atoms
import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from guy4ase.ase.element_assignment import ElementAssignmentDraft
from guy4ase.gui.application import result_loading as result_loading_module
from guy4ase.gui.application import sprkkr_execution as execution_module
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import load_result, load_result_file
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    WorkspaceController,
)
from guy4ase.gui.flows import files as file_flows


class _Parameters:
    def __init__(self, value: int):
        self.value = value
        self.copy_calls: list[bool] = []

    def copy(self, *, copy_values: bool):
        self.copy_calls.append(copy_values)
        return _Parameters(self.value)


class _Cancellation:
    requested = False

    def register(self, _runner):
        return True


def test_confirmed_structure_edit_is_copy_on_write():
    atoms = Atoms("Fe")
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, potential_path="Fe.pot")
    )
    structures = []
    results = []
    controller.structureChanged.connect(structures.append)
    controller.resultChanged.connect(results.append)
    generation = controller.structure_generation

    def edit(candidate):
        assert candidate is not atoms
        candidate.symbols = "Cu"
        return candidate

    returned = controller.apply_structure_edit(
        edit,
        expected_structure_generation=generation,
    )

    assert returned is DocumentChange.APPLIED
    assert controller.atoms is not atoms
    assert atoms.get_chemical_symbols() == ["Fe"]
    assert controller.atoms.get_chemical_symbols() == ["Cu"]
    assert controller.result is None
    assert controller.potential_path is None
    assert controller.structure_generation == generation.next()
    assert structures == [controller.atoms]
    assert results == []


def test_failed_structure_edit_leaves_published_atoms_untouched():
    atoms = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    generation = controller.structure_generation

    def fail(candidate):
        candidate.symbols = "Cu"
        raise RuntimeError("edit failed")

    with pytest.raises(RuntimeError, match="edit failed"):
        controller.apply_structure_edit(
            fail,
            expected_structure_generation=generation,
        )

    assert controller.atoms is atoms
    assert atoms.get_chemical_symbols() == ["Fe"]
    assert controller.structure_generation == generation


def test_run_request_borrows_atoms_and_owns_parameter_values(tmp_path):
    class UncopyableAtoms(Atoms):
        def copy(self):  # pragma: no cover - request creation must not copy Atoms
            raise AssertionError("calculation request must not copy Atoms")

    atoms = UncopyableAtoms("Fe")
    parameters = _Parameters(7)
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=parameters,
            directory=str(tmp_path),
        )
    )

    request = controller.create_calculation_request()
    parameters.value = 11

    assert request.atoms is atoms
    assert request.input_parameters is not parameters
    assert request.input_parameters.value == 7
    assert parameters.copy_calls == [True]
    assert request.structure_id == controller.structure_id
    assert request.state_id == controller.state_id


def test_backend_preparation_does_not_block_new_workspace_version(
    monkeypatch, tmp_path
):
    preparation_entered = Event()
    release_preparation = Event()
    process_entered = Event()
    release_process = Event()
    atoms = Atoms("Fe")
    parameters = _Parameters(1)
    controller = WorkspaceController(
        WorkspaceState(
            atoms=atoms,
            input_parameters=parameters,
            directory=str(tmp_path),
        )
    )
    request = controller.create_calculation_request()
    execution = SprkkrExecution(request, _Cancellation())

    class Runner:
        reference = None
        id = "concurrency-test"

        def submit(self):
            pass

        def wait(self):
            process_entered.set()
            assert release_process.wait(5)
            return object()

    class Calculator:
        def create_run(self, **kwargs):
            assert kwargs["atoms"] is execution.request.atoms
            assert kwargs["atoms"] is not atoms
            assert kwargs["input_parameters"] is request.input_parameters
            preparation_entered.set()
            assert release_preparation.wait(5)
            return Runner()

    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())
    monkeypatch.setattr(execution_module, "load_result", lambda *_args, **_kwargs: object())

    thread = Thread(target=execution.run)
    thread.start()
    assert preparation_entered.wait(5)

    replacement = Atoms("Ni")
    generation = controller.structure_generation
    assert controller.replace_structure(replacement) is DocumentChange.APPLIED
    assert controller.atoms is replacement
    assert controller.structure_generation == generation.next()

    release_preparation.set()
    assert process_entered.wait(5)
    release_process.set()
    thread.join(5)
    assert not thread.is_alive()


def test_backend_preparation_error_propagates(monkeypatch, tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(1),
            directory=str(tmp_path),
        )
    )
    execution = SprkkrExecution(controller.create_calculation_request(), _Cancellation())

    class Calculator:
        def create_run(self, **_kwargs):
            raise RuntimeError("preparation failed")

    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())

    with pytest.raises(RuntimeError, match="preparation failed"):
        execution.run()


def test_old_result_is_recorded_but_does_not_replace_new_structure(tmp_path):
    original = Atoms("Fe", cell=(1, 1, 1), pbc=True)
    controller = WorkspaceController(
        WorkspaceState(
            atoms=original,
            input_parameters=_Parameters(1),
            directory=str(tmp_path),
        )
    )
    source_generation = controller.structure_generation
    draft = ElementAssignmentDraft(controller.atoms)
    request = controller.create_calculation_request()
    replacement = Atoms("Cu")
    controller.replace_structure(replacement)

    result = SimpleNamespace(
        files={},
        directory=str(tmp_path),
        task_name="DOS",
        produces_potential=False,
    )
    loaded = load_result(result, fallback_directory=tmp_path)
    adoption = controller.adopt_calculation_result(loaded, request=request)
    assert not adoption.workspace_updated
    assert controller.atoms is replacement
    assert controller.result_store.results[0].result is result
    assert controller.result_store.results[0].structure_id == request.structure_id

    change = controller.apply_structure_edit(
        lambda atoms: draft.apply(atoms),
        expected_structure_generation=source_generation,
    )
    assert change is DocumentChange.STALE
    assert controller.atoms is replacement


def test_reset_advances_each_changed_revision_independently():
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(1),
            directory="run",
            active_project_id="project",
        )
    )
    structure = controller.structure_generation
    inputs = controller.input_parameters_generation
    directory = controller.directory_generation
    project = controller.active_project_generation

    controller.reset()

    assert controller.structure_generation == structure.next()
    assert controller.input_parameters_generation == inputs.next()
    assert controller.directory_generation == directory.next()
    assert controller.active_project_generation == project
    assert controller.active_project_id == "project"


def test_structure_file_load_ignores_intervening_input_parameter_change(
    monkeypatch, tmp_path
):
    loaded_atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Cu")))
    history = RecentFiles(tmp_path / "structure-recent.json")

    def read_structure(_path):
        controller.replace_input_parameters(object())
        return loaded_atoms

    monkeypatch.setattr(file_flows, "ase_read", read_structure)
    monkeypatch.setattr(
        file_flows,
        "document_change_applied",
        lambda _parent, change: change is DocumentChange.APPLIED,
    )

    assert file_flows.load_structure(
        controller,
        history,
        tmp_path / "Fe.cif",
        object(),
    )
    assert controller.atoms is loaded_atoms
    assert history.paths("structure") == (str((tmp_path / "Fe.cif").resolve()),)


def test_structure_file_load_rejects_intervening_structure_change(monkeypatch, tmp_path):
    loaded_atoms = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Cu")))
    newer = Atoms("Ni")
    history = RecentFiles(tmp_path / "structure-recent.json")

    def read_structure(_path):
        controller.replace_structure(newer)
        return loaded_atoms

    monkeypatch.setattr(file_flows, "ase_read", read_structure)
    monkeypatch.setattr(
        file_flows,
        "document_change_applied",
        lambda _parent, change: change is DocumentChange.APPLIED,
    )

    assert not file_flows.load_structure(
        controller,
        history,
        tmp_path / "Fe.cif",
        object(),
    )
    assert controller.atoms is newer
    assert history.paths("structure") == ()


def test_external_result_load_survives_intervening_workspace_change(monkeypatch, tmp_path):
    result = SimpleNamespace(
        files={},
        directory=str(tmp_path),
        task_name="DOS",
        produces_potential=False,
    )
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Cu")))
    original_structure = controller.atoms
    loaded_result = load_result_file(tmp_path / "Fe.out")

    controller.replace_input_parameters(object())
    adoption = controller.adopt_external_result(loaded_result)

    assert not adoption.workspace_updated
    assert controller.atoms is original_structure
    assert controller.result_store.results[0].result is result


def test_directory_change_does_not_discard_completed_calculation_result(tmp_path):
    original_directory = tmp_path / "first"
    next_directory = tmp_path / "next"
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(1),
            directory=str(original_directory),
        )
    )
    request = controller.create_calculation_request()
    result = SimpleNamespace(
        files={},
        directory=str(original_directory),
        task_name="DOS",
        produces_potential=False,
    )
    loaded = load_result(result, fallback_directory=original_directory)

    controller.change_directory(str(next_directory))
    adoption = controller.adopt_calculation_result(loaded, request=request)

    assert not adoption.workspace_updated
    assert controller.result_store.results[0].result is result
    assert controller.directory == str(next_directory)


def test_structure_file_is_parsed_before_structure_revision_checked(monkeypatch, tmp_path):
    _application = QApplication.instance() or QApplication([])
    parent = QWidget()
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    reads = []
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Cu")))
    history = RecentFiles(tmp_path / "recent.json")

    def read(path):
        reads.append(path)
        controller.replace_structure(Atoms("Ni"))
        return atoms

    monkeypatch.setattr(file_flows, "ase_read", read)
    monkeypatch.setattr(
        file_flows,
        "document_change_applied",
        lambda _parent, change: change is DocumentChange.APPLIED,
    )

    assert not file_flows.load_structure(
        controller, history, tmp_path / "Fe.cif", parent
    )
    assert reads == [(tmp_path / "Fe.cif").resolve()]
    assert history.paths("structure") == ()
    parent.close()
