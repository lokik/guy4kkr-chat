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


def _result(task_name, *, produces_potential=False):
    return SimpleNamespace(
        task_name=task_name,
        produces_potential=produces_potential,
    )


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


def _generations(controller):
    return (
        controller.structure_generation,
        controller.input_parameters_generation,
        controller.directory_generation,
        controller.active_project_generation,
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
    structure, inputs, directory, project = _generations(controller)

    controller.change_directory(str(tmp_path / "other"))
    assert _generations(controller) == (
        structure,
        inputs,
        directory.next(),
        project,
    )

    controller.set_active_project("project")
    assert _generations(controller) == (
        structure,
        inputs,
        directory.next(),
        project.next(),
    )

    controller.replace_input_parameters(_Parameters(1))
    assert _generations(controller) == (
        structure,
        inputs.next(),
        directory.next(),
        project.next(),
    )

    controller.replace_structure(Atoms("Cu"))
    assert _generations(controller) == (
        structure.next(),
        inputs.next(),
        directory.next(),
        project.next(),
    )


def test_unrelated_context_change_does_not_stale_structure_edit(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.structure_generation

    controller.change_directory(str(tmp_path / "other"))
    controller.set_active_project("project")
    change = controller.apply_structure_edit(
        lambda atoms: atoms,
        expected_structure_generation=generation,
    )

    assert change is DocumentChange.APPLIED


def test_input_edit_depends_on_structure_but_not_context(tmp_path):
    controller = _controller(tmp_path)
    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation

    controller.change_directory(str(tmp_path / "other"))
    controller.set_active_project("project")
    assert (
        controller.replace_input_parameters(
            _Parameters(1),
            expected_input_parameters_generation=input_generation,
            expected_structure_generation=structure_generation,
        )
        is DocumentChange.APPLIED
    )

    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation
    controller.replace_structure(Atoms("Cu"))
    assert (
        controller.replace_input_parameters(
            _Parameters(2),
            expected_input_parameters_generation=input_generation,
            expected_structure_generation=structure_generation,
        )
        is DocumentChange.STALE
    )


def test_conflict_resolver_can_reject_without_mutating_value(tmp_path):
    conflicts = []

    def reject(items):
        conflicts.append(items)
        return False

    controller = _controller(tmp_path, conflict_resolver=reject)
    generation = controller.input_parameters_generation
    newer = _Parameters("newer")
    controller.replace_input_parameters(newer)

    change = controller.replace_input_parameters(
        _Parameters("stale"),
        expected_input_parameters_generation=generation,
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
    generation = controller.input_parameters_generation
    controller.replace_input_parameters(_Parameters("newer"))
    before = controller.input_parameters_generation
    replacement = _Parameters("chosen")

    change = controller.replace_input_parameters(
        replacement,
        expected_input_parameters_generation=generation,
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
    structure_generation = controller.structure_generation
    directory_generation = controller.directory_generation
    controller.replace_structure(Atoms("Cu"))
    controller.change_directory(str(tmp_path / "newer"))

    change = controller.replace_structure(
        Atoms("Ni"),
        directory=str(tmp_path / "chosen"),
        expected_structure_generation=structure_generation,
        expected_directory_generation=directory_generation,
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
    generations = _generations(controller)
    request = controller.create_calculation_request()
    result = _result("DOS")

    adoption = controller.adopt_calculation_result(
        _loaded(result, directory=str(tmp_path)),
        request=request,
    )

    assert not adoption.workspace_updated
    assert _generations(controller) == generations
    assert controller.result_store.results[0].result is result


def test_parallel_non_scf_results_are_both_recorded_without_touching_workspace(tmp_path):
    controller = _controller(tmp_path)
    generations = _generations(controller)
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()
    first = _result("DOS")
    second = _result("BSF")

    controller.adopt_calculation_result(_loaded(first), request=request_a)
    controller.adopt_calculation_result(_loaded(second), request=request_b)

    assert _generations(controller) == generations
    assert tuple(record.result for record in controller.result_store.results[:2]) == (
        second,
        first,
    )


def test_non_potential_result_atoms_do_not_fast_forward_structure(tmp_path):
    controller = _controller(tmp_path)
    request = controller.create_calculation_request()
    generation = controller.structure_generation

    adoption = controller.adopt_calculation_result(
        _loaded(_result("DOS"), atoms=Atoms("Cu")),
        request=request,
    )

    assert not adoption.workspace_updated
    assert controller.structure_generation == generation
    assert controller.atoms.get_chemical_symbols() == ["Fe"]


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
