import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

import numpy as np
import pytest
from ase import Atoms
from ase.build import bulk
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QSpinBox, QComboBox

from ase2sprkkr.input_parameters.input_parameters import InputParameters
from ase2sprkkr.sprkkr.build import semiinfinite_system

from guy4ase.gui.dialogs.guided_input import GuidedInputParametersDialog
from guy4ase.gui.input_parameters.session import InputParametersSession
from guy4ase.gui.input_parameters.single_site_contour import SingleSiteContourPlugin
from guy4ase.gui.input_parameters.specs.schema import FieldRole
from guy4ase.gui.input_parameters.tasks import (
    guided_task_definition,
    guided_task_definitions,
)


def _first(value):
    return value.flat[0] if isinstance(value, np.ndarray) else value


def _backend_task(task):
    return "bsfkk" if task == "bsf" else task


def _contour_session(task):
    return InputParametersSession(
        InputParameters.create(_backend_task(task)),
        plugins=(SingleSiteContourPlugin(),),
    )


def test_session_undo_redo_and_content_based_modified_state():
    application = QApplication.instance() or QApplication([])
    session = InputParametersSession(InputParameters.create("dos"))
    path = ("ENERGY", "NE")
    initial = int(_first(session.value(path)))

    assert session.set_value(path, initial + 10, source_page="energy")
    assert session.is_modified()
    assert session.undo_stack.canUndo()
    assert int(_first(session.value(path))) == initial + 10

    session.undo_stack.undo()
    assert not session.is_modified()
    assert int(_first(session.value(path))) == initial

    session.undo_stack.redo()
    assert session.is_modified()
    assert int(_first(session.value(path))) == initial + 10

    # Returning manually to the initial content leaves useful history but the
    # resulting document is no longer modified.
    session.set_value(path, initial, source_page="energy")
    assert not session.is_modified()
    assert session.undo_stack.canUndo()
    application.processEvents()


def test_replacement_is_one_atomic_command_and_failed_edit_is_not_recorded():
    application = QApplication.instance() or QApplication([])
    session = InputParametersSession(InputParameters.create("dos"))
    original_ne = int(_first(session.value(("ENERGY", "NE"))))
    original_nktab = session.value(("TAU", "NKTAB"))

    candidate = session.result()
    candidate.ENERGY.NE.set(original_ne + 5)
    candidate.TAU.NKTAB.set(original_nktab + 50)
    assert session.replace_parameters(candidate, text="Apply expert settings", source_page="expert")
    assert session.undo_stack.count() == 1

    session.undo_stack.undo()
    assert int(_first(session.value(("ENERGY", "NE")))) == original_ne
    assert session.value(("TAU", "NKTAB")) == original_nktab

    count = session.undo_stack.count()
    with pytest.raises(Exception):
        session.set_value(("ENERGY", "NE"), "not-an-integer", source_page="energy")
    assert session.undo_stack.count() == count
    assert int(_first(session.value(("ENERGY", "NE")))) == original_ne
    application.processEvents()


def test_quick_mirror_and_primary_editor_stay_synchronised_through_undo():
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog(
        "dos",
        InputParameters.create("dos"),
        atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
    )
    path = ("ENERGY", "NE")
    quick, primary = dialog.editors_for(path)
    assert quick.page_id == "quick"
    assert primary.page_id == "energy"
    assert isinstance(quick.control, QSpinBox)

    original = primary.control.value()
    quick.control.setValue(original + 25)
    quick.control.editingFinished.emit()
    application.processEvents()

    assert primary.control.value() == original + 25
    assert int(_first(dialog.session.value(path))) == original + 25

    dialog.session.undo_stack.undo()
    application.processEvents()
    assert quick.control.value() == original
    assert primary.control.value() == original

    dialog.close()


def test_every_mirror_has_one_primary_location():
    for definition in guided_task_definitions():
        for is_2d in (False, True):
            spec = definition.build_spec(is_2d=is_2d)
            primary = spec.primary_pages()
            mirrors = [
                field.path
                for page in spec.pages
                for group in page.groups
                for field in group.fields
                if field.role is FieldRole.MIRROR
            ]
            assert mirrors
            assert all(path in primary for path in mirrors)


