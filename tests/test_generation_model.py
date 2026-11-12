from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import Generation, WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    DocumentChange,
    WorkspaceController,
)


class _Parameters:
    def __init__(self, value=None):
        self.value = value

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(self.value)


def _result(task_name):
    return SimpleNamespace(task_name=task_name, produces_potential=False)


def _controller(tmp_path, *, conflict_resolver=None):
    return WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        ),
        conflict_resolver=conflict_resolver,
    )


def _loaded(result, *, atoms=None, potential_path=None, directory=None):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=potential_path,
        atoms=atoms,
        potential_error=None,
        directory=directory,
    )


def test_generation_is_a_regular_value_type_without_integer_compatibility():
    generation = Generation(1)

    assert generation == Generation(1)
    assert hash(generation) == hash(Generation(1))
    assert {generation: "value"}[Generation(1)] == "value"
    assert generation != 1
    assert generation != (1,)


def test_workspace_generations_are_independent(tmp_path):
    controller = _controller(tmp_path)
    initial = controller.generation

    controller.change_directory(str(tmp_path / "other"))
    after_directory = controller.generation
    assert after_directory.directory == initial.directory.next()
    assert after_directory.structure == initial.structure
    assert after_directory.input_parameters == initial.input_parameters
    assert after_directory.active_project == initial.active_project

    controller.set_active_project("project")
    after_project = controller.generation
    assert after_project.active_project == initial.active_project.next()
    assert after_project.structure == initial.structure
    assert after_project.input_parameters == initial.input_parameters
    assert after_project.directory == after_directory.directory

    controller.replace_input_parameters(_Parameters(1))
    after_input = controller.generation
    assert after_input.input_parameters == initial.input_parameters.next()
    assert after_input.structure == initial.structure
    assert after_input.directory == after_directory.directory
    assert after_input.active_project == after_project.active_project

    controller.replace_structure(Atoms("Cu"))
    after_structure = controller.generation
    assert after_structure.structure == initial.structure.next()
    assert after_structure.input_parameters == after_input.input_parameters
    assert after_structure.directory == after_directory.directory
    assert after_structure.active_project == after_project.active_project


def test_unrelated_context_change_does_not_stale_structure_edit(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation

    controller.change_directory(str(tmp_path / "other"))
    controller.set_active_project("project")
    change = controller.apply_structure_edit(
        lambda atoms: atoms,
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED


def test_input_edit_depends_on_structure_but_not_context(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation

    controller.change_directory(str(tmp_path / "other"))
    controller.set_active_project("project")
    assert (
        controller.replace_input_parameters(
            _Parameters(1),
            expected_generation=generation,
        )
        is DocumentChange.APPLIED
    )

    generation = controller.generation
    controller.replace_structure(Atoms("Cu"))
    assert (
        controller.replace_input_parameters(
            _Parameters(2),
            expected_generation=generation,
        )
        is DocumentChange.STALE
    )


def test_conflict_resolver_can_reject_without_mutating_value(tmp_path):
    conflicts = []

    def reject(items):
        conflicts.append(items)
        return False

    controller = _controller(tmp_path, conflict_resolver=reject)
    generation = controller.generation
    newer = _Parameters("newer")
    controller.replace_input_parameters(newer)

    change = controller.replace_input_parameters(
        _Parameters("stale"),
        expected_generation=generation,
    )

    assert change is DocumentChange.CANCELLED
    assert controller.input_parameters is newer
    assert len(conflicts) == 1
    assert [item.component for item in conflicts[0]] == ["input parameters"]


def test_conflict_resolver_can_force_one_atomic_commit(tmp_path):
    conflicts = []

    def accept(items):
        conflicts.append(items)
        return True

    controller = _controller(tmp_path, conflict_resolver=accept)
    generation = controller.generation
    controller.replace_input_parameters(_Parameters("newer"))
    before = controller.input_parameters_generation
    replacement = _Parameters("chosen")

    change = controller.replace_input_parameters(
        replacement,
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert controller.input_parameters is replacement
    assert controller.input_parameters_generation == before.next()
    assert len(conflicts) == 1


def test_multi_value_conflict_is_resolved_once(tmp_path):
    conflicts = []

    def accept(items):
        conflicts.append(items)
        return True

    controller = _controller(tmp_path, conflict_resolver=accept)
    generation = controller.generation
    controller.replace_structure(Atoms("Cu"))
    controller.change_directory(str(tmp_path / "newer"))

    change = controller.replace_structure(
        Atoms("Ni"),
        directory=str(tmp_path / "chosen"),
        expected_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert controller.atoms.get_chemical_symbols() == ["Ni"]
    assert controller.directory == str(tmp_path / "chosen")
    assert len(conflicts) == 1
    assert {item.component for item in conflicts[0]} == {
        "structure",
        "working directory",
    }


def test_result_publication_does_not_advance_workspace_generations(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation
    request = controller.create_calculation_request()
    result = _result("DOS")

    adoption = controller.adopt_calculation_result(
        _loaded(result, directory=str(tmp_path)),
        request=request,
    )

    assert not adoption.workspace_updated
    assert controller.generation == generation
    assert controller.result_store.results[0].result is result


def test_parallel_non_scf_results_are_both_recorded_without_touching_workspace(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.generation
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()
    first = _result("DOS")
    second = _result("BSF")

    controller.adopt_calculation_result(_loaded(first), request=request_a)
    controller.adopt_calculation_result(_loaded(second), request=request_b)

    assert controller.generation == generation
    assert tuple(record.result for record in controller.result_store.results[:2]) == (
        second,
        first,
    )


def test_structure_change_does_not_reject_completed_job_from_history(tmp_path):
    controller = _controller(tmp_path)
    request = controller.create_calculation_request()
    old_structure_id = request.structure_id
    controller.replace_structure(Atoms("Cu"))
    result = _result("DOS")

    adoption = controller.adopt_calculation_result(_loaded(result), request=request)

    assert not adoption.workspace_updated
    assert controller.result_store.results[0].result is result
    assert controller.result_store.results[0].structure_id == old_structure_id
    assert controller.atoms.get_chemical_symbols() == ["Cu"]
