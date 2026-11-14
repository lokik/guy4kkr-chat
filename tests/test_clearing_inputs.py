import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/ase2sprkkr_gui-test-matplotlib')

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog
from ase2sprkkr_gui.gui.widgets.input_parameters.energy import EnergyEditor


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def erase(control):
    control.setFocus()
    control.selectAll()
    QTest.keyClick(control, Qt.Key.Key_Backspace)


def backend_task(task):
    return 'bsfkk' if task == 'bsf' else task


@pytest.mark.parametrize('task', ['scf', 'bsf'])
@pytest.mark.parametrize('path,value', [(('MODE', 'MALF'), .25), (('TAU', 'IQCNTR'), 2),
                                      (('ENERGY', 'EMINEV'), -3.)])
def test_guided_delete_number_unsets_and_undo_restores(application, task, path, value):
    parameters = InputParameters.create(backend_task(task))
    parameters.TAU.CLUSTER.set(True)
    parameters[path[0]][path[1]].set(value)
    dialog = GuidedInputParametersDialog(task, parameters)
    editor = dialog.editors_for(path)[0]
    dialog.select_page(editor.page_id)
    toggle = dialog.form.view_for_editor(editor).detail_toggle
    if toggle is not None:
        toggle.setChecked(True)
    dialog.show()
    application.processEvents()
    assert editor.control.isEnabled()
    control = editor.control.number if isinstance(editor.control, EnergyEditor) else editor.control
    erase(control)
    dialog.navigation.setFocus()
    application.processEvents()
    assert dialog.session.value(path) is None
    if not isinstance(editor.control, EnergyEditor):
        assert editor.control.text() == 'Not set'
    else:
        # The relative value is cleared; the unified field now shows the
        # task's effective absolute default, rather than hiding that default.
        assert not editor.control.relative.isChecked()
    dialog.undo_button.click()
    application.processEvents()
    assert dialog.session.value(path) == value
    dialog.redo_button.click()
    application.processEvents()
    assert dialog.session.value(path) is None
    dialog.close()


@pytest.mark.parametrize('task', ['scf', 'bsf'])
@pytest.mark.parametrize('section,name,value', [('MODE', 'MALF', .25), ('TAU', 'IQCNTR', 2),
                                              ('TAU', 'NSHLCLU', 2),
                                              ('ENERGY', 'EMINEV', -3.)])
def test_expert_delete_number_unsets(application, task, section, name, value):
    parameters = InputParameters.create(backend_task(task))
    parameters[section][name].set(value)
    dialog = InputParametersDialog(parameters)
    tree_name = 'EMIN / EMINEV' if name == 'EMINEV' else name
    tree = dialog.tree_editor.tree
    item, = tree.findItems(tree_name, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)
    control = tree.itemWidget(item, 2)
    energy = control if isinstance(control, EnergyEditor) else None
    control = energy.number if energy else control
    dialog.show()
    tree.scrollToItem(item)
    application.processEvents()
    erase(control)
    dialog.tree_editor.filter_edit.setFocus()
    application.processEvents()
    assert dialog.parameters()[section][name]() is None
    if energy is None:
        assert (control.placeholderText() if isinstance(control, QLineEdit) else control.text()) == 'Not set'
    else:
        assert not energy.relative.isChecked()
    dialog.close()


def test_expert_nullable_numeric_editor_accepts_direct_typing_from_unset_state(application):
    parameters = InputParameters.create('scf')
    parameters.MODE.MALF.set(0.25)
    dialog = InputParametersDialog(parameters)
    tree = dialog.tree_editor.tree
    item, = tree.findItems('MALF', Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)
    control = tree.itemWidget(item, 2)

    control.setValue(control.minimum())
    control.setFocus()
    application.processEvents()
    assert control.text() == 'Not set'

    QTest.keyClicks(control, '1')
    application.processEvents()

    assert control.text() != 'Not set'
    assert control.value() == 1.0
    assert dialog.parameters().MODE.MALF() == 1.0
    dialog.close()


def test_expert_required_text_cannot_silently_become_unset(application):
    parameters = InputParameters.create('scf')
    parameters.CONTROL.POTFIL.set('Fe.pot')
    dialog = InputParametersDialog(parameters)
    tree = dialog.tree_editor.tree
    item, = tree.findItems('POTFIL', Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)
    control = tree.itemWidget(item, 2)
    control.clear()
    control.editingFinished.emit()
    assert dialog.parameters().CONTROL.POTFIL() == 'Fe.pot'
    assert 'must have a value' in control.toolTip()
    assert control.text() == ''
    dialog.close()


def test_expert_site_text_uses_input_grammar(application):
    dialog = InputParametersDialog(InputParameters.create('scf'))
    tree = dialog.tree_editor.tree
    item, = tree.findItems(
        'IQCNTR',
        Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive,
        0,
    )
    control = tree.itemWidget(item, 2)

    control.setText('3')
    control.editingFinished.emit()

    assert dialog.parameters().TAU.IQCNTR() == 3
    assert not dialog.tree_editor.error_text
    dialog.close()


def test_expert_empty_optional_array_unsets(application):
    parameters = InputParameters.create('scf')
    parameters.MODE.OP.set('LDA+U')
    parameters.MODE.LOPT.set(['d'])
    dialog = InputParametersDialog(parameters)
    tree = dialog.tree_editor.tree
    item, = tree.findItems('LOPT', Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)
    control = tree.itemWidget(item, 2)
    control.clear()
    control.editingFinished.emit()
    assert dialog.parameters().MODE.LOPT() is None
    dialog.close()
