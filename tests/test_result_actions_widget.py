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


def test_results_toolbar_has_equal_width_buttons_and_load_action():
    application = QApplication.instance() or QApplication([])
    widget = _widget()
    loaded = []
    widget.loadResultRequested.connect(lambda: loaded.append("load"))
    widget.resize(375, 360)
    widget.show()
    application.processEvents()

    top_buttons = (
        widget.load_result_button, widget.import_directory_button,
    )
    assert [button.text() for button in top_buttons] == [
        "Load Result", "Import Directory…",
    ]
    assert all(not button.icon().isNull() for button in top_buttons)
    assert all(button.isVisible() for button in top_buttons)
    assert max(button.width() for button in top_buttons) - min(
        button.width() for button in top_buttons
    ) <= 1

    bottom_buttons = (
        widget._use_state_button, widget.assign_project_button,
        widget.select_all_button,
    )
    assert [button.text() for button in bottom_buttons] == [
        "Use this structure", "Assign to Project", "Select All",
    ]
    assert widget.show_all_values_checkbox.parentWidget().parentWidget() is (
        widget._record_actions
    )
    assert widget._record_actions.isHidden()  # No result selected yet.
    assert not widget._recompute_button.isEnabled()
    assert not widget._use_state_button.isEnabled()
    assert widget._bottom_controls.isHidden()  # No results to select yet.
    assert widget.layout().indexOf(widget._bottom_controls) == (
        widget.layout().indexOf(widget._selector) + 1
    )
    assert widget._record_actions.parentWidget() is widget._container
    assert widget.layout().indexOf(widget._record_actions) == -1
    assert widget._container.layout().itemAt(0).layout() is widget._grid
    assert widget._container.layout().itemAt(1).widget() is widget._record_actions
    assert not widget.select_all_button.isEnabled()
    assert not widget.assign_project_button.isEnabled()
    assert widget.load_result_button.isEnabled()
    widget.load_result_button.click()
    assert loaded == ["load"]
    widget.close()


def test_load_result_control_is_independent_of_assignment_controls():
    application = QApplication.instance() or QApplication([])
    widget = ResultActionsWidget(
        lambda _value, _action: None,
        show_values_without_actions=False,
        show_assignment_controls=False,
    )
    assert widget.select_all_button.isHidden()
    assert widget.assign_project_button.isHidden()
    assert not widget.load_result_button.isHidden()
    widget.close()


def test_result_directory_import_is_independent_of_result_selection():
    application = QApplication.instance() or QApplication([])
    widget = _widget(show_values_without_actions=False)
    requested = []
    widget.importDirectoryRequested.connect(lambda: requested.append("directory"))
    widget.resize(375, 360)
    widget.show()
    application.processEvents()

    assert widget.import_directory_button.text() == "Import Directory…"
    assert widget.import_directory_button.isEnabled()
    assert widget.import_directory_button.isVisible()
    assert not widget.import_directory_button.icon().isNull()
    assert widget.import_directory_button.shortcut().toString() == "Ctrl+Shift+I"
    assert widget.load_result_button.shortcut().toString() == "Ctrl+Shift+O"
    widget.import_directory_button.click()
    assert requested == ["directory"]
    widget.close()


def test_show_all_values_toggle_preserves_result_and_restores_summary_filter():
    _application = QApplication.instance() or QApplication([])
    widget = _widget(show_values_without_actions=False)
    summary = _Value()
    summary.show_in_summary = True
    result = _Result({"ordinary": _Value(), "summary": summary})
    widget.set_result(result)
    assert not widget.show_all_values_checkbox.isChecked()
    assert widget._row_count == 1
    initial_presentation = widget._current_presentation

    widget.show_all_values_checkbox.setChecked(True)
    assert widget._row_count == 2
    assert widget._current_presentation is initial_presentation

    widget.show_all_values_checkbox.setChecked(False)
    assert widget._row_count == 1
    assert widget._current_presentation is initial_presentation

    widget.set_status("Parsing a different output…")
    widget.show_all_values_checkbox.setChecked(True)
    assert widget._empty_label.text() == "Parsing a different output…"
    assert widget._row_count == 0
    widget.close()


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
    assert widget._use_state_button.isEnabled()
    assert widget._use_state_button.text() == "Use this structure"
    assert not widget._bottom_controls.isHidden()
    assert not widget._recompute_button.isHidden()
    assert widget._recompute_button.text() == "Recompute"
    assert widget._recompute_button.toolTip() == "Recompute on current structure"
    widget.close()


def test_recompute_width_matches_selection_button_and_checkbox_is_independent():
    application = QApplication.instance() or QApplication([])
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        Atoms("Fe"), potential_path="Fe.pot"
    )
    record = store.add_result(
        _record_result("dos"), structure_id=structure_id,
        input_state_id=state_id, input_parameters=object(), directory=None,
    )
    widget = _widget(show_values_without_actions=False)
    _set_store(
        widget, store, structure_id=structure_id,
        state_id=state_id, selected_result_id=record.id,
    )
    widget.resize(540, 450)
    widget.show()
    application.processEvents()
    assert widget._recompute_button.isVisible()
    assert widget._recompute_button.isEnabled()
    assert widget.show_all_values_checkbox.isVisible()
    assert widget._record_actions.layout().count() == 3
    check = widget.show_all_values_checkbox
    right = check.parentWidget().x() + check.x() + check.width()
    assert widget._record_actions.width() - right <= 14
    assert abs(
        widget._recompute_button.width() - widget._use_state_button.width()
    ) <= 18

    # Recompute may be disabled for another result, but both slots stay put.
    widget._refresh_record_actions(
        type(widget._current_presentation.actions)(use_state=None, recompute=None)
    )
    application.processEvents()
    assert widget._recompute_button.isVisible()
    assert not widget._recompute_button.isEnabled()
    assert widget.show_all_values_checkbox.isVisible()
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

    assert widget._use_state_button.isEnabled()
    assert widget._use_state_button.text() == "Use this potential"
    assert widget._recompute_button.text() == "Recompute"
    assert widget._recompute_button.toolTip() == "Recompute on current potential"
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
    assert not widget._recompute_button.isEnabled()
    assert widget._recompute_button.isVisible() is False  # Widget is not shown.
    widget.close()
