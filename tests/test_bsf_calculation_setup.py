import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import numpy as np
import pytest
from ase import Atoms
from ase.build import bulk as build_bulk
from PyQt6.QtWidgets import QApplication
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from ase2sprkkr.input_parameters.definitions.bsf import bsf_mode
from ase2sprkkr.sprkkr.build import semiinfinite_system

from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def ek_parameters():
    parameters = InputParameters.create("bsfek")
    parameters.set({"ENERGY": {"NE": [200], "EMIN": -.2, "EMAX": 1.}, "TASK": {
        "NK": 250, "KA": [[0., 0., 0.], [.5, 0., 0.]],
        "KE": [[.5, 0., 0.], [.5, .5, 0.]],
    }})
    return parameters


def kk_parameters():
    parameters = InputParameters.create("bsfkk")
    parameters.set({"ENERGY": {"EMINEV": 0.}, "TASK": {
        "KA": [[.1, .2, .3]], "K1": [1., 0., 0.], "K2": [0., 1., 0.],
        "NK1": 45, "NK2": 55,
    }})
    return parameters


@pytest.mark.parametrize("selected", [False, True])
def test_kpath_editor_parent_and_atomic_history(application, monkeypatch, selected):
    import ase2sprkkr.gui.k_path as k_path_module

    atoms = Atoms("Fe", cell=[2.8, 2.8, 2.8], pbc=True)
    original = ek_parameters()
    dialog = GuidedInputParametersDialog("bsf", original, atoms=atoms)
    editor = dialog.editors_for(("TASK", "KPATH"))[0]
    calls = []
    result = {"NKDIR": 1, "NK": 42, "KA": [[0., 0., 0.]], "KE": [[0., .5, .5]]}

    def select_path(structure, *, parent):
        calls.append((structure, parent))
        return result if selected else None

    monkeypatch.setattr(k_path_module, "k_path_gui", select_path)
    editor.control.path_edit.click()
    assert len(calls) == 1 and calls[0][0] is atoms and calls[0][1] is dialog
    assert dialog.session.undo_stack.count() == int(selected)
    if selected:
        np.testing.assert_array_equal(dialog.session.value(("TASK", "KE")), result["KE"])
        assert dialog.session.value(("TASK", "NK")) == 42
        dialog.session.undo_stack.undo()
        assert not dialog.session.is_modified()
        np.testing.assert_array_equal(dialog.session.value(("TASK", "KE")), original.TASK.KE())
        dialog.session.undo_stack.redo()
        np.testing.assert_array_equal(dialog.session.value(("TASK", "KE")), result["KE"])
    else:
        assert not dialog.session.is_modified()
    # The original parameters are never modified by the guided editor.
    assert original.TASK.NK() == 250
    dialog.close()


def switch(dialog, mode):
    editor = dialog.editors_for(("ENERGY", "NE"))[0]
    editor.control.mode_combo.setCurrentIndex(editor.control.mode_combo.findData(mode))
    assert not editor._error
    return editor


@pytest.mark.parametrize("factory, expected_mode", [(ek_parameters, "EK"), (kk_parameters, "KK")])
def test_import_preserves_bsf_geometry_and_mode(application, factory, expected_mode):
    parameters = factory()
    dialog = GuidedInputParametersDialog("bsf", parameters)
    assert bsf_mode(dialog.session.working_parameters) == expected_mode
    np.testing.assert_array_equal(dialog.session.value(("TASK", "KA")), parameters.TASK.KA())
    assert dialog.session.value(("TASK", "KPATH")) is None
    assert not dialog.session.is_modified()
    assert dialog._commit_pending()
    dialog.close()


def test_alias_energy_default_is_preserved_when_canonicalising(application):
    parameters = InputParameters.create("bsfek")
    parameters.TASK.KPATH.set(6)
    dialog = GuidedInputParametersDialog("bsf", parameters)
    assert dialog.session.value(("ENERGY", "NE"))[0] == 200
    assert bsf_mode(dialog.session.working_parameters) == "EK"
    assert dialog.session.value(("TASK", "KPATH")) == "6"
    dialog.close()


