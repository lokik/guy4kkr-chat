"""Tests for the result-summary widget's presentation contract."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from ase import Atoms
from ase2sprkkr.outputs.task_result import TaskResult
from PyQt6.QtWidgets import QApplication, QToolButton

from ase2sprkkr_gui.gui.application.operation_results import EmptySpheresResult
from ase2sprkkr_gui.gui.application.result_presentation import present_result_tree
from ase2sprkkr_gui.gui.application.result_store import ResultStore
from ase2sprkkr_gui.gui.widgets.result_actions import ResultActionsWidget


class _Result(TaskResult):
    def __init__(self, output_values):
        self._output_values = output_values

    @property
    def output_values(self):
        if isinstance(self._output_values, Exception):
            raise self._output_values
        return self._output_values


class _BrokenItems:
    @staticmethod
    def items():
        raise RuntimeError("broken iteration")


class _Value:
    name = "value"
    display_name = "Display value"
    info = "Value information"

    def __init__(self, *, broken_label=False, broken_actions=False):
        self._broken_label = broken_label
        self._broken_actions = broken_actions

    def value_label(self):
        if self._broken_label:
            raise RuntimeError("broken label")
        return "Readable value"

    def actions(self):
        if self._broken_actions:
            raise RuntimeError("broken actions")
        return ()


def _record_result(task_name: str):
    return SimpleNamespace(
        task_name=task_name,
        produces_potential=False,
        output_values={},
        output_file=f"Fe_{task_name.upper()}.out",
    )


def _widget(*, show_values_without_actions=True):
    return ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=show_values_without_actions,
    )


def _set_store(
    widget: ResultActionsWidget,
    store: ResultStore,
    *,
    structure_id: int | None,
    state_id: int | None,
    selected_result_id: int | None = None,
) -> None:
    widget.set_model(
        present_result_tree(
            store,
            current_structure_id=structure_id,
            current_state_id=state_id,
            selected_result_id=selected_result_id,
        )
    )


def test_result_actions_render_task_result():
    _application = QApplication.instance() or QApplication([])
    widget = _widget()
    result = TaskResult(None, None, None, output_file="result.out")

    widget.set_result(result)

    assert widget.has_rows
    widget.close()


@pytest.mark.parametrize(
    "result,error",
    (
        (_Result(RuntimeError("broken values")), "broken values"),
        (_Result(_BrokenItems()), "broken iteration"),
    ),
)
def test_result_collection_failure_becomes_one_error_row(result, error, caplog):
    _application = QApplication.instance() or QApplication([])
    widget = _widget()

    widget.set_result(result)

    assert widget._row_count == 1
    name = widget._grid.itemAtPosition(0, 0).widget()
    assert name.text() == "Output values could not be loaded ⚠"
    assert error in name.toolTip()
    assert "Failed to load result output values" in caplog.text
    widget.close()


def test_broken_output_value_does_not_hide_other_rows(caplog):
    _application = QApplication.instance() or QApplication([])
    widget = _widget()
    result = _Result({"good": _Value(), "bad": _Value(broken_label=True)})

    widget.set_result(result)

    assert widget._row_count == 2
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "Display value"
    error_name = widget._grid.itemAtPosition(1, 0).widget()
    assert error_name.text() == "bad: unavailable ⚠"
    assert "broken label" in error_name.toolTip()
    assert "Failed to display output value 'bad'" in caplog.text
    widget.close()


def test_broken_actions_keep_value_visible_without_buttons(caplog):
    _application = QApplication.instance() or QApplication([])
    widget = _widget(show_values_without_actions=False)

    widget.set_result(_Result({"bad": _Value(broken_actions=True)}))

    assert widget._row_count == 1
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "Display value"
    buttons = widget._grid.itemAtPosition(0, 1).widget()
    assert not buttons.findChildren(QToolButton)
    summary = widget._grid.itemAtPosition(0, 2).widget()
    assert "Readable value" in summary.toolTip()
    assert "broken actions" in summary.toolTip()
    assert "Failed to load actions for output value 'bad'" in caplog.text
    widget.close()


def test_summary_opt_in_does_not_expose_all_actionless_values():
    _application = QApplication.instance() or QApplication([])
    widget = _widget(show_values_without_actions=False)
    ordinary = _Value()
    summary = _Value()
    summary.show_in_summary = True

    widget.set_result(_Result({"ordinary": ordinary, "summary": summary}))

    assert widget._row_count == 1
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "Display value"
    widget.close()


def test_empty_spheres_result_is_visible_without_actions():
    _application = QApplication.instance() or QApplication([])
    widget = _widget(show_values_without_actions=False)

    widget.set_result(EmptySpheresResult(found=7))

    assert widget._row_count == 1
    assert widget._grid.itemAtPosition(0, 0).widget().text() == "Empty spheres found"
    summary = widget._grid.itemAtPosition(0, 2).widget()
    assert summary.toolTip() == "7"
    widget.close()


def test_result_from_other_structure_offers_structure_reuse():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    first_structure, first_state = store.new_structure_state(
        Atoms("Fe"), potential_path="Fe.pot"
    )
    current_structure, current_state = store.new_structure_state(
        Atoms("Cu"), potential_path="Cu.pot"
    )
    result = _record_result("dos")
    record = store.add_result(
        result,
        structure_id=first_structure,
        input_state_id=first_state,
        input_parameters=object(),
        directory=None,
    )
    widget = _widget()
    _set_store(
        widget,
        store,
        structure_id=current_structure,
        state_id=current_state,
        selected_result_id=record.id,
    )

    assert widget.selected_result_id == record.id
    assert not widget._record_actions.isHidden()
    assert not widget._use_state_button.isHidden()
    assert widget._use_state_button.text() == "Use this structure"
    assert not widget._recompute_button.isHidden()
    assert widget._recompute_button.text() == "Recompute on current structure"
    widget.close()


def test_result_from_other_state_of_same_structure_offers_potential_reuse(tmp_path):
    _application = QApplication.instance() or QApplication([])
    p0 = tmp_path / "p0"
    p1 = tmp_path / "p1"
    p2 = tmp_path / "p2"
    for path in (p0, p1, p2):
        path.write_text(path.name)

    store = ResultStore()
    structure_id, root = store.new_structure_state(Atoms("Fe"), potential_path=str(p0))
    historical_state = store.new_child_state(root, potential_path=str(p1))
    current_state = store.new_child_state(historical_state, potential_path=str(p2))
    result = _record_result("dos")
    record = store.add_result(
        result,
        structure_id=structure_id,
        input_state_id=historical_state,
        input_parameters=object(),
        directory=None,
    )
    widget = _widget()
    _set_store(
        widget,
        store,
        structure_id=structure_id,
        state_id=current_state,
        selected_result_id=record.id,
    )

    assert widget._use_state_button.text() == "Use this potential"
    assert widget._recompute_button.text() == "Recompute on current potential"
    widget.close()


def test_empty_spheres_is_not_presented_as_recomputable_task():
    _application = QApplication.instance() or QApplication([])
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(Atoms("Fe"), potential_path=None)
    record = store.add_result(
        EmptySpheresResult(found=2),
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters={"min_radius": 0.8},
        directory=None,
    )
    widget = _widget(show_values_without_actions=False)
    _set_store(
        widget,
        store,
        structure_id=structure_id,
        state_id=state_id,
        selected_result_id=record.id,
    )

    assert widget.selected_result_id == record.id
    assert widget._selector.currentItem().text(0) == "Empty spheres"
    assert widget._recompute_button.isHidden()
    widget.close()
