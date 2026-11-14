from __future__ import annotations

import pytest
from ase import Atoms

from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController


def test_controller_exposes_live_read_only_workspace_properties():
    controller = WorkspaceController(WorkspaceState())

    assert controller.atoms is None

    atoms = Atoms("Fe")
    controller.replace_structure(atoms, potential_path="Fe.pot")

    assert controller.atoms is atoms
    assert controller.potential_path == "Fe.pot"

    with pytest.raises(AttributeError):
        controller.atoms = Atoms("Cu")
    with pytest.raises(AttributeError):
        controller.potential_path = "Cu.pot"

    assert controller.atoms is atoms
    assert controller.potential_path == "Fe.pot"