def test_mode_switch_is_atomic_and_undo_restores_custom_segments(application):
    parameters = ek_parameters()
    dialog = GuidedInputParametersDialog("bsf", parameters)
    switch(dialog, "KK")
    assert dialog.session.undo_stack.count() == 1
    current = dialog.session.working_parameters
    assert bsf_mode(current) == "KK"
    assert current.ENERGY.NE()[0] == 1
    assert current.ENERGY.EMIN() == 1.
    assert current.ENERGY.EMAX() == 1.
    assert current.TASK.NK1() == current.TASK.NK2() == 60
    for name in ("KPATH", "NK", "KE"):
        assert not current.TASK[name].is_set()
    current.validate(why="set")
    dialog.session.undo_stack.undo()
    application.processEvents()
    assert not dialog.session.is_modified()
    np.testing.assert_array_equal(dialog.session.value(("TASK", "KA")), parameters.TASK.KA())
    np.testing.assert_array_equal(dialog.session.value(("TASK", "KE")), parameters.TASK.KE())
    dialog.session.undo_stack.redo()
    application.processEvents()
    assert bsf_mode(dialog.session.working_parameters) == "KK"
    switch(dialog, "EK")
    current = dialog.session.working_parameters
    assert current.TASK.KPATH() == "1"
    for name in ("NK1", "NK2", "K1", "K2"):
        assert not current.TASK[name].is_set()
    current.validate(why="set")
    dialog.close()


def test_custom_path_and_plane_origin_editors(application):
    dialog = GuidedInputParametersDialog("bsf", kk_parameters())
    origin, = dialog.editors_for(("TASK", "KA"))
    assert origin.control._rows() == [[.1, .2, .3]]
    from PyQt6.QtWidgets import QApplication
    QApplication.clipboard().setText("0.4\t0.5\t0.6")
    origin.control.paste()
    np.testing.assert_array_equal(dialog.session.value(origin.path), [[.4, .5, .6]])
    switch(dialog, "EK")
    path = dialog.editors_for(("TASK", "KPATH"))[-1]
    combo = path.control.path_combo
    assert {combo.itemData(i) for i in range(combo.count())} == {
        None, "0", "1", "2", "3", "4", "5", "6", "7", "10",
    }
    combo.setCurrentIndex(combo.findData(None))
    assert not path._error
    assert dialog.session.value(path.path) is None
    assert origin.control._rows()[0][:3] == [0., 0., 0.]
    assert dialog.session.value(("TASK", "KE")) is not None
    dialog.close()


def test_mode_controls_visibility_and_mirrors_follow_undo(application):
    dialog = GuidedInputParametersDialog("bsf", ek_parameters())
    dialog.show()
    application.processEvents()
    quick, detail = [e for e in dialog.editors_for(("ENERGY", "NE"))
                     if e.placement.editor == "bsf_mesh"]
    assert not dialog.editors_for(("TASK", "KPATH"))[0].isHidden()
    assert dialog.editors_for(("TASK", "NK1"))[0].isHidden()
    switch(dialog, "KK")
    assert detail.control.mode_combo.currentData() == "KK"
    assert not quick.control.energy_count.isEnabled()
    assert dialog.editors_for(("TASK", "KPATH"))[0].isHidden()
    assert not dialog.editors_for(("TASK", "NK1"))[0].isHidden()
    assert dialog.editors_for(("ENERGY", "EMAX"))[0].isHidden()
    dialog.select_page("output")
    dialog.undo_button.click()
    application.processEvents()
    assert quick.control.mode_combo.currentData() == detail.control.mode_combo.currentData() == "EK"
    assert quick.control.mode_combo.hasFocus()
    assert not dialog.editors_for(("ENERGY", "EMAX"))[0].isHidden()
    dialog.close()


@pytest.mark.parametrize("factory", [ek_parameters, kk_parameters])
def test_bsf_serializes_and_reloads_without_wrong_mode_keywords(application, factory, tmp_path):
    dialog = GuidedInputParametersDialog("bsf", factory())
    for mode in ("EK", "KK"):
        switch(dialog, mode)
        result = dialog.session.result()
        result.CONTROL.POTFIL.set("Fe.pot")
        result.validate(why="save")
        filename = tmp_path / f"Fe_BSF_{mode}.inp"
        result.save_to_file(str(filename))
        text = filename.read_text()
        loaded = InputParameters.from_file(str(filename))
        assert bsf_mode(loaded) == mode
        if mode == "KK":
            assert "NK1=" in text and "NK2=" in text and "K1=" in text and "K2=" in text
            assert "KPATH=" not in text and "NKDIR=" not in text and "KE1=" not in text
            assert "KA=" in text and "KA1=" not in text
        else:
            assert "NK1=" not in text and "K1=" not in text
            assert "KPATH=" in text or ("KA1=" in text and "KE1=" in text)
    dialog.close()