def test_finishing_untouched_dialog_does_not_commit_visual_fallbacks():
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog(
        "scf",
        InputParameters.create("scf"),
        atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
    )

    assert dialog.session.value(("SCF", "QIONSCL")) is None
    assert dialog._commit_pending()
    assert dialog.session.value(("SCF", "QIONSCL")) is None
    assert not dialog.session.is_modified()

    dialog.close()
    application.processEvents()


def test_scf_accuracy_page_does_not_treat_plain_slab_as_layered_2d():
    application = QApplication.instance() or QApplication([])
    atoms = Atoms("Fe", cell=(2.8, 2.8, 12.0), pbc=(True, True, False))
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"), atoms=atoms)

    assert dialog.editors_for(("TAU", "NKTAB"))
    assert not dialog.editors_for(("TAU", "NKTAB2D"))
    assert not dialog.editors_for(("TAU", "NKTAB3D"))

    dialog.close()
    application.processEvents()


def test_scf_accuracy_page_uses_2d_kpoint_controls_for_layered_structure():
    application = QApplication.instance() or QApplication([])
    atoms = semiinfinite_system(bulk("Cu", "sc", a=2.0), (0, 0))
    dialog = GuidedInputParametersDialog(
        "scf", InputParameters.create("scf"), atoms=atoms
    )

    assert dialog.editors_for(("TAU", "NKTAB2D"))
    assert dialog.editors_for(("TAU", "NKTAB3D"))
    assert not dialog.editors_for(("TAU", "NKTAB"))

    dialog.close()
    application.processEvents()


def test_scf_spec_covers_xband_and_common_input_groups():
    spec = guided_task_definition("scf").build_spec()
    paths = set(spec.all_paths())

    assert len(paths) >= 60
    assert {
        ("CONTROL", "KRWS"),
        ("SCF", "MIXOP"),
        ("SCF", "QION"),
        ("SCF", "MSPIN"),
        ("CPA", "NITER"),
        ("TAU", "NKMIN"),
        ("TAU", "NSHLCLU"),
        ("ENERGY", "EMIN"),
        ("MODE", "MDIR"),
        ("MODE", "UEFF"),
        ("STRCONST", "RMAX"),
        ("CONTROL", "FSOHFF"),
    } <= paths


def test_grid_choices_come_from_keyword_and_both_meshes_survive_edits_and_undo():
    application = QApplication.instance() or QApplication([])
    parameters = InputParameters.create("scf")
    parameters.ENERGY.GRID.set([5, 3])
    parameters.ENERGY.NE.set([32, 80])
    parameters.ENERGY.SPLITSS.set(True)
    dialog = GuidedInputParametersDialog("scf", parameters)
    first, second = dialog.editors_for(("ENERGY", "GRID"))
    grammar = parameters.ENERGY.GRID._definition.type.type
    assert isinstance(first.control, QComboBox)
    assert {first.control.itemData(i) for i in range(first.control.count())} == {
        grammar.convert(key) for key, _ in grammar.items()
    }
    assert first.control.currentData() == grammar.convert(5)
    assert second.control.currentData() == grammar.convert(3)
    assert "arc" in first.control.currentText()
    first.control.setCurrentIndex(first.control.findData(grammar.convert(11)))
    assert list(dialog.session.value(first.path)) == [grammar.convert(11), grammar.convert(3)]

    quick_ne, main_ne, single_ne = dialog.editors_for(("ENERGY", "NE"))
    quick_ne.control.setValue(40)
    quick_ne.control.editingFinished.emit()
    assert list(dialog.session.value(quick_ne.path)) == [40, 80]
    assert main_ne.control.value() == 40
    single_ne.control.setValue(100)
    single_ne.control.editingFinished.emit()
    assert list(dialog.session.value(quick_ne.path)) == [40, 100]
    dialog.session.undo_stack.undo()
    assert list(dialog.session.value(quick_ne.path)) == [40, 80]
    dialog.session.undo_stack.undo()
    dialog.session.undo_stack.undo()
    assert not dialog.session.is_modified()
    dialog.close()
    application.processEvents()


