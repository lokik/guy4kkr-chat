from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from guy4ase.gui.widgets.browser_panel import BrowserPanel
from guy4ase.gui.widgets.calculation_setup import CalculationSetupPanel
from guy4ase.gui.widgets.result_actions import ResultActionsWidget


class ExpertSidePanel(QWidget):
    """Compose independent expert-mode side-panel views without application policy."""

    def __init__(
        self,
        *,
        edit_input: Callable[[], None],
        load_input: Callable[[], None],
        save_input: Callable[[], None],
        run_calculation_action: QAction,
        load_output: Callable[[], None],
        value_action: Callable[[Any, Any], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.calculation_setup = CalculationSetupPanel(
            edit_input=edit_input,
            load_input=load_input,
            save_input=save_input,
            run_calculation_action=run_calculation_action,
            load_output=load_output,
            parent=self,
        )
        layout.addWidget(self.calculation_setup)

        self.browser_panel = BrowserPanel(self)
        layout.addWidget(self.browser_panel)

        result_group = QGroupBox("Calculation Result", self)
        result_layout = QVBoxLayout(result_group)
        self.result_actions_widget = ResultActionsWidget(
            value_action,
            show_values_without_actions=True,
            show_history_button=False,
            parent=result_group,
        )
        result_layout.addWidget(self.result_actions_widget, 1)
        layout.addWidget(result_group, 1)

        self.setMaximumWidth(350)
