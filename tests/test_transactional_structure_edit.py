from ase import Atoms
import pytest

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


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