@pytest.mark.parametrize("switch", [("ENERGY", "SPLITSS"), ("CONTROL", "SPLITSS"), ("CONTROL", "FSOHFF")])
def test_enabling_split_contour_is_one_undoable_edit(switch):
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    editor, = dialog.editors_for(switch)
    editor.control.setChecked(True)
    assert dialog.session.undo_stack.count() == 1
    for name in ("GRID", "NE"):
        first, second = dialog.session.value(("ENERGY", name))
        assert first == second
        assert dialog.editors_for(("ENERGY", name))[-1].control.isEnabled()
    dialog.session.undo_stack.undo()
    assert not editor.control.isChecked()
    assert len(dialog.session.value(("ENERGY", "GRID"))) == 1
    assert not dialog.session.is_modified()
    dialog.session.undo_stack.redo()
    assert len(dialog.session.value(("ENERGY", "GRID"))) == 2
    dialog.close()
    application.processEvents()


def test_krmt_zero_is_not_automatic_and_repeated_values_remain_visible():
    application = QApplication.instance() or QApplication([])
    parameters = InputParameters.create("scf")
    parameters.MODE.SOC.set({"def": 1., 2: .5})
    dialog = GuidedInputParametersDialog("scf", parameters)
    krmt, = dialog.editors_for(("CONTROL", "KRMT"))
    krmt.control.setCurrentIndex(krmt.control.findData("0"))
    assert dialog.session.value(krmt.path) == "0"
    soc, = dialog.editors_for(("MODE", "SOC"))
    assert soc.control.table.verticalHeaderItem(1).text() == "Type 2"
    assert soc.control.table.item(1, 0).text() == "0.5"
    assert dialog.session.value(soc.path) == {"def": 1., 2: .5}
    dialog.session.undo_stack.undo()
    assert krmt.control.currentData() is None
    dialog.close()
    application.processEvents()


def test_incomplete_imported_split_contour_is_reported_without_rewriting_input():
    application = QApplication.instance() or QApplication([])
    parameters = InputParameters.create("scf")
    parameters.CONTROL.FSOHFF.set(True)
    dialog = GuidedInputParametersDialog("scf", parameters)
    assert not dialog.session.is_modified()
    assert not dialog._commit_pending()
    assert dialog.navigation.currentRow() == dialog._page_indexes["energy"]
    for name in ("GRID", "NE"):
        editor = dialog.editors_for(("ENERGY", name))[-1]
        if name == "GRID":
            editor.control.setCurrentIndex(editor.control.findData("3"))
        else:
            editor.control.setValue(60)
            editor.control.editingFinished.emit()
    assert dialog._commit_pending()
    dialog.close()
    application.processEvents()


def test_kkr_controls_follow_integration_mode_without_losing_values():
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    bzint, = dialog.editors_for(("TAU", "BZINT"))
    nkmin, = dialog.editors_for(("TAU", "NKMIN"))
    nktab = dialog.editors_for(("TAU", "NKTAB"))[-1]
    original = nkmin.control.value()
    bzint.control.setCurrentIndex(bzint.control.findData("WEYL"))
    assert nkmin.control.isEnabled()
    assert not nktab.control.isEnabled()
    cluster, = dialog.editors_for(("TAU", "CLUSTER"))
    cluster.control.setChecked(True)
    assert not nkmin.control.isEnabled()
    assert dialog.editors_for(("TAU", "IQCNTR"))[0].control.isEnabled()
    dialog.session.undo_stack.undo()
    assert nkmin.control.isEnabled()
    assert nkmin.control.value() == original
    dialog.close()
    application.processEvents()


def test_history_tooltips_describe_next_change_and_its_direction():
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    assert dialog.undo_button.toolTip() == "Nothing to undo"
    assert dialog.redo_button.toolTip() == "Nothing to redo"
    editor = dialog.editors_for(("SCF", "NITER"))[0]
    initial = editor.control.value()
    for value in (initial + 10, initial + 20):
        editor.control.setValue(value)
        editor.control.editingFinished.emit()
    assert "SCF.NITER" in dialog.undo_button.toolTip()
    assert f"{initial + 20} → {initial + 10}" in dialog.undo_button.toolTip()
    dialog.undo_button.click()
    application.processEvents()
    # Both commands have the same action name, but different values.
    assert f"{initial + 10} → {initial}" in dialog.undo_button.toolTip()
    assert f"{initial + 10} → {initial + 20}" in dialog.redo_button.toolTip()
    dialog.redo_button.click()
    application.processEvents()
    assert dialog.redo_button.toolTip() == "Nothing to redo"
    dialog.close()


