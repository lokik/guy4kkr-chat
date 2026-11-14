import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/ase2sprkkr_gui-test-matplotlib')

from io import StringIO
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.widgets.input_parameters.energy import EnergyEditor
from ase2sprkkr_gui.gui.input_parameters.energy import convert_energy
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def _parameters_for_guided_task(task):
    return InputParameters.create('bsfkk' if task == 'bsf' else task)


@pytest.mark.parametrize('task', ['scf', 'bsf', 'dos', 'arpes'])
def test_open_energy_pair_does_not_change_parameters(application, task):
    parameters = _parameters_for_guided_task(task)
    dialog = GuidedInputParametersDialog(task, parameters)
    absolute = dialog.editors_for(('ENERGY', 'EMIN'))
    relative = dialog.editors_for(('ENERGY', 'EMINEV'))
    assert absolute == relative
    assert isinstance(absolute[0].control, EnergyEditor)
    assert not dialog.session.is_modified()
    assert dialog.session.undo_stack.count() == 0
    assert absolute[0].control.relative.isChecked() == (task == 'arpes')
    assert absolute[0].control.relative.isEnabled() == (task != 'scf')
    dialog.close()


@pytest.mark.parametrize('task', ['scf', 'bsf', 'dos'])
def test_unit_change_only_converts_display_with_full_precision(application, task):
    parameters = _parameters_for_guided_task(task)
    value = -.2345678912345
    parameters.ENERGY.EMIN.set(value)
    dialog = GuidedInputParametersDialog(task, parameters)
    editor = dialog.editors_for(('ENERGY', 'EMIN'))[-1].control
    for _ in range(3):
        editor.units.setCurrentText('eV')
        assert editor.number.value() == pytest.approx(convert_energy(value, 'Ry', 'eV'))
        assert editor.commit()
        editor.units.setCurrentText('Ry')
        assert editor.commit()
    assert dialog.session.value(('ENERGY', 'EMIN')) == value
    assert dialog.session.undo_stack.count() == 0
    assert not dialog.session.is_modified()
    dialog.close()


@pytest.mark.parametrize('unit', ['Ry', 'eV'])
@pytest.mark.parametrize('relative', [False, True])
def test_all_unit_reference_combinations_roundtrip(application, unit, relative):
    parameters = InputParameters.create('dos')
    parameters.CONTROL.POTFIL.set('Fe.pot')
    dialog = GuidedInputParametersDialog('dos', parameters)
    editor = dialog.editors_for(('ENERGY', 'EMIN'))[-1].control
    editor.units.setCurrentText(unit)
    editor.relative.setChecked(relative)
    editor.number.setValue(-.3)
    assert editor.commit()
    current = dialog.session.result()
    target = 'EMINEV' if relative else 'EMIN'
    other = 'EMIN' if relative else 'EMINEV'
    expected = convert_energy(-.3, unit, 'eV' if relative else 'Ry')
    assert current.ENERGY[target]() == pytest.approx(expected)
    assert current.ENERGY[other]() is None
    source = current.to_string(validate=False)
    loaded = InputParameters.create('dos')
    loaded.read_from_file(StringIO(source))
    assert loaded.ENERGY[target]() == pytest.approx(expected)
    assert loaded.ENERGY[other]() is None
    dialog.close()


def test_reference_change_is_atomic_undoable_and_mirrored(application):
    parameters = InputParameters.create('bsfkk')
    parameters.ENERGY.EMIN.set(.5)
    dialog = GuidedInputParametersDialog('bsf', parameters)
    quick, detail = dialog.editors_for(('ENERGY', 'EMIN'))
    quick.control.relative.setChecked(True)
    assert dialog.session.undo_stack.count() == 1
    assert dialog.session.value(('ENERGY', 'EMIN')) is None
    assert dialog.session.value(('ENERGY', 'EMINEV')) == pytest.approx(convert_energy(.5, 'Ry', 'eV'))
    assert detail.control.relative.isChecked()
    dialog.undo_button.click()
    application.processEvents()
    assert not quick.control.relative.isChecked()
    assert not detail.control.relative.isChecked()
    assert dialog.session.value(('ENERGY', 'EMIN')) == .5
    assert not dialog.session.is_modified()
    dialog.redo_button.click()
    application.processEvents()
    assert detail.control.relative.isChecked()
    dialog.close()


