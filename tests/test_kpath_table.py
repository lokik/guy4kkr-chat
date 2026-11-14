import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit
from PyQt6.QtTest import QTest
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.widgets.numeric_table import coordinate_text


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(application):
    parameters = InputParameters.create("bsfek")
    parameters.set({"ENERGY": {"NE": [200]}, "TASK": {
        "KA": [[-.4999999999999999, .5000000000000002, -2.33e-32], [0., 0., 0.]],
        "KE": [[0., 0., 0.], [1., 1., 1.]], "NK": 250}})
    dialog = GuidedInputParametersDialog("bsf", parameters)
    yield dialog
    dialog.close()


def geometry(dialog):
    return dialog.editors_for(("TASK", "KA"))[0].control


def edit(widget, row, column, text):
    index = widget.table.model().index(row, column)
    editor = QLineEdit()
    editor.setText(text)
    widget.delegate.setModelData(editor, widget.table.model(), index)


def test_table_preserves_raw_precision_and_disconnected_segments(dialog):
    widget = geometry(dialog)
    assert dialog.editors_for(("TASK", "KE"))[0] is dialog.editors_for(("TASK", "KA"))[0]
    assert widget.table.columnCount() == 6 and widget.table.rowCount() == 2
    assert coordinate_text(widget._rows()[0][0]) == "-0.5"
    assert coordinate_text(widget._rows()[0][2]) == "≈0"
    assert widget._rows()[0][0] == -.4999999999999999
    widget.table.selectAll()
    widget.copy()
    assert "-2.33e-32" in QApplication.clipboard().text()
    widget.table.setCurrentCell(0, 0)
    widget.paste()
    assert not dialog.session.is_modified()
    raw = dialog.session.value(("TASK", "KA")).copy()
    edit(widget, 1, 4, "1/2")
    assert dialog.session.value(("TASK", "KE"))[1, 1] == .5
    np.testing.assert_array_equal(dialog.session.value(("TASK", "KA")), raw)
    assert dialog.session.undo_stack.count() == 1
    assert "TASK.KE[2]" in dialog.session.history_description(undo=True)
    dialog.select_page("quick")
    dialog.session.undo_stack.undo()
    QApplication.processEvents()
    assert dialog.pages.currentIndex() == dialog._page_indexes["path"]
    assert widget.table.currentRow() == 1 and widget.table.currentColumn() == 3
    assert not dialog.session.is_modified()
    dialog.session.undo_stack.redo()
    assert widget._rows()[1][4] == .5


def test_add_remove_move_and_atomic_paste(dialog):
    widget = geometry(dialog)
    original = widget._rows()
    widget.table.setCurrentCell(1, 0)
    widget.add_segment()
    assert widget.table.rowCount() == 3
    assert widget._rows()[2][:3] == original[1][3:]
    assert dialog.session.working_parameters.TASK.NKDIR() == 3
    widget.move_segment(-1)
    assert widget._rows()[1][:3] == original[1][3:]
    widget.table.selectRow(1)
    widget.remove_segments()
    assert widget._rows() == original
    before = dialog.session.undo_stack.count()
    widget.table.setCurrentCell(0, 0)
    QApplication.clipboard().setText("0\t1/2\t0\t1\t0\t0\n1\t0\t0\t1\t1\t0")
    widget.paste()
    assert widget._rows() == [[0., .5, 0., 1., 0., 0.], [1., 0., 0., 1., 1., 0.]]
    assert dialog.session.undo_stack.count() == before + 1
    dialog.session.undo_stack.undo()
    assert widget._rows() == original


@pytest.mark.parametrize("value", ["nan", "inf", "1/0", "bad", ""])
def test_invalid_cell_stays_visible_and_blocks_acceptance(dialog, value):
    widget = geometry(dialog)
    edit(widget, 0, 0, value)
    assert not dialog.session.is_modified()
    assert widget.table.item(0, 0).data(Qt.ItemDataRole.EditRole) == value
    assert not dialog._commit_pending()
    edit(widget, 0, 0, "-1/2")
    assert dialog._commit_pending()


def test_paste_limits_and_invalid_input_are_non_mutating(dialog):
    widget = geometry(dialog)
    original = widget._rows()
    for text in ("0\tbroken", "\n".join(["0\t0\t0\t1\t0\t0"] * 10), "0\t1\n0"):
        QApplication.clipboard().setText(text)
        widget.paste()
        assert widget._rows() == original
        assert not dialog.session.is_modified()
    # Complete rows may extend the table, up to nine segments.
    widget.table.setCurrentCell(0, 0)
    QApplication.clipboard().setText("\n".join(["0\t0\t0\t1\t0\t0"] * 9))
    widget.paste()
    assert widget.table.rowCount() == 9
    assert not widget.add_button.isEnabled()
    assert dialog._commit_pending()


def test_mode_switch_and_default_origin(dialog):
    widget = geometry(dialog)
    mode = dialog.editors_for(("ENERGY", "NE"))[0]
    original = widget._rows()
    mode.control.mode_combo.setCurrentIndex(mode.control.mode_combo.findData("KK"))
    assert widget.table.columnCount() == 3 and widget.table.rowCount() == 1
    widget.clear_origin()
    assert dialog.session.value(("TASK", "KA")) is None
    assert widget._rows() == [[None, None, None]]
    for column, value in enumerate(("1/2", "0", "1")):
        edit(widget, 0, column, value)
    assert widget._rows() == [[.5, 0., 1.]]
    assert dialog._commit_pending()
    for _ in range(3):
        dialog.session.undo_stack.undo()
    assert widget.table.columnCount() == 6
    assert widget._rows() == original


def test_edited_table_saves_and_reloads(dialog, tmp_path):
    widget = geometry(dialog)
    edit(widget, 0, 0, "-1/2")
    widget.add_segment()
    parameters = dialog.session.result()
    parameters.CONTROL.POTFIL.set("Fe.pot")
    filename = tmp_path / "Fe_BSF.inp"
    parameters.save_to_file(str(filename))
    loaded = InputParameters.from_file(str(filename))
    np.testing.assert_allclose(loaded.TASK.KA(), parameters.TASK.KA(), atol=1e-12)
    np.testing.assert_allclose(loaded.TASK.KE(), parameters.TASK.KE(), atol=1e-12)


def test_actual_cell_editor_commits_fraction_on_tab(dialog):
    dialog.select_page("path")
    dialog.show()
    QApplication.processEvents()
    widget = geometry(dialog)
    index = widget.table.model().index(0, 0)
    widget.table.setCurrentIndex(index)
    widget.table.edit(index)
    QApplication.processEvents()
    editor = QApplication.focusWidget()
    assert isinstance(editor, QLineEdit)
    assert editor.text() == "-0.4999999999999999"
    QTest.keyClicks(editor, "1/3")
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    QApplication.processEvents()
    assert dialog.session.value(("TASK", "KA"))[0, 0] == 1 / 3
    assert dialog.form.views_for(("TASK", "KA"))[0].label.font().bold()
