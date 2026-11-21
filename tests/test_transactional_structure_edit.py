from ase import Atoms
from ase2sprkkr import SPRKKRAtoms
import numpy as np
import pytest

from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController


def test_structure_edit_uses_explicit_shallow_copy():
    atoms = SPRKKRAtoms("Fe", cell=(2, 2, 2), symmetry=False)
    original = atoms.sites[0].atomic_type(0)
    original.potential = np.ones((2, len(original.mesh)))
    controller = WorkspaceController(WorkspaceState(atoms=atoms))

    def edit(candidate):
        edited = candidate.sites[0].atomic_type(0)
        assert candidate is not atoms
        assert edited is not original
        assert np.shares_memory(edited.potential.raw_value, original.potential.raw_value)
        candidate.positions[0, 0] = 1
        return candidate

    controller.apply_structure_edit(
        edit, expected_structure_generation=controller.structure_generation,
    )
    assert controller.atoms is not atoms
    assert atoms.positions[0, 0] == 0


def test_unchanged_read_only_dialog_does_not_copy_or_create_state(monkeypatch):
    atoms = SPRKKRAtoms("Fe", cell=(2, 2, 2), symmetry=False)
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    state_id = controller.state_id

    def forbid_copy(*_args, **_kwargs):
        raise AssertionError("An unchanged dialog must not copy the structure")

    monkeypatch.setattr(atoms, "copy", forbid_copy)
    change = controller.apply_structure_edit(
        lambda candidate: candidate,
        expected_structure_generation=controller.structure_generation,
        copy_source=False,
    )
    assert change is None
    assert controller.atoms is atoms
    assert controller.state_id == state_id


def test_failed_structure_edit_does_not_mutate_workspace():
    atoms = Atoms("Fe", cell=(1, 1, 1), pbc=True)
    controller = WorkspaceController(
        WorkspaceState(atoms=atoms, potential_path="Fe.pot")
    )
    generation = controller.structure_generation
    state_id = controller.state_id

    def fail(candidate):
        candidate.symbols = "Cu"
        candidate.cell[0, 0] = 9.0
        raise RuntimeError("edit failed")

    with pytest.raises(RuntimeError, match="edit failed"):
        controller.apply_structure_edit(
            fail,
            expected_structure_generation=generation,
        )

    assert controller.atoms is atoms
    assert atoms.get_chemical_symbols() == ["Fe"]
    assert atoms.cell[0, 0] == 1.0
    assert controller.potential_path == "Fe.pot"
    assert controller.state_id == state_id
    assert controller.result_store.results == ()
    assert controller.structure_generation == generation
