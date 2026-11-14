from __future__ import annotations

import inspect
from types import SimpleNamespace

import numpy as np
from ase import Atoms

from ase2sprkkr_gui.gui.application.result_store import ResultStore
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController


def _atoms() -> Atoms:
    atoms = Atoms("FeNi", positions=((0, 0, 0), (1, 1, 1)), cell=(3, 3, 3), pbc=True)
    atoms.set_array("spacegroup_kinds", np.asarray((0, 1), dtype=int))
    atoms.set_array("labels", np.asarray(("a", "b"), dtype=object))
    atoms.info["occupancy"] = {
        "0": {"Fe": 0.75, "Co": 0.25},
        "1": {"Ni": 1.0},
    }
    return atoms


def test_state_without_usable_potential_keeps_only_lightweight_structure_snapshot():
    atoms = _atoms()
    atoms.potential = object()
    store = ResultStore()

    _, state_id = store.new_structure_state(atoms, potential_path=None)
    state = store.state(state_id)

    assert not hasattr(state, "atoms")
    assert state.structure_snapshot is not None

    atoms.positions[:] = 9
    atoms.info["occupancy"]["0"]["Fe"] = 0.0
    restored = state.structure_snapshot.to_atoms()

    assert np.allclose(restored.positions, ((0, 0, 0), (1, 1, 1)))
    assert restored.arrays["spacegroup_kinds"].tolist() == [0, 1]
    assert restored.arrays["labels"].tolist() == ["a", "b"]
    assert restored.info["occupancy"]["0"] == {"Fe": 0.75, "Co": 0.25}
    assert not hasattr(restored, "potential")


def test_state_with_usable_potential_does_not_retain_structure_snapshot(tmp_path):
    potential = tmp_path / "Fe.pot"
    potential.write_text("potential", encoding="utf-8")
    store = ResultStore()

    _, state_id = store.new_structure_state(
        _atoms(),
        potential_path=str(potential),
    )
    state = store.state(state_id)

    assert state.potential_version is not None
    assert state.potential_version.available
    assert state.structure_snapshot is None
    assert not hasattr(state, "atoms")


def test_result_store_api_has_no_ignored_atoms_arguments():
    assert "atoms" not in inspect.signature(ResultStore.add_result).parameters
    assert "atoms" not in inspect.signature(ResultStore.new_child_state).parameters


def test_historical_snapshot_can_restore_structure_without_retaining_live_atoms():
    original = _atoms()
    controller = WorkspaceController(WorkspaceState(atoms=original))
    structure_id = controller.structure_id
    state_id = controller.state_id
    assert structure_id is not None
    assert state_id is not None

    record = controller.result_store.add_result(
        SimpleNamespace(
            task_name="dos",
            produces_potential=False,
            output_values={},
        ),
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters={},
        directory=None,
    )
    controller.replace_structure(Atoms("Cu"))

    controller.use_result_state(record.id)

    assert controller.atoms is not original
    assert controller.atoms.get_chemical_symbols() == ["Fe", "Ni"]
    assert controller.atoms.info["occupancy"]["0"] == {"Fe": 0.75, "Co": 0.25}
