"""Presentation ownership for the calculation-result browser."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from ase2sprkkr_gui.gui.application.result_action_policy import (
    NewCalculationSource,
    ResultActionAvailability,
    new_calculation_source,
    result_action_availability,
)
from ase2sprkkr_gui.gui.application.result_presentation import present_result_tree
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.widgets.result_actions import ResultActionsWidget


class ResultActionsPresenter(QObject):
    """Own result-browser projection, selection, and action availability."""

    useStateRequested = pyqtSignal(int, object)
    recomputeRequested = pyqtSignal(int)
    newCalculationRequested = pyqtSignal(object)
    newCalculationUnavailable = pyqtSignal()

    def __init__(
        self,
        controller: WorkspaceController,
        widget: ResultActionsWidget,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._widget = widget
        self._selected_result_id: int | None = None

        controller.structureChanged.connect(self.refresh)
        controller.resultChanged.connect(self.refresh)
        controller.resultSelectionRequested.connect(self.select_result)
        widget.selectionRequested.connect(self.select_result)
        widget.useStateRequested.connect(self._request_use_state)
        widget.recomputeRequested.connect(self._request_recompute)
        widget.newCalculationRequested.connect(self._request_new_calculation)

        self.refresh()

    @property
    def selected_result_id(self) -> int | None:
        return self._selected_result_id

    def refresh(self, *_args) -> None:
        """Rebuild the complete result projection from current application state."""
        model = present_result_tree(
            self._controller.result_store,
            current_structure_id=self._controller.structure_id,
            current_state_id=self._controller.state_id,
            selected_result_id=self._selected_result_id,
        )
        self._selected_result_id = model.selected_result_id
        self._widget.set_model(model)

    def select_result(self, result_id: int) -> None:
        """Select one result and immediately project its presentation."""
        self._selected_result_id = result_id
        self.refresh()

    def action_availability(self, result_id: int) -> ResultActionAvailability:
        """Resolve actions again at intent time to avoid stale UI decisions."""
        try:
            record = self._controller.result_store.result(result_id)
        except KeyError:
            return ResultActionAvailability()
        return result_action_availability(
            self._controller.result_store,
            record,
            current_structure_id=self._controller.structure_id,
            current_state_id=self._controller.state_id,
        )

    def _request_use_state(self, result_id: int) -> None:
        action = self.action_availability(result_id).use_state
        if action is None:
            self.refresh()
            return
        self.useStateRequested.emit(result_id, action.expected_potential)

    def _request_recompute(self, result_id: int) -> None:
        if self.action_availability(result_id).recompute is None:
            self.refresh()
            return
        self.recomputeRequested.emit(result_id)

    def _request_new_calculation(self, structure_id: int) -> None:
        source: NewCalculationSource | None = new_calculation_source(
            self._controller.result_store,
            structure_id,
            current_structure_id=self._controller.structure_id,
            current_state_id=self._controller.state_id,
        )
        if source is None:
            self.newCalculationUnavailable.emit()
            return
        self.newCalculationRequested.emit(source)
