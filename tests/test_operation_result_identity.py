import pytest
from ase import Atoms

from ase2sprkkr_gui.gui.application.operation_results import EmptySpheresResult
from ase2sprkkr_gui.gui.application.result_store import ResultStore


def test_empty_spheres_result_has_stable_task_identity():
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(Atoms("Fe"), potential_path=None)

    record = store.add_result(
        EmptySpheresResult(found=2),
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters={},
        directory=None,
    )

    assert record.task_name == "empty_spheres"


def test_result_without_task_identity_is_rejected():
    class MissingTaskIdentity:
        produces_potential = False
        output_values = {}

    store = ResultStore()

    with pytest.raises(AttributeError):
        store.add_result(
            MissingTaskIdentity(),
            structure_id=None,
            input_state_id=None,
            input_parameters=None,
            directory=None,
        )

    assert len(store) == 0
