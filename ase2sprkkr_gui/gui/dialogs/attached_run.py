"""Attach an existing persistent run to the generic run monitor."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import pyqtSlot
from PyQt6.QtWidgets import QWidget

from ase2sprkkr_gui.gui.application.attached_run_execution import AttachedRunExecution
from ase2sprkkr_gui.gui.application.execution_cancellation import (
    ExecutionCancelled,
    RunCancellation,
)
from ase2sprkkr_gui.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from ase2sprkkr_gui.gui.dialogs.run_monitor import (
    RunMonitorWindow,
    RunMonitorWorker,
    state_label,
)


logger = logging.getLogger(__name__)


class AttachedRunWorker(RunMonitorWorker):
    """Qt signal adapter around :class:`AttachedRunExecution`."""

    def __init__(
        self,
        source: PersistentJobSource,
        job_id: str,
        cancellation: RunCancellation,
    ) -> None:
        super().__init__()
        self._execution = AttachedRunExecution(
            source,
            job_id,
            cancellation,
            output=self.output.emit,
            attached=lambda runner: self.status.emit(state_label(runner.state)),
        )

    def _emit_cancelled(self) -> None:
        self.status.emit("Monitoring stopped")
        self.cancelled.emit()

    @pyqtSlot()
    def run(self) -> None:
        self.status.emit("Attaching to calculation…")
        try:
            result = self._execution.run()
        except ExecutionCancelled:
            self._emit_cancelled()
        except Exception as exc:  # noqa: BLE001 - worker/backend boundary
            logger.exception("Failed to attach to SPR-KKR calculation")
            self.error.emit(str(exc))
        else:
            self.status.emit("Finished")
            self.finished.emit(result)


def create_attached_run_monitor_window(
    job: PersistentJob,
    source: PersistentJobSource,
    parent: QWidget | None = None,
    *,
    on_finished: Callable[[Any], None] | None = None,
    autostart: bool = True,
) -> RunMonitorWindow:
    """Create the monitor window for an existing persistent job."""
    title = job.dataset or job.id
    return RunMonitorWindow(
        lambda cancellation: AttachedRunWorker(source, job.id, cancellation),
        parent,
        title=f"Monitor {job.task or 'SPRKKR'} Calculation",
        header=f"{title}\n{job.target} · {job.directory}",
        initial_status=state_label(job.state),
        on_finished=on_finished,
        autostart=autostart,
        observation_only=True,
    )
