from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application import result_store as result_store_module
from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    WorkspaceController,
)


class _Parameters:
    def __init__(self, task_name="dos", value=1):
        self.task_name = task_name
        self.value = value

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(self.task_name, self.value)


class _FailingParameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        raise ValueError("parameter snapshot failed")


def _result(task_name: str, *, produces_potential: bool = False):
    return SimpleNamespace(
        task_name=task_name,
        produces_potential=produces_potential,
    )


def test_calculation_request_requires_structure_and_state_ids():
    common = dict(
        atoms=Atoms("Fe"),
        input_parameters=object(),
        directory=".",
    )

    with pytest.raises(TypeError, match="structure_id"):
        CalculationRequest(**common, state_id=1)
    with pytest.raises(TypeError, match="state_id"):
        CalculationRequest(**common, structure_id=1)


@pytest.mark.parametrize(
    ("structure_id", "input_state_id"),
    ((1, None), (None, 1)),
)
def test_add_result_rejects_partial_provenance(structure_id, input_state_id):
    store = ResultStore()

    with pytest.raises(ValueError, match="requires structure_id and input_state_id together"):
        store.add_result(
            _result("dos"),
            structure_id=structure_id,
            input_state_id=input_state_id,
            input_parameters=None,
            directory=None,
        )

    assert len(store) == 0


def test_add_result_does_not_expose_external_import_mode():
    store = ResultStore()

    with pytest.raises(TypeError, match="imported"):
        store.add_result(
            _result("dos"),
            structure_id=None,
            input_state_id=None,
            input_parameters=None,
            directory=None,
            imported=True,
        )

    assert len(store) == 0


def test_add_result_rejects_cross_structure_input_state_atomically():
    store = ResultStore()
    first_structure, _first_state = store.new_structure_state(
        Atoms("Fe"), potential_path=None
    )
    second_structure, second_state = store.new_structure_state(
        Atoms("Cu"), potential_path=None
    )
    result = _result("dos")

    with pytest.raises(AssertionError, match="Result provenance mismatch"):
        store.add_result(
            result,
            structure_id=first_structure,
            input_state_id=second_state,
            input_parameters=None,
            directory=None,
        )

    assert len(store) == 0
    assert store.results_for_state(second_state) == ()

    record = store.add_result(
        result,
        structure_id=second_structure,
        input_state_id=second_state,
        input_parameters=None,
        directory=None,
    )
    assert record.id == 1


def test_add_result_snapshot_failure_does_not_commit_state_or_result():
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        Atoms("Fe"), potential_path=None
    )
    result = _result("scf", produces_potential=True)

    with pytest.raises(ValueError, match="parameter snapshot failed"):
        store.add_result(
            result,
            structure_id=structure_id,
            input_state_id=state_id,
            input_parameters=_FailingParameters(),
            directory=None,
            output_atoms=Atoms("Fe"),
        )

    assert len(store) == 0
    assert store.results_for_state(state_id) == ()

    record = store.add_result(
        result,
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=None,
        directory=None,
        output_atoms=Atoms("Fe"),
    )

    assert record.id == 1
    assert record.output_state_id == state_id + 1
    output_state = store.state(record.output_state_id)
    assert output_state.produced_by_result_id == record.id
    assert store.result(record.id) is record


def test_add_external_result_snapshot_failure_does_not_commit_structure():
    store = ResultStore()

    with pytest.raises(ValueError, match="parameter snapshot failed"):
        store.add_external_result(
            _result("dos"),
            atoms=Atoms("Fe"),
            input_parameters=_FailingParameters(),
            directory=None,
            output_path=None,
            potential_path=None,
        )

    assert store.structures == ()
    assert len(store) == 0

    record = store.add_external_result(
        _result("dos"),
        atoms=Atoms("Fe"),
        input_parameters=None,
        directory=None,
        output_path=None,
        potential_path=None,
    )
    assert record.id == 1
    assert record.structure_id == 1
    assert record.input_state_id == 1
    assert record.imported
    assert store.imported_results(None) == (record,)


