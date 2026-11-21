"""Cluster history transactions and edit grouping through real Qt controls."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
import pytest
from ase import Atoms
from PyQt6.QtCore import QItemSelectionModel, Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

pytest.importorskip("ase2sprkkr.sprkkr.embedding_geometry")

from ase2sprkkr.sprkkr.embedding_geometry import HostSite

from ase2sprkkr_gui.ase.embedding import EmbeddingDraft
from ase2sprkkr_gui.gui.dialogs.structures.embedding import BuildEmbeddingDialog
from ase2sprkkr_gui.gui.dialogs.structures.embedding_history import EmbeddingUndoStack


@pytest.fixture
def atoms():
    return Atoms("Cu", positions=[[0, 0, 0]], cell=[2., 2., 2.], pbc=True)


@pytest.fixture
def dialog(atoms):
    return BuildEmbeddingDialog(atoms)


def focus(dialog, widget):
    dialog.show()
    dialog.activateWindow()
    QApplication.processEvents()
    widget.setFocus()
    QApplication.processEvents()


def type_number(spin, value):
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), str(value))


def shortcut(dialog, key):
    widget = QApplication.focusWidget() or dialog
    QTest.keySequence(widget, QKeySequence(key))


def test_draft_snapshots_restore_independent_arrays_and_original_cluster(atoms):
    draft = EmbeddingDraft(atoms)
    draft.include([draft.center])
    draft.entries[draft.center].magnetisation[:] = [15., 30.]
    original = draft.to_atoms()
    draft = EmbeddingDraft(atoms, original)
    before = draft.snapshot()
    draft.entries[draft.center].occupation["Cu"] = .5
    draft.entries[draft.center].displacement[0] = .2
    draft.entries[draft.center].magnetisation[0] = 90.
    draft.restore(before)
    assert draft.is_unchanged()
    assert draft.host is atoms
    assert draft.original_cluster is original
    draft.entries[draft.center].displacement[0] = .7
    np.testing.assert_array_equal(before.entries[before.center].displacement, [0, 0, 0])
    draft.restore(before)
    np.testing.assert_array_equal(draft.entries[draft.center].magnetisation, [15, 30])


def test_failed_history_transaction_rolls_back_and_does_not_enter_history(atoms):
    draft = EmbeddingDraft(atoms)
    stack = EmbeddingUndoStack(draft)
    before = draft.snapshot()

    def fail():
        draft.set_occupation([draft.center], {"Fe": 1.})
        draft.set_center(HostSite(0, (2, 0, 0)))
        raise ValueError("Invalid edit")

    with pytest.raises(ValueError, match="Invalid edit"):
        stack.apply(fail, "Failed edit")
    assert draft.snapshot() == before
    assert stack.count() == 0


def test_returning_to_initial_value_removes_the_merged_history_command(atoms):
    draft = EmbeddingDraft(atoms)
    draft.include([draft.center])
    stack = EmbeddingUndoStack(draft)
    key = stack.edit_key("displacement")
    for value in (.1, .2, 0.):
        stack.apply(lambda value=value: draft.set_displacement([draft.center], [value, 0., 0.]),
                    "Displacement", merge_key=key)
    assert stack.count() == 0
    assert not stack.canUndo()


def test_displacement_typing_merges_across_timer_commits_and_shortcuts_restore_all(dialog):
    spin = dialog.deltas[0]
    focus(dialog, spin)
    type_number(spin, .1)
    QTest.qWait(420)
    assert dialog.undo_stack.count() == 1
    type_number(spin, .25)
    QTest.qWait(420)
    assert dialog.undo_stack.count() == 1
    shortcut(dialog, QKeySequence.StandardKey.Undo)
    assert not dialog.draft.entries
    assert spin.value() == 0.
    QTest.qWait(420)
    assert not dialog.draft.entries  # No late timer can recreate the edit.
    shortcut(dialog, QKeySequence.StandardKey.Redo)
    np.testing.assert_array_equal(dialog.draft.entries[dialog.draft.center].displacement,
                                  [.25, 0., 0.])


@pytest.mark.parametrize("boundary", ["enter", "focus"])
def test_a_new_visit_to_the_same_number_is_a_new_undo_step(dialog, boundary):
    spin = dialog.deltas[0]
    focus(dialog, spin)
    type_number(spin, .1)
    if boundary == "enter":
        QTest.keyClick(spin, Qt.Key.Key_Return)
        assert dialog.isVisible()  # Enter commits the field, not the dialog.
    else:
        focus(dialog, dialog.deltas[1])
        focus(dialog, spin)
    type_number(spin, .2)
    dialog._apply_pending_displacement()
    assert dialog.undo_stack.count() == 2
    shortcut(dialog, QKeySequence.StandardKey.Undo)
    assert spin.value() == pytest.approx(.1)
    shortcut(dialog, QKeySequence.StandardKey.Undo)
    assert not dialog.draft.entries


def test_pending_displacement_is_undoable_and_redoable_before_timer_fires(dialog):
    dialog.deltas[0].setValue(.12)
    assert dialog.undo_action.isEnabled()
    assert dialog.undo_stack.count() == 0
    dialog.undo_action.trigger()
    assert not dialog.draft.entries
    assert not dialog._displacement_timer.isActive()
    assert dialog.redo_action.isEnabled()
    dialog.redo_action.trigger()
    assert dialog.deltas[0].value() == pytest.approx(.12)
    QTest.qWait(420)
    assert dialog.undo_stack.count() == 1


def test_zero_displacement_does_not_include_an_unselected_host_site(dialog):
    dialog.deltas[0].setValue(.1)
    dialog.deltas[0].setValue(0.)
    dialog._apply_pending_displacement()
    assert not dialog.draft.entries
    assert dialog.undo_stack.count() == 0


def test_expansion_is_one_step_and_no_op_edits_preserve_redo(dialog):
    dialog._add_shells()
    expanded = dialog.draft.snapshot()
    assert len(expanded.entries) == 7
    assert dialog.undo_stack.count() == 1
    dialog.radius.setValue(2.01)
    dialog._add_radius()
    assert dialog.undo_stack.count() == 1
    dialog._undo()
    assert not dialog.draft.entries
    dialog._exclude()  # No-op must leave the expansion available for redo.
    assert dialog.redo_action.isEnabled()
    dialog._redo()
    assert dialog.draft.snapshot() == expanded


def test_exclude_undo_restores_every_physical_value_and_redo_is_not_aliased(dialog):
    dialog._include()
    site = dialog.draft.center
    dialog.occupation.rows[0]["elem"].setText("Fe")
    dialog.deltas[0].setValue(.13)
    dialog._apply_pending_displacement()
    before = dialog.draft.snapshot()
    dialog._exclude()
    assert not dialog.draft.entries
    dialog._undo()
    assert dialog.draft.snapshot() == before
    dialog._redo()
    assert not dialog.draft.entries
    dialog._undo()
    dialog.deltas[1].setValue(.24)
    dialog._apply_pending_displacement()
    assert not dialog.redo_action.isEnabled()
    assert dialog.draft.entries[site].occupation == {"Fe": 1.}
    np.testing.assert_array_equal(dialog.draft.entries[site].displacement, [.13, .24, 0.])
    dialog._undo()
    assert dialog.draft.snapshot() == before


def test_symmetry_occupation_is_a_single_complete_undo_step(dialog, atoms):
    dialog._cell_changed((1, 0, 0))
    dialog.symmetric.setChecked(True)
    dialog.occupation.rows[0]["elem"].setText("Fe")
    assert len(dialog.draft.entries) == 6
    assert dialog.undo_stack.count() == 1
    dialog._undo()
    assert not dialog.draft.entries
    dialog._redo()
    assert all(entry.occupation == {"Fe": 1.} for entry in dialog.draft.entries.values())
    assert atoms.get_chemical_symbols() == ["Cu"]


def test_pending_displacement_keeps_its_original_symmetry_context(dialog):
    dialog._cell_changed((1, 0, 0))
    selected = dialog._selected_site
    dialog.deltas[0].setValue(.1)
    dialog.symmetric.setChecked(True)
    assert set(dialog.draft.entries) == {selected}
    dialog.deltas[0].setValue(.2)
    dialog._apply_pending_displacement()
    assert len(dialog.draft.entries) == 6
    dialog._undo()
    assert set(dialog.draft.entries) == {selected}
    np.testing.assert_array_equal(dialog.draft.entries[selected].displacement, [.1, 0., 0.])


def test_invalid_pending_vector_undo_cancels_it_without_undoing_previous_command(dialog, monkeypatch):
    dialog._cell_changed((1, 0, 0))
    dialog._include()
    before = dialog.draft.snapshot()
    dialog.symmetric.setChecked(True)
    dialog.deltas[1].setValue(.1)  # Conflicts with the site's stabilizer symmetry.
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog._undo()
    assert dialog.draft.snapshot() == before
    assert not dialog._displacement_timer.isActive()
    assert dialog.deltas[1].value() == 0.
    assert dialog.undo_stack.index() == 1
    assert not warnings


def test_rejected_displacement_commit_restores_controls_and_preserves_history(dialog, monkeypatch):
    dialog._cell_changed((1, 0, 0))
    dialog._include()
    before = dialog.draft.snapshot()
    dialog.symmetric.setChecked(True)
    dialog.deltas[1].setValue(.1)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog._apply_pending_displacement()
    assert len(warnings) == 1
    assert dialog.draft.snapshot() == before
    assert dialog.deltas[1].value() == 0.
    assert not dialog._displacement_timer.isActive()
    assert dialog.undo_stack.index() == 1


def test_incomplete_occupation_undo_only_cancels_its_own_edit(dialog):
    dialog._include()
    dialog.occupation.rows[0]["occ"].setValue(.5)
    assert not dialog.occupation.is_valid()
    assert dialog.undo_action.isEnabled()
    dialog._undo()
    assert dialog.occupation.occupation() == {"Cu": 1.}
    assert len(dialog.draft.entries) == 1  # The earlier Include is intact.
    dialog._undo()
    assert not dialog.draft.entries


def test_occupation_shortcut_undo_groups_valid_and_incomplete_text(dialog):
    element = dialog.occupation.rows[0]["elem"]
    focus(dialog, element)
    element.selectAll()
    QTest.keyClicks(element, "Fe")  # F and Fe are both valid intermediate states.
    assert dialog.undo_stack.count() == 1
    QTest.keyClick(element, Qt.Key.Key_Backspace)
    QTest.keyClick(element, Qt.Key.Key_Backspace)
    assert not dialog.occupation.is_valid()
    shortcut(dialog, QKeySequence.StandardKey.Undo)
    assert not dialog.draft.entries
    assert dialog.occupation.occupation() == {"Cu": 1.}
    shortcut(dialog, QKeySequence.StandardKey.Redo)
    assert dialog.occupation.occupation() == {"F": 1.}


def test_undo_of_an_empty_new_occupation_row_does_not_undo_an_earlier_edit(dialog):
    dialog.occupation.rows[0]["elem"].setText("Fe")
    dialog.occupation.add_btn.click()
    assert len(dialog.occupation.rows) == 2
    dialog._undo()
    assert len(dialog.occupation.rows) == 1
    assert dialog.occupation.occupation() == {"Fe": 1.}
    assert dialog.undo_stack.index() == 1


def test_multisite_restore_is_one_command_and_keeps_selection():
    dialog = BuildEmbeddingDialog(Atoms("CuNi", positions=[[0, 0, 0], [1, 1, 1]],
                                       cell=[3, 3, 3], pbc=True))
    dialog.sites.selectAll()
    selected = set(dialog._selected_sites)
    assert len(selected) == 2
    dialog.occupation.rows[0]["elem"].setText("Co")
    dialog.occupation.restore_btn.click()
    assert [dialog.draft.entries[s].occupation for s in sorted(selected)] == [{"Cu": 1.}, {"Ni": 1.}]
    dialog._undo()
    assert all(entry.occupation == {"Co": 1.} for entry in dialog.draft.entries.values())
    assert dialog._selected_sites == selected
    dialog._undo()
    assert not dialog.draft.entries
    assert len(dialog.sites.selectionModel().selectedRows()) == 2


def test_selection_change_and_new_branch_do_not_merge_visits_to_one_site():
    dialog = BuildEmbeddingDialog(Atoms("CuNi", positions=[[0, 0, 0], [1, 1, 1]],
                                       cell=[3, 3, 3], pbc=True))
    first = dialog._selected_site
    dialog.occupation.rows[0]["elem"].setText("Fe")
    dialog.sites.selectRow(1)
    dialog.sites.setCurrentCell(0, 0, QItemSelectionModel.SelectionFlag.ClearAndSelect
                                | QItemSelectionModel.SelectionFlag.Rows)
    dialog.occupation.rows[0]["elem"].setText("Co")
    assert dialog.undo_stack.count() == 2
    dialog._undo()
    assert dialog.draft.entries[first].occupation == {"Fe": 1.}
    dialog.occupation.rows[0]["elem"].setText("Ni")
    assert not dialog.undo_stack.canRedo()
    dialog._undo()
    assert dialog.draft.entries[first].occupation == {"Fe": 1.}


def test_centre_change_undo_restores_summary_and_has_no_host_side_effects(dialog, atoms):
    original = dialog.draft.center
    dialog._cell_changed((1, 0, 0))
    dialog._set_centre()
    assert dialog.draft.center == HostSite(0, (1, 0, 0))
    dialog._undo()
    assert dialog.draft.center == original
    assert "in (0, 0, 0)" in dialog.centre_label.text()
    assert not dialog.draft.entries
    np.testing.assert_array_equal(atoms.positions, [[0, 0, 0]])


def test_centre_only_change_is_undoable_and_committed_on_accept(atoms):
    draft = EmbeddingDraft(atoms)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    dialog = BuildEmbeddingDialog(cluster)
    original = dialog.draft.center
    alternative = HostSite(0, (1, 0, 0))
    dialog.draft.set_center(alternative)
    assert dialog.has_unapplied_changes()
    dialog._accept()
    assert dialog.result_atoms is not cluster
    assert EmbeddingDraft(atoms, dialog.result_atoms).center == alternative
    assert EmbeddingDraft(atoms, cluster).center == original


def test_undo_to_original_cluster_preserves_unchanged_acceptance(atoms):
    draft = EmbeddingDraft(atoms)
    draft.include([draft.center])
    original = draft.to_atoms()
    dialog = BuildEmbeddingDialog(original)
    dialog.occupation.rows[0]["elem"].setText("Fe")
    assert not dialog.draft.is_unchanged()
    dialog._undo()
    assert dialog.draft.is_unchanged()
    dialog._accept()
    assert dialog.result_atoms is original


def test_normalized_occupation_numbers_merge_both_components_into_one_edit(atoms):
    draft = EmbeddingDraft(atoms)
    draft.set_occupation([draft.center], {"Cu": .5, "Ni": .5})
    dialog = BuildEmbeddingDialog(draft.to_atoms())
    spin = dialog.occupation.rows[0]["occ"]
    focus(dialog, spin)
    type_number(spin, .6)
    type_number(spin, .7)
    assert dialog.occupation.occupation() == {"Cu": .7, "Ni": .3}
    assert dialog.undo_stack.count() == 1
    shortcut(dialog, QKeySequence.StandardKey.Undo)
    assert dialog.occupation.occupation() == {"Cu": .5, "Ni": .5}
    shortcut(dialog, QKeySequence.StandardKey.Redo)
    assert dialog.occupation.occupation() == {"Cu": .7, "Ni": .3}


@pytest.mark.parametrize("value", [None, .1])
def test_undo_of_unfinished_negative_number_preserves_earlier_include(dialog, value):
    dialog._include()
    spin = dialog.deltas[0]
    focus(dialog, spin)
    if value is not None:
        type_number(spin, value)
        QTest.qWait(420)
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "-")
    assert not spin.hasAcceptableInput()
    shortcut(dialog, QKeySequence.StandardKey.Undo)
    assert len(dialog.draft.entries) == 1
    assert dialog.undo_stack.index() == 1
    assert spin.value() == 0.
    assert spin.hasAcceptableInput()
