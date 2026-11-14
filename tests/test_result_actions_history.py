from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.application.result_presentation import present_result_tree
from ase2sprkkr_gui.gui.application.result_store import ResultStore
from ase2sprkkr_gui.gui.widgets.result_actions import ResultActionsWidget


class _Value:
    info = ""

    def __init__(self, name):
        self.display_name = name

    def value_label(self):
        return self.display_name

    def actions(self):
        return ()


def _ui_result(task, name):
    return SimpleNamespace(
        task_name=task,
        produces_potential=task.lower() == "scf",
        output_file=f"{name}.out",
        output_values={"value": _Value(name)},
    )


def _model(store, structure_id=None, state_id=None, selected_result_id=None):
    return present_result_tree(
        store,
        current_structure_id=structure_id,
        current_state_id=state_id,
        selected_result_id=selected_result_id,
    )


def test_result_selector_groups_by_formula_and_switches_displayed_result():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(Atoms("Fe"), potential_path=None)
    older = _ui_result("dos", "old")
    newest = _ui_result("jxc", "new")
    older_record = store.add_result(
        older,
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=None,
        directory=None,
    )
    newest_record = store.add_result(
        newest,
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=None,
        directory=None,
    )
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_model(_model(store, structure_id, state_id))

    assert widget._selector.topLevelItemCount() == 1
    structure = widget._selector.topLevelItem(0)
    assert structure.text(0) == "Fe"
    assert structure.childCount() == 2
    assert widget.selected_result_id == newest_record.id
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "new"

    widget.set_model(
        _model(store, structure_id, state_id, selected_result_id=older_record.id)
    )
    assert widget.selected_result_id == older_record.id
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "old"
    widget.close()


def test_result_selector_does_not_expose_internal_branch_nodes():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    structure_id, root_state = store.new_structure_state(Atoms("Fe"), potential_path="p0")

    first = store.add_result(
        _ui_result("scf", "a"),
        structure_id=structure_id,
        input_state_id=root_state,
        input_parameters=None,
        directory=None,
        output_atoms=Atoms("Fe"),
        output_potential_path="pa",
    )
    second = store.add_result(
        _ui_result("scf", "b"),
        structure_id=structure_id,
        input_state_id=root_state,
        input_parameters=None,
        directory=None,
        output_atoms=Atoms("Fe"),
        output_potential_path="pb",
    )

    assert store.branch_id_for_result(first) != store.branch_id_for_result(second)

    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=True,
    )
    widget.set_model(_model(store))
    structure = widget._selector.topLevelItem(0)
    assert structure.childCount() == 2
    assert all(
        not structure.child(index).text(0).startswith("Branch")
        for index in range(structure.childCount())
    )
    widget.close()
