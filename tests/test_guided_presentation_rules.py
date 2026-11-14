"""Regression tests for declarative guided-dialog presentation rules."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import pytest
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def kk_parameters():
    parameters = InputParameters.create("bsfkk")
    parameters.set({"ENERGY": {"NE": [1]}, "TASK": {
        "KA": [[0., 0., 0.]], "K1": [1., 0., 0.], "K2": [0., 1., 0.],
        "NK1": 45, "NK2": 55,
    }})
    return parameters


def switch_mode(dialog, mode):
    editor = next(
        item for item in dialog.editors_for(("ENERGY", "NE"))
        if item.placement.editor == "bsf_mesh"
    )
    editor.control.mode_combo.setCurrentIndex(editor.control.mode_combo.findData(mode))


def test_bsf_rules_update_mirrors_labels_and_conditional_errors(application):
    dialog = GuidedInputParametersDialog("bsf", kk_parameters())
    emin = dialog.editors_for(("ENERGY", "EMIN"))
    emax = dialog.editors_for(("ENERGY", "EMAX"))
    k1 = dialog.editors_for(("TASK", "K1"))[0]

    assert {editor.accessibleName() for editor in emin} == {"Fixed energy"}
    assert all(editor.isHidden() for editor in emax)
    dialog.session.set_value(("TASK", "K1"), None)
    assert ("TASK", "K1") in dialog.form.errors

    switch_mode(dialog, "EK")
    assert {editor.accessibleName() for editor in emin} == {"Minimum energy"}
    assert all(not editor.isHidden() for editor in emax)
    assert k1.isHidden()
    assert ("TASK", "K1") not in dialog.form.errors

    dialog.session.undo_stack.undo()
    application.processEvents()
    assert not k1.isHidden()
    assert ("TASK", "K1") in dialog.form.errors
    assert {editor.accessibleName() for editor in emin} == {"Fixed energy"}
    dialog.close()


@pytest.mark.parametrize("task", ["scf", "bsf"])
def test_shared_rules_reapply_without_mutating_or_adding_history(application, task):
    parameters = kk_parameters() if task == "bsf" else InputParameters.create(task)
    dialog = GuidedInputParametersDialog(task, parameters)
    radius = dialog.editors_for(("TAU", "CLURAD"))[0]
    initial_count = dialog.session.undo_stack.count()

    assert initial_count == 0
    assert not radius.control.isEnabled()

    dialog.session.set_value(("TAU", "KKRMODE"), "TB")
    assert radius.control.isEnabled()
    dialog.session.undo_stack.undo()
    application.processEvents()
    assert not radius.control.isEnabled()
    dialog.close()
