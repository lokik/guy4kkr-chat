import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import pytest
from ase import Atoms
from ase.build import bulk
from PyQt6.QtWidgets import QApplication, QComboBox
from ase2sprkkr.common.grammar_types import String
from ase2sprkkr.input_parameters.input_parameters import InputParameters

from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.field_binding import FieldValue, create_field_binding
from ase2sprkkr_gui.gui.widgets.input_parameters.parameter import ParameterEditor
from ase2sprkkr_gui.gui.input_parameters.specs.schema import Choice, field, main_energy_mesh_field
from ase2sprkkr_gui.gui.widgets.input_parameters.registry import create_editor
from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog
from ase2sprkkr_gui.gui.input_parameters.keyword_choices import keyword_items


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def choices(combo):
    return {combo.itemData(index) for index in range(combo.count())}


def value_editor(session, placement, *, atoms=None):
    binding = create_field_binding(session, placement, "test")
    return create_editor(binding, placement, atoms=atoms)


def test_generic_atom_choices_apply_to_guided_and_expert_keywords(application, monkeypatch):
    parameters = InputParameters.create("scf")
    parameters.SCF.VXC.set("PBE")
    atoms = bulk("Fe", "bcc", a=2.8)
    calls = []

    def provider(structure):
        calls.append(structure)
        return {"PBE": "Structure-dependent choice"}

    monkeypatch.setattr(parameters.SCF.VXC._definition, "choices_for_atoms", provider, raising=False)
    session = InputParametersSession(parameters)
    editor = ParameterEditor(session, field("SCF", "VXC", "XC", "keyword"), "physical", atoms=atoms)
    generic = value_editor(session, field("SCF", "VXC", "XC", "keyword"), atoms=atoms)
    for combo in (editor.control, generic):
        assert choices(combo) == {"PBE"}
        assert combo.itemText(combo.findData("PBE")) == "PBE: Structure-dependent choice"
    assert len(calls) == 2 and all(item is atoms for item in calls)
    editor.close()
    generic.close()


def test_optional_keyword_can_be_unset_and_undone(application):
    session = InputParametersSession(InputParameters.create("scf"))
    editor = ParameterEditor(session, field("TAU", "KKRMODE", "Representation", "keyword"), "kkr")
    assert editor.control.currentData() is None
    assert editor.control.currentText() == "Not set"
    editor.control.setCurrentIndex(editor.control.findData("TB"))
    assert session.value(editor.path) == "TB"
    editor.control.setCurrentIndex(editor.control.findData(None))
    assert not session.option(editor.path).is_set()
    assert editor.control.currentData() is None
    session.undo_stack.undo()
    assert editor.control.currentData() == "TB"
    session.undo_stack.redo()
    assert editor.control.currentData() is None
    editor.close()


def test_required_keyword_and_array_elements_have_no_unset_choice(application, monkeypatch):
    parameters = InputParameters.create("scf")
    monkeypatch.setattr(parameters.SCF.VXC._definition, "is_optional", False)
    session = InputParametersSession(parameters)
    for placement in (
        field("SCF", "VXC", "XC", "keyword"),
        main_energy_mesh_field("GRID", "Grid", "keyword"),
    ):
        editor = ParameterEditor(session, placement, "test")
        assert None not in choices(editor.control)
        editor.close()


def test_explicit_editor_overrides_grammar_default(application):
    session = InputParametersSession(InputParameters.create("scf"))
    placement = field(
        "SCF",
        "NITER",
        "Iterations",
        editor="choice",
        choices=(Choice("Short", 10), Choice("Long", 200)),
    )

    editor = ParameterEditor(session, placement, "test")

    assert isinstance(editor.control, QComboBox)
    assert choices(editor.control) == {10, 200}
    editor.close()


@pytest.mark.parametrize("path, default", [
    (("SCF", "VXC"), "VWN"),
    (("MODE", "OP"), "NONE"),
    (("TAU", "BZINT"), "POINTS"),
])
def test_optional_keyword_with_default_selects_default_without_unset(application, path, default):
    session = InputParametersSession(InputParameters.create("scf"))
    option = session.option(path)
    assert option._definition.is_optional and not option.is_set()
    editor = ParameterEditor(session, field(*path, "Value", "keyword"), "test")
    generic = value_editor(session, field(*path, "Value", "keyword"))
    for combo in (editor.control, generic):
        assert None not in choices(combo)
        assert combo.currentData() == default
    assert not option.is_set() and not session.is_modified()
    editor.close()
    generic.close()