def test_history_returns_to_quick_mirror_and_exact_single_site_field():
    application = QApplication.instance() or QApplication([])
    parameters = InputParameters.create("scf")
    parameters.ENERGY.NE.set([32, 80])
    parameters.ENERGY.GRID.set([5, 3])
    parameters.ENERGY.SPLITSS.set(True)
    dialog = GuidedInputParametersDialog("scf", parameters)
    dialog.show()
    application.processEvents()
    quick, main, single = dialog.editors_for(("ENERGY", "NE"))
    quick.control.setValue(40)
    quick.control.editingFinished.emit()
    dialog.select_page("output")
    dialog.undo_button.click()
    application.processEvents()
    assert dialog.navigation.currentRow() == dialog._page_indexes["quick"]
    assert quick.control.hasFocus()
    dialog.redo_button.click()
    application.processEvents()
    dialog.select_page("energy")
    single.control.setValue(100)
    single.control.editingFinished.emit()
    assert "ENERGY.NE[2]: 100 → 80" in dialog.undo_button.toolTip()
    dialog.select_page("physical")
    dialog.undo_button.click()
    application.processEvents()
    assert dialog.navigation.currentRow() == dialog._page_indexes["energy"]
    assert single.control.hasFocus()
    assert main.control.value() == 40
    assert single.control.value() == 80
    dialog.select_page("quick")
    dialog.redo_button.click()
    application.processEvents()
    assert single.control.hasFocus()
    assert single.control.value() == 100
    dialog.close()


def test_history_expands_and_scrolls_to_changed_detail_without_navigating_on_edit():
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    dialog.show()
    application.processEvents()
    editor, = dialog.editors_for(("MODE", "SOC"))
    toggle = dialog.form.view_for_editor(editor).detail_toggle
    assert toggle is not None
    assert not toggle.isChecked()
    dialog.session.set_value(editor.path, .5, source_page="physical")
    application.processEvents()
    assert dialog.navigation.currentRow() == dialog._page_indexes["quick"]
    dialog.undo_button.click()
    application.processEvents()
    assert dialog.navigation.currentRow() == dialog._page_indexes["physical"]
    assert toggle.isChecked()
    assert editor.control.hasFocus()
    scroll = dialog.pages.currentWidget()
    top_left = editor.mapTo(scroll.viewport(), QPoint(0, 0))
    assert 0 <= top_left.y() < scroll.viewport().height() - editor.height()
    assert not dialog.session.is_modified()
    assert dialog.session.undo_stack.count() == 1
    dialog.close()


def test_bulk_history_describes_changes_and_finds_a_guided_field():
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    candidate = dialog.session.result()
    candidate.SCF.NITER.set(250)
    candidate.SCF.TOL.set(.001)
    dialog.session.replace_parameters(candidate, text="Apply expert settings", source_page="expert")
    assert "Apply expert settings" in dialog.undo_button.toolTip()
    assert "SCF.NITER" in dialog.undo_button.toolTip()
    assert "SCF.TOL" in dialog.undo_button.toolTip()
    dialog.session.undo_stack.undo()
    application.processEvents()
    assert dialog.navigation.currentRow() == dialog._page_indexes["convergence"]
    assert not dialog.session.is_modified()
    dialog.close()


def test_expert_history_finds_changed_array_component():
    application = QApplication.instance() or QApplication([])
    parameters = InputParameters.create("scf")
    parameters.ENERGY.NE.set([32, 80])
    parameters.ENERGY.GRID.set([5, 3])
    parameters.ENERGY.SPLITSS.set(True)
    dialog = GuidedInputParametersDialog("scf", parameters)
    dialog.show()
    application.processEvents()
    candidate = dialog.session.result()
    candidate.ENERGY.NE.set([32, 100])
    dialog.session.replace_parameters(candidate, source_page="expert")
    dialog.undo_button.click()
    application.processEvents()
    assert dialog.editors_for(("ENERGY", "NE"))[-1].control.hasFocus()
    dialog.close()


