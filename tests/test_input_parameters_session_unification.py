"""Behavioral coverage for the shared Guided/Expert transaction backend."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import pytest
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog

from ase2sprkkr_gui.gui.dialogs import guided_input
from ase2sprkkr_gui.gui.dialogs.expert_input import InputParametersDialog
from ase2sprkkr_gui.gui.dialogs.guided_input import GuidedInputParametersDialog
from ase2sprkkr_gui.gui.input_parameters.bindings import values_equal
from ase2sprkkr_gui.gui.input_parameters.field_binding import create_field_binding
from ase2sprkkr_gui.gui.input_parameters.session import create_input_parameters_session
from ase2sprkkr_gui.gui.input_parameters.specs.schema import field
from ase2sprkkr_gui.gui.widgets.input_parameters import common as common_editors
from ase2sprkkr_gui.gui.widgets.input_parameters.energy import EnergyEditor


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def _secondary_ne_binding(session):
    return create_field_binding(
        session,
        field(
            "ENERGY",
            "NE",
            "Single-site energy points",
            "integer",
            index=1,
        ),
        "energy",
    )


def _editable_values(parameters):
    return parameters.as_dict(only_changed=False, generated=False, copy=True)


def _expert_energy_editor(dialog, label="EMIN / EMINEV"):
    item, = dialog.tree_editor.tree.findItems(
        label,
        Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive,
        0,
    )
    editor = dialog.tree_editor.tree.itemWidget(item, 2)
    assert isinstance(editor, EnergyEditor)
    return editor


def test_input_dialogs_preserve_qdialog_result_contract(application):
    parameters = InputParameters.create("scf")
    for dialog in (
        InputParametersDialog(parameters),
        GuidedInputParametersDialog("scf", parameters),
    ):
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert isinstance(dialog.parameters(), InputParameters)
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted
        dialog.close()


def test_expert_binding_mutate_is_atomic_after_partial_callback_failure():
    session = create_input_parameters_session(InputParameters.create("scf"))
    binding = create_field_binding(
        session,
        field("SCF", "NITER", "Iterations"),
        "expert",
    )
    before = _editable_values(session.result())

    def fail_after_first_write(candidate):
        candidate.SCF.NITER.set(17)
        raise RuntimeError("second write failed")

    with pytest.raises(RuntimeError, match="second write failed"):
        binding.mutate(fail_after_first_write, text="Broken compound edit")

    assert values_equal(_editable_values(session.result()), before)
    assert session.undo_stack.count() == 0


def test_expert_dialog_forks_supplied_session(application):
    session = create_input_parameters_session(InputParameters.create("scf"))
    before = _editable_values(session.result())
    history_count = session.undo_stack.count()

    dialog = InputParametersDialog(session)
    assert dialog.session is not session
    dialog.session.set_value(("SCF", "NITER"), 17)

    assert values_equal(_editable_values(session.result()), before)
    assert session.undo_stack.count() == history_count
    assert dialog.parameters().SCF.NITER() == 17
    dialog.close()


def test_expert_bound_energy_compound_edit_commits_once_and_undoes_once(application):
    parameters = InputParameters.create("bsfkk")
    parameters.ENERGY.EMIN.set(0.5)
    dialog = InputParametersDialog(parameters)
    editor = _expert_energy_editor(dialog)

    editor.relative.setChecked(True)

    assert dialog.session.undo_stack.count() == 1
    assert dialog.parameters().ENERGY.EMIN() is None
    assert dialog.parameters().ENERGY.EMINEV() is not None
    dialog.session.undo_stack.undo()
    assert dialog.parameters().ENERGY.EMIN() == 0.5
    assert dialog.parameters().ENERGY.EMINEV() is None
    dialog.close()


def test_expert_bound_energy_partial_failure_does_not_commit(
    application,
    monkeypatch,
):
    dialog = InputParametersDialog(InputParameters.create("dos"))
    editor = _expert_energy_editor(dialog)
    before = _editable_values(dialog.parameters())

    def fail_after_first_write(parameters, *_args):
        parameters.ENERGY.EMIN.set(123.0)
        raise RuntimeError("paired option failed")

    monkeypatch.setattr(common_editors, "set_bound_energy", fail_after_first_write)
    editor.number.setValue(editor.number.value() + 1.0)

    assert not editor.commit()
    assert values_equal(_editable_values(dialog.parameters()), before)
    assert dialog.session.undo_stack.count() == 0
    dialog.close()


def test_guided_and_standalone_expert_share_single_site_policy(application):
    parameters = InputParameters.create("scf")
    guided = GuidedInputParametersDialog("scf", parameters)
    expert = InputParametersDialog(parameters)

    for session in (guided.session, expert.session):
        session.set_value(("ENERGY", "SPLITSS"), True)
        _secondary_ne_binding(session).set_value(87)
        session.set_value(("ENERGY", "SPLITSS"), False)
        assert len(session.result().ENERGY.NE()) == 1
        assert session.display_value(("ENERGY", "NE"), 1) == 87
        session.set_value(("ENERGY", "SPLITSS"), True)
        assert list(session.result().ENERGY.NE())[1] == 87

    assert values_equal(
        _editable_values(guided.session.result()),
        _editable_values(expert.session.result()),
    )
    guided.close()
    expert.close()


def test_guided_expert_cancel_keeps_parent_session(application, monkeypatch):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    parent = dialog.session
    before = _editable_values(parent.result())
    history_count = parent.undo_stack.count()

    def cancel(session, **_kwargs):
        assert session is parent
        return None

    monkeypatch.setattr(guided_input, "edit_input_parameters_session", cancel)
    dialog._open_expert_settings()

    assert values_equal(_editable_values(parent.result()), before)
    assert parent.undo_stack.count() == history_count
    dialog.close()


def test_guided_expert_accept_imports_state_as_one_transaction(
    application,
    monkeypatch,
):
    dialog = GuidedInputParametersDialog("scf", InputParameters.create("scf"))
    parent = dialog.session
    parent.set_value(("ENERGY", "SPLITSS"), True)
    _secondary_ne_binding(parent).set_value(87)
    parent.set_value(("ENERGY", "SPLITSS"), False)
    before = _editable_values(parent.result())
    before_history = parent.undo_stack.count()
    old_niter = parent.result().SCF.NITER()

    equivalent = parent.fork()
    equivalent.set_value(("ENERGY", "SPLITSS"), True)
    equivalent.set_value(("SCF", "NITER"), old_niter + 1)

    def accept(session, **_kwargs):
        assert session is parent
        temporary = session.fork()
        temporary.set_value(("ENERGY", "SPLITSS"), True)
        temporary.set_value(("SCF", "NITER"), old_niter + 1)
        return temporary

    monkeypatch.setattr(guided_input, "edit_input_parameters_session", accept)
    dialog._open_expert_settings()

    assert parent.undo_stack.count() == before_history + 1
    assert values_equal(
        _editable_values(parent.result()),
        _editable_values(equivalent.result()),
    )
    assert len(parent.result().ENERGY.NE()) == 2
    assert list(parent.result().ENERGY.NE())[1] == 87

    parent.undo_stack.undo()
    assert values_equal(_editable_values(parent.result()), before)
    assert parent.display_value(("ENERGY", "NE"), 1) == 87
    parent.undo_stack.redo()
    assert len(parent.result().ENERGY.NE()) == 2
    assert list(parent.result().ENERGY.NE())[1] == 87
    dialog.close()