def test_undo_to_keyword_default_does_not_display_unset(application):
    session = InputParametersSession(InputParameters.create("scf"))
    editor = ParameterEditor(session, field("SCF", "VXC", "XC", "keyword"), "physical")
    assert editor.control.currentData() == "VWN"
    editor.control.setCurrentIndex(editor.control.findData("PBE"))
    session.undo_stack.undo()
    assert editor.control.currentData() == "VWN"
    assert not session.option(editor.path).is_set()
    assert not session.is_modified()
    editor.close()


def test_expert_optional_keyword_without_default_retains_unset(application):
    session = InputParametersSession(InputParameters.create("scf"))
    option = session.option(("TAU", "KKRMODE"))
    editor = value_editor(session, field("TAU", "KKRMODE", "Representation"))
    assert editor.currentData() is None
    assert editor.currentText() == "Not set"
    editor.setCurrentIndex(editor.findData("TB"))
    editor.setCurrentIndex(editor.findData(None))
    assert not option.is_set()
    editor.close()


def test_generic_text_editor_uses_grammar_conversion_not_parser(application, monkeypatch):
    grammar_type = String()
    converted = []
    applied = []

    def convert(value):
        converted.append(value)
        return value

    def unexpected_parse(_text):
        pytest.fail("Text editors should use grammar conversion, not grammar parsing")

    monkeypatch.setattr(grammar_type, "convert", convert)
    monkeypatch.setattr(grammar_type, "parse", unexpected_parse)
    class Binding:
        value_type = grammar_type
        option = None
        allows_unset = False
        read_only = False
        allow_empty = False

        @staticmethod
        def read():
            return FieldValue("initial")

        @staticmethod
        def set_value(value):
            applied.append(value)

    editor = create_editor(Binding(), field("TEST", "VALUE", "Value"))
    editor.setText("entered_text")
    editor.editingFinished.emit()
    assert converted == ["entered_text"]
    assert applied == ["entered_text"]
    editor.close()


def test_empty_atom_choices_do_not_fall_back_to_static_choices(application, monkeypatch):
    parameters = InputParameters.create("scf")
    option = parameters.SCF.VXC
    monkeypatch.setattr(option._definition, "choices_for_atoms", lambda atoms: {}, raising=False)
    assert list(keyword_items(option, atoms=Atoms("Fe"))) == []
    assert "PBE" in {value for value, _ in keyword_items(option)}


@pytest.mark.parametrize("symbol, lattice, expected", [
    ("Fe", "bcc", {None, "0", "1", "2", "3", "4", "5", "6"}),
    ("Cu", "fcc", {None, "0", "1", "2", "3", "4", "5", "6", "10"}),
    ("Fe", "sc", {None, "1", "2", "3", "4", "5"}),
])
def test_real_kpath_atom_choices(application, symbol, lattice, expected):
    atoms = bulk(symbol, lattice, a=3.)
    parameters = InputParameters.create("bsfek")
    parameters.set({"ENERGY": {"NE": [200]}, "TASK": {"KPATH": 1}})
    dialog = GuidedInputParametersDialog("bsf", parameters, atoms=atoms)
    for editor in dialog.editors_for(("TASK", "KPATH")):
        control = editor.control
        assert choices(control.path_combo) == expected
        assert control.path_combo.itemText(control.path_combo.findData(None)) == "Custom path"
        assert "Γ" in control.path_combo.itemText(control.path_combo.findData("1"))
        assert control.path_combo.itemText(control.path_combo.findData("1")).startswith("1: ")
        assert all(" — " not in control.path_combo.itemText(i) for i in range(control.path_combo.count()))
        assert not control.path_edit.isEnabled()
    dialog.close()


