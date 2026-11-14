from ase import Atoms

from ase2sprkkr_gui.gui.application.workspace_controller import (
    DocumentChange,
    WorkspaceController,
)


def test_replace_structure_none_clears_active_state_without_erasing_history():
    controller = WorkspaceController()
    atoms = Atoms("Fe")

    assert controller.replace_structure(atoms) is DocumentChange.APPLIED
    structure_id = controller.structure_id
    state_id = controller.state_id
    assert structure_id is not None
    assert state_id is not None

    assert controller.replace_structure(None) is DocumentChange.APPLIED
    assert controller.atoms is None
    assert controller.structure_id is None
    assert controller.state_id is None
    assert controller.potential_path is None

    # Clearing the draft is not deletion of provenance/history.
    state = controller.result_store.state(state_id)
    assert state.structure_id == structure_id
