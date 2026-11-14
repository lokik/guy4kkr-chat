import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import numpy as np
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from ase2sprkkr.common.grammar_types import SetOf
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("task", ["scf", "bsf"])
@pytest.mark.parametrize("name", ["C", "SOC"])
def test_scaling_default_and_type_rows_undo_redo(application, task, name):
    backend_task = "bsfkk" if task == "bsf" else task
    parameters = InputParameters.create(backend_task)
    parameters.MODE[name].set({"def": 0.8, 2: 0.4})
    dialog = GuidedInputParametersDialog(task, parameters)
    control = dialog.editors_for(("MODE", name))[0].control
    assert not dialog.session.is_modified()
    assert control.table.verticalHeaderItem(0).text() == "Global"
    assert control.table.verticalHeaderItem(1).text() == "Type 2"
    control.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, .6)
    assert dialog.session.value(("MODE", name)) == {"def": .6, 2: .4}
    control.type_index.setValue(3)
    control.add_button.click()
    assert dialog.session.value(("MODE", name))[3] == 1.
    control.table.item(2, 0).setData(Qt.ItemDataRole.EditRole, .2)
    assert dialog.session.value(("MODE", name))[3] == .2
    control.table.setCurrentCell(2, 0)
    control.remove_button.click()
    assert 3 not in dialog.session.value(("MODE", name))
    dialog.undo_button.click()
    assert dialog.session.value(("MODE", name))[3] == .2
    dialog.redo_button.click()
    assert 3 not in dialog.session.value(("MODE", name))
    dialog.close()


def test_scaling_invalid_draft_does_not_modify_session(application):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    control = dialog.editors_for(("MODE", "SOC"))[0].control
    control.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, "bad")
    assert ("MODE", "SOC") in dialog.form.errors
    assert not dialog.session.is_modified()
    control.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, .5)
    assert ("MODE", "SOC") not in dialog.form.errors
    assert dialog.session.value(("MODE", "SOC"))["def"] == .5
    dialog.close()


def test_array_scaling_uses_orbital_columns_without_expanding_on_open(application, monkeypatch):
    parameters = InputParameters.create("scf")
    # Exercise array-capable metadata without changing the installed library.
    definition = parameters.MODE.SOC._definition
    monkeypatch.setattr(definition, "type", SetOf(float, min_length=1))
    monkeypatch.setattr(definition, "default_value", np.array([1.]))
    parameters.MODE.SOC.set({"def": [1.], 2: [.8, .7, .6]})
    dialog = GuidedInputParametersDialog("scf", parameters)
    control = dialog.editors_for(("MODE", "SOC"))[0].control
    assert control.orbital_resolved
    assert [control.table.horizontalHeaderItem(i).text() for i in range(4)] == ["s", "p", "d", "f"]
    assert not dialog.session.is_modified()
    assert control.table.item(1, 3).data(Qt.ItemDataRole.EditRole) == .6
    control.table.item(1, 2).setData(Qt.ItemDataRole.EditRole, .3)
    np.testing.assert_equal(dialog.session.value(("MODE", "SOC"))[2], [.8, .7, .3, .6])
    np.testing.assert_equal(dialog.session.value(("MODE", "SOC"))["def"], [1.])
    dialog.undo_button.click()
    assert not dialog.session.is_modified()
    dialog.close()


def test_single_row_tables_fit_contents_without_empty_viewport(application):
    parameters = InputParameters.create("bsfkk")
    parameters.TASK.set({"K1": [1., 0., 0.], "K2": [0., 1., 0.], "NK1": 60, "NK2": 60})
    dialog = GuidedInputParametersDialog("bsf", parameters)
    dialog.show()
    dialog.select_page("path")
    application.processEvents()
    for name in ("KA", "K1", "K2"):
        control = dialog.editors_for(("TASK", name))[0].control
        table = control.table
        assert table.rowCount() == 1
        assert table.height() == table.horizontalHeader().sizeHint().height() + table.rowHeight(0) + 2 * table.frameWidth()
        assert table.viewport().height() <= table.rowHeight(0) + 1
    dialog.close()
