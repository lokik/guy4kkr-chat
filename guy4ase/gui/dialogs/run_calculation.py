from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import pyqtSignal, pyqtSlot

from guy4ase.gui.application.execution_cancellation import (
    ExecutionCancelled,
    RunCancellation,
)
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs.run_monitor import RunMonitorWindow, RunMonitorWorker


logger = logging.getLogger(__name__)


class _SprkkrRunWorker(RunMonitorWorker):
    """Qt signal adapter around the backend-only :class:`SprkkrExecution`."""

    persistentJobChanged = pyqtSignal(str)

    def __init__(
        self,
        request: CalculationRequest,
        cancellation: RunCancellation,
        *,
        profile_name: str | None = None,
        execution_manager=None,
        project_id: str | None = None,
    ) -> None:
        super().__init__()
        self._execution = SprkkrExecution(
            request,
            cancellation,
            profile_name=profile_name,
            execution_manager=execution_manager,
            project_id=project_id,
            output=self.output.emit,
            status=self.status.emit,
            warning=self.warning.emit,
            persistent_job_changed=self.persistentJobChanged.emit,
        )

    def _emit_cancelled(self) -> None:
        self.status.emit("Cancelled")
        self.cancelled.emit()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.finished.emit(self._execution.run())
        except ExecutionCancelled:
            self._emit_cancelled()
        except Exception as exc:  # noqa: BLE001 - worker/backend boundary
            logger.exception("SPR-KKR calculation or result loading failed")
            self.error.emit(str(exc))


class SprkkrRunWindow(RunMonitorWindow):
    """Create an SPR-KKR runner and display it in the generic run monitor."""

    persistentJobChanged = pyqtSignal(str)

    def __init__(
        self,
        request: CalculationRequest,
        parent: Any | None = None,
        *,
        profile_name: str | None = None,
        profile_description: str | None = None,
        project_id: str | None = None,
        on_finished=None,
    ) -> None:
        header = f"Directory: {request.directory}"
        if profile_description:
            header = f"{header}\n{profile_description}"

        self._request = request
        self._execution_manager = None
        self.launch_project_id = project_id
        self._project_id: str | None = project_id

        def worker_factory(cancellation: RunCancellation) -> _SprkkrRunWorker:
            worker = _SprkkrRunWorker(
                self._request,
                cancellation,
                profile_name=profile_name,
                execution_manager=self._execution_manager,
                project_id=self._project_id,
            )
            worker.persistentJobChanged.connect(self._persistent_job_changed_received)
            return worker

        # Ownership and execution/project context are established by the caller
        # before ``start()``. This prevents a fast local submit from publishing a
        # run id before the application owns this top-level window.
        super().__init__(
            worker_factory,
            parent,
            title="SPRKKR Run",
            header=header,
            warning_title="MPI Not Detected",
            on_finished=on_finished,
            autostart=False,
        )

    def set_execution_context(self, manager, *, project_id: str | None = None) -> None:
        """Capture persistent execution context before this monitor is started."""
        if self._thread is not None:
            raise RuntimeError("execution context cannot change after the run has started")
        self._execution_manager = manager
        self._project_id = project_id

    @pyqtSlot(str)
    def _persistent_job_changed_received(self, job_id: str) -> None:
        self.persistentJobChanged.emit(job_id)