def test_relative_fixed_energy_and_missing_geometry_validation(application):
    dialog = GuidedInputParametersDialog("bsf", InputParameters.create("bsfkk"))
    assert not dialog._commit_pending()
    assert ("TASK", "K1") in dialog.form.errors
    dialog.session.replace_parameters(kk_parameters())
    assert dialog._commit_pending()
    energy = dialog.editors_for(("ENERGY", "EMINEV"))[-1]
    energy.control.units.setCurrentText("eV")
    energy.control.number.setValue(.25)
    assert energy.commit()
    current = dialog.session.working_parameters
    assert current.ENERGY.EMINEV() == current.ENERGY.EMAXEV() == .25
    assert current.ENERGY.EMIN() is None
    dialog.close()


def test_bsf_bulk_and_layered_integration_fields(application):
    bulk = Atoms("Fe", cell=(2.8, 2.8, 8.), pbc=True)
    layered = semiinfinite_system(build_bulk("Fe", "bcc", a=2.8), (0, 0))
    for atoms, expected in [(bulk, "NKTAB"), (layered, "NKTAB2D")]:
        dialog = GuidedInputParametersDialog("bsf", kk_parameters(), atoms=atoms)
        assert dialog.editors_for(("TAU", expected))
        dialog.close()


def test_kpath_choices_use_type_metadata_without_probing_values(application, monkeypatch):
    import ase2sprkkr_gui.gui.widgets.input_parameters.bsf as editors

    def unexpected_mode_switch(*args):
        pytest.fail("Building the KPATH menu must not probe choices by changing BSF mode")

    monkeypatch.setattr(editors, "set_energy_points", unexpected_mode_switch)
    dialog = GuidedInputParametersDialog("bsf", kk_parameters())
    option = dialog.session.option(("TASK", "KPATH"))
    expected = {option._definition.type.convert(value) for value, _ in option._definition.type.items()}
    for editor in dialog.editors_for(("TASK", "KPATH")):
        combo = editor.control.path_combo
        assert {combo.itemData(i) for i in range(1, combo.count())} == expected
    assert not dialog.session.is_modified()
    assert bsf_mode(dialog.session.working_parameters) == "KK"
    dialog.close()


@pytest.mark.parametrize("path", ["6", "7", "10"])
def test_keyword_path_selection_roundtrip_and_undo(application, path, tmp_path):
    dialog = GuidedInputParametersDialog("bsf", ek_parameters())
    quick, primary = dialog.editors_for(("TASK", "KPATH"))
    quick.control.path_combo.setCurrentIndex(quick.control.path_combo.findData(path))
    assert not quick._error
    assert primary.control.path_combo.currentData() == path
    result = dialog.session.result()
    result.CONTROL.POTFIL.set("Fe.pot")
    filename = tmp_path / "Fe_BSF.inp"
    result.save_to_file(str(filename))
    assert InputParameters.from_file(str(filename)).TASK.KPATH() == path
    dialog.session.undo_stack.undo()
    application.processEvents()
    assert quick.control.path_combo.currentData() is None
    assert not dialog.session.is_modified()
    dialog.session.undo_stack.redo()
    application.processEvents()
    assert primary.control.path_combo.currentData() == path
    dialog.close()


def test_bsf_xband_groups_and_quick_sampling(application):
    dialog = GuidedInputParametersDialog("bsf", ek_parameters())
    assert [page.id for page in dialog.spec.pages] == ["quick", "energy", "path", "physical", "kkr", "output"]
    primary = dialog.spec.primary_pages()
    assert primary[("MODE", "MODE")] == primary[("CONTROL", "NONMAG")] == "physical"
    assert primary[("CPA", "NITER")] == primary[("STRCONST", "ETA")] == "kkr"
    quick, detail = dialog.editors_for(("TASK", "NK"))
    quick.control.setValue(321)
    assert quick.commit()
    assert detail.control.value() == 321
    dialog.session.undo_stack.undo()
    assert detail.control.value() == 250
    assert dialog.session.value(("ENERGY", "NE"))[0] == 200
    dialog.close()


def test_bsf_dependencies_follow_model_and_kkr_choices(application):
    dialog = GuidedInputParametersDialog("bsf", ek_parameters())

    def enabled(section, name):
        return dialog.editors_for((section, name))[0].control.isEnabled()

    def set_value(section, name, value):
        dialog.session.set_value((section, name), value)

    assert enabled("STRCONST", "ETA") and not enabled("TAU", "CLURAD")
    set_value("TAU", "KKRMODE", "TB")
    assert enabled("TAU", "NSHLCLU") and not enabled("STRCONST", "ETA")
    set_value("TAU", "BZINT", "WEYL")
    assert enabled("TAU", "NKMIN") and not enabled("TAU", "NKTAB")
    set_value("TAU", "CLUSTER", True)
    assert enabled("TAU", "IQCNTR") and not enabled("TAU", "NKMIN")
    assert not enabled("TAU", "BZINT")
    set_value("CONTROL", "NONMAG", True)
    assert not enabled("MODE", "MDIR")
    set_value("MODE", "OP", "LDA+U")
    assert enabled("MODE", "LOPT") and enabled("MODE", "UEFF")
    set_value("MODE", "IEREF", -1)
    assert enabled("MODE", "EREF")
    set_value("MODE", "OP", "NONE")
    assert not enabled("MODE", "UEFF") and not enabled("MODE", "EREF")
    dialog.close()