def test_custom_path_enablement_follows_unset_zero_and_undo(application):
    parameters = InputParameters.create("bsfek")
    parameters.set({"ENERGY": {"NE": [200]}, "TASK": {"KPATH": 0}})
    dialog = GuidedInputParametersDialog("bsf", parameters, atoms=bulk("Fe", "bcc", a=2.8))
    quick, primary = dialog.editors_for(("TASK", "KPATH"))
    assert not quick.control.path_edit.isEnabled()
    quick.control.path_combo.setCurrentIndex(quick.control.path_combo.findData(None))
    assert quick.control.path_edit.isEnabled() and primary.control.path_edit.isEnabled()
    assert dialog.editors_for(("TASK", "KA"))[0].control.isEnabled()
    dialog.session.undo_stack.undo()
    application.processEvents()
    assert quick.control.path_combo.currentData() == "0"
    assert not quick.control.path_edit.isEnabled() and not primary.control.path_edit.isEnabled()
    assert not dialog.editors_for(("TASK", "KA"))[0].control.isEnabled()
    dialog.session.undo_stack.redo()
    application.processEvents()
    assert quick.control.path_edit.isEnabled() and primary.control.path_edit.isEnabled()
    dialog.close()


def test_unsupported_lattice_switches_to_custom_path(application):
    atoms = Atoms("Fe", cell=[2.8, 3.1, 3.7, 70, 80, 75], pbc=True)
    dialog = GuidedInputParametersDialog("bsf", InputParameters.create("bsfek"), atoms=atoms)
    mode = dialog.editors_for(("ENERGY", "NE"))[0]
    mode.control.mode_combo.setCurrentIndex(mode.control.mode_combo.findData("EK"))
    assert not mode._error
    assert dialog.session.value(("TASK", "KPATH")) is None
    path = dialog.editors_for(("TASK", "KPATH"))[0]
    assert choices(path.control.path_combo) == {None}
    assert path.control.path_edit.isEnabled()
    # No predefined path exists for this lattice. The user must enter custom
    # path geometry before the setup is complete.
    assert not dialog._commit_pending()
    dialog.close()


def test_keyword_option_hook_works_without_explicit_keyword_placement(application, monkeypatch):
    session = InputParametersSession(InputParameters.create("scf"))
    session.set_value(("SCF", "VXC"), "PBE")
    atoms = bulk("Fe", "bcc", a=2.8)
    option = session.option(("SCF", "VXC"))
    seen = []

    def provider(structure):
        seen.append(structure)
        return {"PBE": "Option-level choice"}

    monkeypatch.setattr(option, "choices_for_atoms", provider, raising=False)
    editor = ParameterEditor(session, field("SCF", "VXC", "XC", "keyword"), "physical", atoms=atoms)
    assert isinstance(editor.control, QComboBox)
    assert choices(editor.control) == {"PBE"}
    assert len(seen) == 1 and seen[0] is atoms
    editor.close()


def test_expert_dialog_passes_structure_to_keyword_editor(application):
    parameters = InputParameters.create("bsfek")
    parameters.set({"ENERGY": {"NE": [200]}, "TASK": {"KPATH": 1}})
    dialog = InputParametersDialog(parameters, atoms=bulk("Fe", "sc", a=2.8))
    from PyQt6.QtCore import Qt
    tree = dialog.tree_editor.tree
    item, = tree.findItems("KPATH", Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)
    combo = tree.itemWidget(item, 2)
    assert choices(combo) == {None, "1", "2", "3", "4", "5"}
    assert combo.currentData() == "1"
    assert combo.itemText(combo.findData(None)) == "Custom path"
    assert combo.itemText(combo.findData("1")).startswith("1: ")
    assert " — " not in combo.itemText(combo.findData("1"))
    combo.setCurrentIndex(combo.findData(None))
    assert dialog.parameters().TASK.KPATH() is None
    dialog.close()


def test_unavailable_imported_path_is_preserved_but_not_offered(application):
    parameters = InputParameters.create("bsfek")
    parameters.set({"ENERGY": {"NE": [200]}, "TASK": {"KPATH": 10}})
    dialog = GuidedInputParametersDialog("bsf", parameters, atoms=bulk("Fe", "sc", a=2.8))
    combo = dialog.editors_for(("TASK", "KPATH"))[0].control.path_combo
    assert combo.currentData() == "10"
    assert not combo.model().item(combo.currentIndex()).isEnabled()
    assert "unavailable" in combo.currentText()
    assert not dialog.session.is_modified()
    dialog.close()
