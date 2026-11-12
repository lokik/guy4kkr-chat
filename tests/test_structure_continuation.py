from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from guy4ase.gui.application.result_action_policy import NewCalculationSource
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import DocumentChange, WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.presenters.result_actions import ResultActionsPresenter
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class _Value:
    info = ""
    display_name = "value"

    def value_label(self):
        return "value"

    def actions(self):
        return ()


def _result(task: str = "dos"):
    return SimpleNamespace(
        task_name=task,
        produces_potential=False,
        output_file=f"{task}.out",
        output_values={"value": _Value()},
    )


def _record_result_for_state(controller: WorkspaceController, state_id: int):
    state = controller.result_store.state(state_id)
    return controller.result_store.add_result(
        _result(),
        structure_id=state.structure_id,
        input_state_id=state_id,
        input_parameters=None,
        directory=None,
    )


def _record_current_result(controller: WorkspaceController):
    return _record_result_for_state(controller, controller.state_id)


def _app():
    return QApplication.instance() or QApplication([])


def _result_widget(controller: WorkspaceController):
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    presenter = ResultActionsPresenter(controller, widget, parent=widget)
    return widget, presenter


def test_user_double_clicking_structure_emits_structure_intent_only():
    application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    _record_current_result(controller)
    widget, _presenter = _result_widget(controller)
    captured = []
    widget.newCalculationRequested.connect(captured.append)

    widget.resize(800, 600)
    widget.show()
    application.processEvents()
    structure = widget._selector.topLevelItem(0)
    result = structure.child(0)
    structure_rect = widget._selector.visualItemRect(structure)
    result_rect = widget._selector.visualItemRect(result)
    assert structure_rect.isValid()
    assert result_rect.isValid()

    QTest.mouseDClick(
        widget._selector.viewport(),
        Qt.MouseButton.LeftButton,
        pos=structure_rect.center(),
    )
    QTest.mouseDClick(
        widget._selector.viewport(),
        Qt.MouseButton.LeftButton,
        pos=result_rect.center(),
    )
    application.processEvents()

    assert captured == [controller.structure_id]
    widget.close()


def test_presenter_uses_active_state_for_current_structure():
    _application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    _record_current_result(controller)
    widget, presenter = _result_widget(controller)

    captured: list[NewCalculationSource] = []
    presenter.newCalculationRequested.connect(captured.append)
    widget.newCalculationRequested.emit(controller.structure_id)

    assert captured == [NewCalculationSource()]
    widget.close()


def test_historical_source_uses_lineage_depth_not_result_completion_order():
    _application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    historical_structure_id = controller.structure_id
    root_state = controller.state_id
    deeper_state = controller.result_store.new_child_state(root_state)
    deeper = _record_result_for_state(controller, deeper_state)
    late_root = _record_result_for_state(controller, root_state)
    assert late_root.id > deeper.id

    controller.replace_structure(Atoms("Cu"))
    widget, presenter = _result_widget(controller)

    captured: list[NewCalculationSource] = []
    presenter.newCalculationRequested.connect(captured.append)
    widget.newCalculationRequested.emit(historical_structure_id)

    assert captured == [NewCalculationSource(result_id=deeper.id)]
    widget.close()


def test_historical_structure_with_multiple_branches_requests_explicit_state():
    _application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    historical_structure_id = controller.structure_id
    root_state = controller.state_id
    alternative_state = controller.result_store.new_child_state(
        root_state,
        new_branch=True,
    )
    _record_result_for_state(controller, root_state)
    _record_result_for_state(controller, alternative_state)
    controller.replace_structure(Atoms("Cu"))
    widget, presenter = _result_widget(controller)

    requested: list[NewCalculationSource] = []
    unavailable = []
    presenter.newCalculationRequested.connect(requested.append)
    presenter.newCalculationUnavailable.connect(lambda: unavailable.append(True))
    widget.newCalculationRequested.emit(historical_structure_id)

    assert requested == []
    assert unavailable == [True]
    widget.close()


def test_historical_continuation_is_one_observable_controller_transition():
    _application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    historical_structure_id = controller.structure_id
    historical_state_id = controller.state_id
    record = _record_current_result(controller)
    controller.replace_structure(Atoms("Cu"))
    generation = controller.structure_generation
    changes = []
    controller.structureChanged.connect(changes.append)

    change = controller.use_for_new_calculation(
        result_id=record.id,
        expected_structure_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert controller.structure_generation == generation.next()
    assert len(changes) == 1
    assert changes[0] is controller.atoms
    assert controller.structure_id == historical_structure_id
    state = controller.result_store.state(controller.state_id)
    assert state.parent_id == historical_state_id
    assert controller.restarted
    assert controller.atoms.get_chemical_formula() == "Fe"


def test_current_continuation_creates_one_new_branch_transition():
    _application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    parent_state_id = controller.state_id
    parent_branch_id = controller.result_store.state(parent_state_id).branch_id
    generation = controller.structure_generation
    changes = []
    controller.structureChanged.connect(changes.append)

    change = controller.use_for_new_calculation(
        expected_structure_generation=generation
    )

    assert change is DocumentChange.APPLIED
    state = controller.result_store.state(controller.state_id)
    assert state.parent_id == parent_state_id
    assert state.branch_id != parent_branch_id
    assert controller.structure_generation == generation.next()
    assert len(changes) == 1
    assert controller.restarted


def test_confirmed_flow_uses_atomic_historical_transition(monkeypatch):
    _application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    historical_state_id = controller.state_id
    record = _record_current_result(controller)
    controller.replace_structure(Atoms("Cu"))
    generation = controller.structure_generation
    changes = []
    controller.structureChanged.connect(changes.append)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    assert calculation_flow.use_for_new_calculation(
        controller,
        None,
        result_id=record.id,
    )
    assert controller.structure_generation == generation.next()
    state = controller.result_store.state(controller.state_id)
    assert state.parent_id == historical_state_id
    assert len(changes) == 1


def test_cancelled_flow_keeps_workspace_unchanged(monkeypatch):
    _application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    record = _record_current_result(controller)
    state_id = controller.state_id
    generation = controller.structure_generation

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    assert not calculation_flow.use_for_new_calculation(
        controller,
        None,
        result_id=record.id,
    )
    assert controller.state_id == state_id
    assert controller.structure_generation == generation


def test_flow_rejects_workspace_change_while_confirmation_is_open(monkeypatch):
    _application = _app()
    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    record = _record_current_result(controller)

    def answer(*_args, **_kwargs):
        controller.replace_structure(Atoms("Ni"))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)
    monkeypatch.setattr(
        calculation_flow,
        "document_change_applied",
        lambda _parent, change: change is DocumentChange.APPLIED,
    )

    assert not calculation_flow.use_for_new_calculation(
        controller,
        None,
        result_id=record.id,
    )
    changed_state_id = controller.state_id
    assert controller.atoms.get_chemical_formula() == "Ni"
    assert controller.result_store.state(changed_state_id).parent_id is None