def test_imaginary_energy_has_units_without_relative_checkbox(application):
    dialog = GuidedInputParametersDialog('scf', InputParameters.create('scf'))
    editor = dialog.editors_for(('ENERGY', 'ImE'))[0].control
    assert isinstance(editor, EnergyEditor)
    assert editor.relative.isHidden()
    editor.units.setCurrentText('eV')
    editor.number.setValue(.02)
    assert editor.commit()
    assert float(dialog.session.value(('ENERGY', 'ImE')).to_value('eV')) == pytest.approx(.02)
    dialog.close()


def test_expert_combines_pair_and_uses_identical_control(application):
    parameters = InputParameters.create('dos')
    dialog = InputParametersDialog(parameters)
    flags = Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive
    tree = dialog.tree_editor.tree
    item, = tree.findItems('EMIN / EMINEV', flags, 0)
    assert not tree.findItems('EMINEV', flags, 0)
    editor = tree.itemWidget(item, 2)
    assert isinstance(editor, EnergyEditor)
    editor.relative.setChecked(True)
    editor.units.setCurrentText('eV')
    editor.number.setValue(-5.)
    assert editor.commit()
    assert dialog.parameters().ENERGY.EMINEV() == -5.
    assert dialog.parameters().ENERGY.EMIN() is None
    application.processEvents()
    assert item.font(0).bold()
    editor.relative.setChecked(False)
    assert dialog.parameters().ENERGY.EMIN() == pytest.approx(convert_energy(-5., 'eV', 'Ry'))
    assert dialog.parameters().ENERGY.EMINEV() is None
    dialog.close()


@pytest.mark.parametrize('expert', [False, True])
def test_arpes_absolute_bounds_and_relative_defaults(application, expert):
    parameters = InputParameters.create('arpes')
    parameters.CONTROL.POTFIL.set('Fe.pot')
    if expert:
        dialog = InputParametersDialog(parameters)
        flags = Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive
        def editor_for(name):
            tree = dialog.tree_editor.tree
            item, = tree.findItems(f'{name} / {name}EV', flags, 0)
            return tree.itemWidget(item, 2)
        current = dialog.parameters
    else:
        dialog = GuidedInputParametersDialog('arpes', parameters)
        editor_for = lambda name: dialog.editors_for(('ENERGY', name))[-1].control
        current = lambda: dialog.session.working_parameters
    for name, value in [('EMIN', .2), ('EMAX', .8)]:
        editor = editor_for(name)
        assert editor.relative.isEnabled()
        editor.relative.setChecked(False)
        editor.units.setCurrentText('Ry')
        editor.number.setValue(value)
        assert editor.commit()
        assert current().ENERGY[name]() == pytest.approx(value)
        assert current().ENERGY[name + 'EV']() is None
    source = current().to_string(validate=True)
    assert 'EMINEV=' not in source
    assert 'EMAXEV=' not in source
    if not expert:
        while dialog.session.undo_stack.canUndo():
            dialog.session.undo_stack.undo()
        assert not dialog.session.is_modified()
        assert current().ENERGY.EMINEV() == -8.
        assert current().ENERGY.EMAXEV() == 5.
        for name in ('EMIN', 'EMAX'):
            assert editor_for(name).relative.isChecked()
            assert editor_for(name).relative.isEnabled()
        while dialog.session.undo_stack.canRedo():
            dialog.session.undo_stack.redo()
        assert current().ENERGY.EMIN() == pytest.approx(.2)
        assert current().ENERGY.EMAX() == pytest.approx(.8)
    dialog.close()


def test_bsf_relative_kk_import_can_switch_to_ek_and_edit_both_references(application):
    parameters = InputParameters.create('bsfkk')
    parameters.ENERGY.EMINEV.set(0.)
    dialog = GuidedInputParametersDialog('bsf', parameters)
    mode = dialog.editors_for(('ENERGY', 'NE'))[0]
    mode.control.mode_combo.setCurrentIndex(mode.control.mode_combo.findData('EK'))
    for name in ('EMIN', 'EMAX'):
        editor = dialog.editors_for(('ENERGY', name))[-1].control
        assert editor.relative.isEnabled()
        editor.relative.setChecked(True)
        assert dialog.session.value(('ENERGY', name)) is None
        assert dialog.session.value(('ENERGY', name + 'EV')) is not None
    dialog.close()