@pytest.mark.parametrize("flag", [("CONTROL", "FSOHFF"), ("CONTROL", "SPLITSS"), ("ENERGY", "SPLITSS")])
def test_bsf_single_site_mesh_edits_preserve_mode_and_other_mesh(application, flag):
    dialog = GuidedInputParametersDialog("bsf", ek_parameters())
    secondary_ne = next(e for e in dialog.editors_for(("ENERGY", "NE")) if e.placement.index == 1)
    secondary_grid = next(e for e in dialog.editors_for(("ENERGY", "GRID")) if e.placement.index == 1)
    assert not secondary_ne.control.isEnabled()
    switch_flag, = dialog.editors_for(flag)
    switch_flag.control.setChecked(True)
    assert list(dialog.session.value(("ENERGY", "NE"))) == [200, 200]
    assert secondary_ne.control.isEnabled() and secondary_grid.control.isEnabled()
    secondary_ne.control.setValue(32)
    assert secondary_ne.commit()
    secondary_grid.control.setCurrentIndex(secondary_grid.control.findData("5"))
    assert list(dialog.session.value(("ENERGY", "NE"))) == [200, 32]
    assert list(dialog.session.value(("ENERGY", "GRID"))) == ["3", "5"]
    switch(dialog, "KK")
    assert list(dialog.session.value(("ENERGY", "NE"))) == [1, 32]
    assert list(dialog.session.value(("ENERGY", "GRID"))) == ["3", "5"]
    switch(dialog, "EK")
    assert list(dialog.session.value(("ENERGY", "NE"))) == [200, 32]
    dialog.close()


def test_bsf_vector_cells_and_cpa_roundtrip(application, tmp_path):
    from PyQt6.QtWidgets import QLineEdit

    dialog = GuidedInputParametersDialog("bsf", kk_parameters())
    vector = dialog.editors_for(("TASK", "K1"))[0].control
    index = vector.table.model().index(0, 1)
    editor = QLineEdit()
    editor.setText("1/2")
    vector.delegate.setModelData(editor, vector.table.model(), index)
    np.testing.assert_array_equal(dialog.session.value(("TASK", "K1")), [1., .5, 0.])
    dialog.session.undo_stack.undo()
    np.testing.assert_array_equal(dialog.session.value(("TASK", "K1")), [1., 0., 0.])
    dialog.session.undo_stack.redo()
    cpa = dialog.editors_for(("CPA", "NITER"))[0]
    cpa.control.setValue(40)
    assert cpa.commit()
    tolerance = dialog.editors_for(("CPA", "TOL"))[0]
    tolerance.control.setValue(1e-6)
    assert tolerance.commit()
    parameters = dialog.session.result()
    parameters.CONTROL.POTFIL.set("Fe.pot")
    filename = tmp_path / "Fe_BSF.inp"
    parameters.save_to_file(str(filename))
    loaded = InputParameters.from_file(str(filename))
    assert loaded.CPA.NITER() == 40 and loaded.CPA.TOL() == 1e-6
    np.testing.assert_array_equal(loaded.TASK.K1(), [1., .5, 0.])
    assert dialog._commit_pending()
    dialog.close()


def test_bsf_plane_vectors_keep_invalid_drafts_and_report_required_unset(application):
    from PyQt6.QtCore import Qt
    dialog = GuidedInputParametersDialog("bsf", kk_parameters())
    vector = dialog.editors_for(("TASK", "K1"))[0].control
    vector.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, "bad")
    assert not dialog.session.is_modified()
    assert not dialog._commit_pending()
    vector.table.item(0, 0).setData(Qt.ItemDataRole.EditRole, "1/2")
    assert dialog._commit_pending()
    for column in range(3):
        vector.table.item(0, column).setData(Qt.ItemDataRole.EditRole, "")
    assert dialog.session.value(("TASK", "K1")) is None
    assert not dialog._commit_pending()
    assert ("TASK", "K1") in dialog.form.errors
    dialog.session.undo_stack.undo()
    assert dialog._commit_pending()
    dialog.close()
