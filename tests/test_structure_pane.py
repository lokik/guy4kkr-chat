"""Focused tests for the shared 2D-builder structure pane."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms

from ase2sprkkr_gui.gui.widgets.structures.structure_pane import StructurePane


def test_structure_pane_tracks_presence_and_emits_actions():
    pane = StructurePane(empty_text="Vacuum")
    scale_requests = []
    pane.scaleRequested.connect(lambda: scale_requests.append(True))

    assert pane.atoms is None
    assert not pane.scale_button.isEnabled()
    assert not pane.rotate_button.isEnabled()

    atoms = Atoms("Fe", cell=[2.0, 3.0, 4.0])
    pane.set_atoms(atoms)
    pane.set_match_enabled(True)
    pane.scale_button.click()

    assert pane.atoms is atoms
    assert pane.scale_button.isEnabled()
    assert pane.rotate_button.isEnabled()
    assert pane.match_axis_button.isEnabled()
    assert scale_requests == [True]

    pane.set_atoms(None)

    assert pane.atoms is None
    assert not pane.scale_button.isEnabled()
    assert not pane.rotate_button.isEnabled()
    pane.close()
