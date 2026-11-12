import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from guy4ase.gui.dialogs.input_file import InputFileEditor
from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_ok_parses_text_and_cancel_leaves_original_unchanged(application):
    parameters = InputParameters.create("scf")
    editor = InputFileEditor(parameters)
    editor.editor.setPlainText(editor.editor.toPlainText().replace("NITER=200", "NITER=135"))
    editor.accept()
    assert editor.result() == QDialog.DialogCode.Accepted
    assert editor.parameters.SCF.NITER() == 135
    assert parameters.SCF.NITER() == 200
    editor = InputFileEditor(parameters)
    editor.editor.setPlainText("garbage")
    editor.reject()
    assert editor.parameters is None
    assert parameters.SCF.NITER() == 200


def test_parse_error_highlights_suspected_line_and_keeps_draft(application):
    parameters = InputParameters.create("scf")
    editor = InputFileEditor(parameters)
    editor.show()
    source = editor.editor.toPlainText().replace("NITER=200", "NITER=invalid")
    expected_line = next(i for i, line in enumerate(source.splitlines(), 1) if "NITER=invalid" in line)
    editor.editor.setPlainText(source)
    editor.accept()
    assert editor.isVisible()
    assert editor.parameters is None
    assert editor.error_line == expected_line
    assert editor.editor.extraSelections()[0].cursor.blockNumber() == expected_line - 1
    assert "Suspected location" in editor.error_label.text()
    assert editor.editor.toPlainText() == source
    assert parameters.SCF.NITER() == 200
    editor.editor.setPlainText(source.replace("NITER=invalid", "NITER=135"))
    assert not editor.editor.extraSelections()
    editor.accept()
    assert editor.parameters.SCF.NITER() == 135


def test_different_task_is_rejected(application):
    editor = InputFileEditor(InputParameters.create("scf"))
    editor.editor.setPlainText(InputParameters.create("dos").to_string(validate=False))
    editor.accept()
    assert editor.parameters is None
    assert editor.error_label.text()


def test_text_edit_is_one_undoable_session_change(application, monkeypatch):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))

    def edit(editor):
        source = editor.editor.toPlainText().replace("NITER=200", "NITER=135").replace("NKTAB=250", "NKTAB=500")
        editor.editor.setPlainText(source)
        editor.accept()
        return editor.result()

    monkeypatch.setattr(InputFileEditor, "exec", edit)
    dialog.edit_input_button.click()
    assert dialog.session.undo_stack.count() == 1
    assert dialog.session.value(("SCF", "NITER")) == 135
    assert dialog.session.value(("TAU", "NKTAB")) == 500
    dialog.undo_button.click()
    assert not dialog.session.is_modified()
    dialog.redo_button.click()
    assert dialog.session.value(("SCF", "NITER")) == 135
    dialog.close()


def test_cancel_does_not_add_history(application, monkeypatch):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    monkeypatch.setattr(InputFileEditor, "exec", lambda editor: QDialog.DialogCode.Rejected)
    dialog.edit_input_button.click()
    assert dialog.session.undo_stack.count() == 0
    assert not dialog.session.is_modified()
    dialog.close()


def test_apply_callback_error_propagates_without_becoming_input_error(application):
    parameters = InputParameters.create("scf")
    error = RuntimeError("broken session invariant")

    def apply(_candidate):
        raise error

    editor = InputFileEditor(parameters, apply_parameters=apply)

    with pytest.raises(RuntimeError, match="broken session invariant") as raised:
        editor.accept()

    assert raised.value is error
    assert editor.parameters is None
    assert editor.error_line is None
    assert not editor.error_label.text()
    assert not editor.editor.extraSelections()


def test_text_editor_uses_from_file_without_copying_original(application, monkeypatch):
    parameters = InputParameters.create("scf")

    def broken_copy(self, *, copy_values):
        raise AssertionError("text parsing must not copy the original model")

    monkeypatch.setattr(type(parameters), "copy", broken_copy)
    editor = InputFileEditor(parameters)
    editor.accept()

    assert editor.parameters is not None
    assert editor.parameters is not parameters
    assert editor.parameters.task_name == "SCF"


def test_same_input_schema_can_change_effective_task(application):
    original = InputParameters.create("bsfek")
    plane = InputParameters.create("bsfkk")
    plane.CONTROL.POTFIL.set("Fe.pot")
    plane.set({
        "ENERGY": {"NE": [1]},
        "TASK": {
            "KA": [[0.0, 0.0, 0.0]],
            "K1": [1.0, 0.0, 0.0],
            "K2": [0.0, 1.0, 0.0],
            "NK1": 45,
            "NK2": 55,
        },
    })
    editor = InputFileEditor(original)
    editor.editor.setPlainText(plane.to_string(validate=False))
    editor.accept()

    assert editor.parameters is not None
    assert editor.parameters.definition_name.lower() == "bsf"
    assert editor.parameters.task_name.lower() == "bsfkk"
