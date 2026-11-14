"""Standalone shell for persistent calculation-job browsing."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget

from ase2sprkkr_gui.gui.application.window_geometry import manage_window_geometry
from ase2sprkkr_gui.gui.controllers.persistent_jobs import PersistentJobsController
from ase2sprkkr_gui.gui.dialogs.object_view import execute_value_action
from ase2sprkkr_gui.gui.widgets.persistent_jobs import PersistentJobsWidget


class CalculationHistoryDialog(QDialog):
    """Standalone shell around one view of the shared persistent-jobs controller."""

    def __init__(
        self,
        controller: PersistentJobsController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._persistent_jobs_controller = controller
        self.setWindowTitle("Calculation Jobs")
        manage_window_geometry(
            self,
            "calculation-history",
            default_size=(1100, 700),
        )
        root = QVBoxLayout(self)
        self.jobs = PersistentJobsWidget(
            lambda value, action: execute_value_action(value, action, self),
            self,
        )
        controller.bind_view(self.jobs)
        root.addWidget(self.jobs)