@pytest.mark.parametrize("task", ["scf", "bsf"])
@pytest.mark.parametrize("switch", [("ENERGY", "SPLITSS"), ("CONTROL", "SPLITSS"), ("CONTROL", "FSOHFF")])
def test_single_site_toggle_restores_clean_input_and_remembers_values(task, switch, tmp_path):
    application = QApplication.instance() or QApplication([])
    parameters = InputParameters.create(_backend_task(task))
    if task == "bsf":
        parameters.ENERGY.NE.set([200])
        parameters.TASK.KPATH.set(1)
    dialog = GuidedInputParametersDialog(task, parameters)
    session = dialog.session
    flag = dialog.editors_for(switch)[0].control
    main_grid, ss_grid = dialog.editors_for(("ENERGY", "GRID"))
    ss_ne = dialog.editors_for(("ENERGY", "NE"))[-1]
    flag.setChecked(True)
    flag.setChecked(False)
    assert not session.is_modified()
    assert not session.is_changed(("ENERGY", "GRID"))
    assert not session.is_changed(("ENERGY", "NE"))
    assert not ss_grid.control.isEnabled()
    flag.setChecked(True)
    ss_grid.control.setCurrentIndex(ss_grid.control.findData("3"))
    ss_ne.control.setValue(87)
    assert ss_ne.commit()
    flag.setChecked(False)
    assert not session.is_modified()
    assert ss_grid.control.currentData() == "3"
    assert ss_ne.control.value() == 87
    assert len(session.result().ENERGY.GRID()) == len(session.result().ENERGY.NE()) == 1
    assert not ss_ne.control.isEnabled()
    # Focus loss from a newly disabled field must not recreate the second mesh.
    ss_ne.control.editingFinished.emit()
    assert not session.is_modified()
    saved = session.result()
    saved.CONTROL.POTFIL.set("Fe.pot")
    filename = tmp_path / f"{task}.inp"
    saved.save_to_file(str(filename))
    loaded = InputParameters.from_file(str(filename))
    assert len(loaded.ENERGY.GRID()) == len(loaded.ENERGY.NE()) == 1
    session.undo_stack.undo()
    assert flag.isChecked() and ss_ne.control.isEnabled()
    assert list(session.value(("ENERGY", "NE")))[1] == 87
    session.undo_stack.redo()
    assert not flag.isChecked() and not session.is_modified()
    # Main mesh edits while disabled do not overwrite remembered SS settings.
    main_grid.control.setCurrentIndex(main_grid.control.findData("8"))
    flag.setChecked(True)
    assert list(session.value(("ENERGY", "GRID"))) == ["8", "3"]
    assert list(session.value(("ENERGY", "NE")))[1] == 87
    assert ss_ne.control.isEnabled()
    dialog.close()
    application.processEvents()


@pytest.mark.parametrize("task", ["scf", "bsf"])
def test_single_site_history_branch_does_not_reuse_future_cache(task):
    application = QApplication.instance() or QApplication([])
    session = _contour_session(task)
    flag = ("ENERGY", "SPLITSS")
    ne = ("ENERGY", "NE")
    original = int(session.value(ne)[0])
    session.set_value(flag, True)
    session.set_value(ne, [original, 87])
    session.set_value(flag, False)
    assert session.display_value(ne, 1) == 87
    for _ in range(3):
        session.undo_stack.undo()
    assert not session.is_modified()
    assert session.display_value(ne, 1) is None
    session.set_value(flag, True)
    assert list(session.value(ne)) == [original, original]
    assert not session.undo_stack.canRedo()
    application.processEvents()


@pytest.mark.parametrize("task", ["scf", "bsf"])
def test_forced_single_site_contour_stays_active_until_last_flag_is_off(task):
    application = QApplication.instance() or QApplication([])
    session = _contour_session(task)
    flag, force = ("ENERGY", "SPLITSS"), ("CONTROL", "FSOHFF")
    session.set_value(flag, True)
    session.set_value(force, True)
    session.set_value(flag, False)
    assert len(session.value(("ENERGY", "GRID"))) == 2
    candidate = session.result()
    candidate.CONTROL.FSOHFF.set(False)
    session.replace_parameters(candidate, text="Apply expert settings")
    assert len(session.value(("ENERGY", "GRID"))) == 1
    assert not session.is_modified()
    session.undo_stack.undo()
    assert len(session.value(("ENERGY", "GRID"))) == 2
    application.processEvents()


