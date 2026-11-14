"""Thin Qt integration tests for element assignment."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import numpy as np
from ase import Atoms
from PyQt6.QtWidgets import QDialog

from ase2sprkkr_gui.gui.dialogs.structures.element_assignment import (
    ElementAssignmentDialog,
)


def _atoms() -> Atoms:
    atoms = Atoms(
        "Fe2",
        scaled_positions=((0, 0, 0), (0.5, 0.5, 0.5)),
        cell=np.eye(3),
        pbc=True,
    )
    atoms.set_array("spacegroup_kinds", np.asarray((0, 0), dtype=int))
    atoms.set_array("labels", np.asarray(("a.1", "a.2"), dtype=object))
    atoms.info["occupancy"] = {"0": {"Fe": 1.0}}
    return atoms


def test_break_button_delegates_to_model_and_refreshes_rows():
    dialog = ElementAssignmentDialog()
    dialog.setup(_atoms())
    original_site = dialog._draft.sites[0]
    calls = []
    original_split = dialog._draft.split_site

    def split(site):
        calls.append(site)
        return original_split(site)

    dialog._draft.split_site = split
    dialog._letter_widgets[0].break_btn.click()

    assert calls == [original_site]
    assert len(dialog._draft.sites) == 2
    assert [row.label for row in dialog._letter_widgets] == ["a.1", "a.2"]
    dialog.close()


def test_cancel_does_not_apply_working_state_to_source():
    atoms = _atoms()
    original = atoms.copy()
    dialog = ElementAssignmentDialog()
    dialog.setup(atoms)

    dialog._letter_widgets[0].break_btn.click()
    dialog.reject()

    np.testing.assert_array_equal(atoms.positions, original.positions)
    np.testing.assert_array_equal(
        atoms.get_array("spacegroup_kinds"),
        original.get_array("spacegroup_kinds"),
    )
    dialog.close()


def test_accept_returns_unapplied_draft():
    dialog = ElementAssignmentDialog()
    dialog.setup(_atoms())
    dialog._letter_widgets[0].break_btn.click()

    dialog._on_ok()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog._result is dialog._draft
    result = dialog._result.apply()
    np.testing.assert_array_equal(
        result.get_array("spacegroup_kinds"), (0, 1)
    )
    dialog.close()