def test_new_structure_state_snapshot_failure_does_not_mutate_store(monkeypatch):
    store = ResultStore()

    def fail_capture(_atoms):
        raise ValueError("structure snapshot failed")

    with monkeypatch.context() as patch:
        patch.setattr(
            result_store_module.StructureSnapshot,
            "capture",
            staticmethod(fail_capture),
        )
        with pytest.raises(ValueError, match="structure snapshot failed"):
            store.new_structure_state(Atoms("Fe"), potential_path=None)

    assert store.structures == ()
    structure_id, state_id = store.new_structure_state(Atoms("Fe"), potential_path=None)
    assert (structure_id, state_id) == (1, 1)
    assert store.state(state_id).branch_id == 1


def test_replace_structure_store_failure_keeps_workspace_unchanged(monkeypatch):
    controller = WorkspaceController()
    original = Atoms("Fe")
    controller.replace_structure(original, directory="old", restarted=True)
    original_structure_id = controller.structure_id
    original_state_id = controller.state_id
    original_structure_generation = controller.structure_generation
    original_directory_generation = controller.directory_generation

    def fail_new_structure_state(*_args, **_kwargs):
        raise ValueError("state preparation failed")

    monkeypatch.setattr(
        controller.result_store,
        "new_structure_state",
        fail_new_structure_state,
    )

    with pytest.raises(ValueError, match="state preparation failed"):
        controller.replace_structure(
            Atoms("Cu"),
            directory="new",
            restarted=False,
        )

    assert controller.atoms is original
    assert controller.directory == "old"
    assert controller.structure_id == original_structure_id
    assert controller.state_id == original_state_id
    assert controller.restarted is True
    assert controller.structure_generation == original_structure_generation
    assert controller.directory_generation == original_directory_generation


def test_apply_structure_edit_store_failure_keeps_workspace_unchanged(monkeypatch):
    controller = WorkspaceController()
    original = Atoms("Fe")
    controller.replace_structure(original)
    original_structure_id = controller.structure_id
    original_state_id = controller.state_id
    original_generation = controller.structure_generation

    def fail_new_structure_state(*_args, **_kwargs):
        raise ValueError("state preparation failed")

    monkeypatch.setattr(
        controller.result_store,
        "new_structure_state",
        fail_new_structure_state,
    )

    with pytest.raises(ValueError, match="state preparation failed"):
        controller.apply_structure_edit(
            lambda atoms: atoms,
            expected_structure_generation=original_generation,
        )

    assert controller.atoms is original
    assert controller.structure_id == original_structure_id
    assert controller.state_id == original_state_id
    assert controller.restarted is False
    assert controller.structure_generation == original_generation


def test_result_record_snapshots_task_name_and_input_parameters():
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        Atoms("Fe"), potential_path=None
    )
    parameters = _Parameters(task_name="dos", value=7)
    result = _result(parameters.task_name)

    record = store.add_result(
        result,
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=parameters,
        directory=None,
    )

    assert record.task_name == "dos"
    assert record.input_parameters is not parameters
    assert record.input_parameters.task_name == "dos"
    assert record.input_parameters.value == 7

    parameters.task_name = "jxc"
    parameters.value = 99
    result.task_name = "arpes"

    assert record.task_name == "dos"
    assert record.input_parameters.task_name == "dos"
    assert record.input_parameters.value == 7


def test_result_record_deep_copies_generic_mapping_parameters():
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        Atoms("Fe"), potential_path=None
    )
    parameters = {"mesh": [10, 20, 30]}

    record = store.add_result(
        _result("empty-spheres"),
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=parameters,
        directory=None,
    )

    parameters["mesh"][0] = 999

    assert record.input_parameters == {"mesh": [10, 20, 30]}