def test_requested_task_provenance_does_not_force_single_site_contour(monkeypatch):
    parameters = InputParameters.create("scf")
    parameters.ENERGY.SPLITSS.set(True)
    parameters.ENERGY.GRID.set([5, 3])
    parameters.ENERGY.NE.set([32, 87])
    monkeypatch.setattr(
        InputParameters,
        "requested_task_name",
        property(lambda _parameters: "COMPTON"),
    )
    session = InputParametersSession(
        parameters,
        plugins=(SingleSiteContourPlugin(),),
    )

    session.set_value(("ENERGY", "SPLITSS"), False)

    assert not session.working_parameters.uses_separate_single_site_contour()
    assert list(session.value(("ENERGY", "GRID"))) == ["5"]
    assert list(session.value(("ENERGY", "NE"))) == [32]


def test_unrelated_edit_does_not_repair_incomplete_imported_split_contour():
    parameters = InputParameters.create("scf")
    parameters.ENERGY.SPLITSS.set(True)
    parameters.ENERGY.GRID.set([5])
    parameters.ENERGY.NE.set([32])
    session = InputParametersSession(
        parameters,
        plugins=(SingleSiteContourPlugin(),),
    )

    session.set_value(("SCF", "NITER"), 201)

    assert list(session.value(("ENERGY", "GRID"))) == ["5"]
    assert list(session.value(("ENERGY", "NE"))) == [32]


@pytest.mark.parametrize("task", ["scf", "bsf"])
def test_energy_grids_are_aligned_side_by_side(task):
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog(task, InputParameters.create(_backend_task(task)))
    dialog.select_page("energy")
    dialog.show()
    application.processEvents()
    main, single = dialog.editors_for(("ENERGY", "GRID"))
    main_position = main.mapTo(dialog, QPoint(0, 0))
    single_position = single.mapTo(dialog, QPoint(0, 0))
    assert main_position.y() == single_position.y()
    assert single_position.x() >= main_position.x() + main.width()
    assert main.width() == single.width()
    assert "grid" in main.placement.label.lower()
    assert "grid" in single.placement.label.lower()
    assert not dialog.session.is_modified()
    dialog.close()


@pytest.mark.parametrize("task", ["scf", "bsf"])
def test_cluster_disabled_explanation_tracks_partial_and_full_activation(task):
    application = QApplication.instance() or QApplication([])
    dialog = GuidedInputParametersDialog(task, InputParameters.create(_backend_task(task)))
    note = dialog.group_note("cluster_extent")
    radius = dialog.editors_for(("TAU", "CLURAD"))[0]
    centre = dialog.editors_for(("TAU", "IQCNTR"))[0]
    assert note.isEnabled()
    assert "Disabled: STANDARD" in note.text()
    assert '"KKR representation"' in note.text()
    assert not radius.control.isEnabled() and not centre.control.isEnabled()
    assert 'Disabled: Choose TB or IMPURITY' in radius.toolTip()
    assert '"Use cluster mode"' in centre.toolTip()
    assert not dialog.session.is_modified()

    dialog.session.set_value(("TAU", "KKRMODE"), "TB")
    assert "shells and radius are active" in note.text()
    assert radius.control.isEnabled() and not centre.control.isEnabled()
    assert "Disabled:" not in radius.toolTip()
    assert "Disabled:" in centre.control.toolTip()

    dialog.session.set_value(("TAU", "CLUSTER"), True)
    assert "Cluster settings are active" in note.text()
    assert centre.control.isEnabled()
    assert "Disabled:" not in centre.toolTip()
    dialog.session.undo_stack.undo()
    assert "shells and radius are active" in note.text()
    dialog.session.undo_stack.undo()
    assert "Disabled: STANDARD" in note.text()
    assert not dialog.session.is_modified()
    dialog.session.undo_stack.redo()
    assert "shells and radius are active" in note.text()

    # All three ways to activate cluster controls have the same explanation.
    for flag, value in (("MOL", True), ("BZINT", "CLUSTER")):
        dialog.session.set_value(("TAU", flag), value)
        assert "Cluster settings are active" in note.text()
        assert centre.control.isEnabled()
        dialog.session.undo_stack.undo()
    dialog.close()
    application.processEvents()
