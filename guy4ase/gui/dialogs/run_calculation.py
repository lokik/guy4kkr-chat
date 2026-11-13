from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import QTimer, pyqtSignal, pyqtSlot
from kkrunner.runs import DuplicateSubmissionError

from guy4ase.gui.application.execution_cancellation import (
    ExecutionCancelled,
    RunCancellation,
)
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace_controller import CalculationRequest
from guy4ase.gui.dialogs.run_monitor import RunMonitorWindow, RunMonitorWorker
from guy4ase.gui.dialogs.run_conflict import (
    CancellationFailureDialog,
    SubmissionConflictDialog,
)


logger = logging.getLogger(__name__)


class _SprkkrRunWorker(RunMonitorWorker):
    """Qt signal adapter around the backend-only :class:`SprkkrExecution`."""

    persistentJobChanged = pyqtSignal(str)
    conflict = pyqtSignal(object)

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
        except DuplicateSubmissionError as exc:
            # This is a rejected preflight reservation, not a backend failure.
            # Preserve the RunRecords and per-file collisions for the UI.
            self.conflict.emit(exc)
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - worker/backend boundary
            logger.exception("SPR-KKR calculation or result loading failed")
            self.error.emit(str(exc))


class SprkkrRunWindow(RunMonitorWindow):
    """Create an SPR-KKR runner and display it in the generic run monitor."""

    persistentJobChanged = pyqtSignal(str)
    conflictStopFinished = pyqtSignal(object)
    conflictForgetFinished = pyqtSignal(object)

    def __init__(
        self,
        request: CalculationRequest,
        parent: Any | None = None,
        *,
        profile_name: str | None = None,
        profile_description: str | None = None,
        project_id: str | None = None,
        on_finished=None,
        on_back_to_setup: Callable[[], None] | None = None,
    ) -> None:
        header = f"Directory: {request.directory}"
        if profile_description:
            header = f"{header}\n{profile_description}"

        self._request = request
        self._execution_manager = None
        self.launch_project_id = project_id
        self._project_id: str | None = project_id
        self._back_to_setup = on_back_to_setup

        def worker_factory(cancellation: RunCancellation) -> _SprkkrRunWorker:
            worker = _SprkkrRunWorker(
                self._request,
                cancellation,
                profile_name=profile_name,
                execution_manager=self._execution_manager,
                project_id=self._project_id,
            )
            worker.persistentJobChanged.connect(self._persistent_job_changed_received)
            worker.conflict.connect(self._on_conflict)
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
        self._conflict_cancellation_pending = False
        self.conflictStopFinished.connect(self._on_conflict_stop_finished)
        self.conflictForgetFinished.connect(self._on_conflict_forget_finished)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._conflict_cancellation_pending:
            # A background SSH cancellation still owns this signal receiver.
            # Let the user hide the monitor without destroying it mid-request.
            self._close_requested = True
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)

    def set_execution_context(self, manager, *, project_id: str | None = None) -> None:
        """Capture persistent execution context before this monitor is started."""
        if self._thread is not None:
            raise RuntimeError("execution context cannot change after the run has started")
        self._execution_manager = manager
        self._project_id = project_id

    @pyqtSlot(str)
    def _persistent_job_changed_received(self, job_id: str) -> None:
        self.persistentJobChanged.emit(job_id)

    def _return_to_setup(self) -> None:
        """Return control to the original run picker after a rejected submission."""
        if self._back_to_setup is None:
            return
        self._set_status("Returning to run setup…")
        # Let the worker's terminal signals and this dialog's close complete
        # before opening the next modal profile/directory picker.
        callback = self._back_to_setup
        self.close()
        QTimer.singleShot(0, callback)

    @pyqtSlot(object)
    def _on_conflict(self, conflict: DuplicateSubmissionError) -> None:
        """Offer an explicit choice instead of displaying a red execution error."""
        self._set_status("New calculation not started — files are in use")
        dialog = SubmissionConflictDialog(conflict, parent=self)
        if dialog.exec() != SubmissionConflictDialog.STOP_EXISTING:
            self._set_status("New calculation cancelled; existing jobs were kept")
            self._return_to_setup()
            return
        self._set_status("Requesting cancellation of conflicting jobs…")
        self._conflict_cancellation_pending = True
        self._background_thread_factory(
            target=lambda: self._stop_existing_jobs(conflict),
            name="cancel-conflicting-runs",
            daemon=True,
        ).start()

    def _conflict_manager(self):
        if self._execution_manager is not None:
            return self._execution_manager
        # Use the same persistent store that was used for submission.
        from ase2sprkkr.sprkkr.projects import default_project_repository
        from guy4ase.gui.application.persistent_jobs import project_run_manager

        return project_run_manager(default_project_repository())

    def _stop_existing_jobs(self, conflict: DuplicateSubmissionError) -> None:
        """Cancel by durable run ID; never erase history or overwrite files.

        Cancellation can be asynchronous. We only retry when all returned
        states are terminal; pending or unverified cancellation leaves the
        new calculation unstarted.
        """
        stopped: list[str] = []
        pending: list[str] = []
        errors: list[tuple[Any | None, str]] = []
        try:
            manager = self._conflict_manager()
            for record in conflict.conflicts:
                try:
                    latest = manager.store.get(record.id)
                    if not latest.state.is_terminal:
                        latest = manager.cancel(record.id)
                    if latest.state.is_terminal:
                        stopped.append(record.id)
                    else:
                        pending.append(record.id)
                    self.persistentJobChanged.emit(record.id)
                except FileNotFoundError:
                    # Missing history does not prove that the native process
                    # exited. In particular, do NOT auto-retry on this basis.
                    pending.append(record.id)
                    self.persistentJobChanged.emit(record.id)
                except Exception as exc:  # noqa: BLE001 - backend cancellation boundary
                    logger.exception("Could not cancel conflicting run %s", record.id)
                    errors.append((record, str(exc)))
        except Exception as exc:  # noqa: BLE001 - manager construction boundary
            logger.exception("Could not access persisted runs for cancellation")
            errors.append((None, str(exc)))
        self.conflictStopFinished.emit((stopped, pending, errors))

    @pyqtSlot(object)
    def _on_conflict_stop_finished(self, outcome: object) -> None:
        stopped, pending, errors = outcome
        self._conflict_cancellation_pending = False
        if self._close_requested:
            self.close()
            return
        if errors:
            dialog = CancellationFailureDialog(errors, pending=pending, parent=self)
            if dialog.exec() == CancellationFailureDialog.REMOVE_SELECTED:
                selected = dialog.selected_job_ids()
                if selected:
                    self._set_status("Removing selected job records from history…")
                    self._conflict_cancellation_pending = True
                    self._background_thread_factory(
                        target=lambda: self._forget_conflicting_jobs(selected),
                        name="forget-conflicting-runs",
                        daemon=True,
                    ).start()
                    return
            self._set_status("New calculation not started — existing jobs kept")
            self._return_to_setup()
        elif pending:
            self._set_status(
                "Stop requested; wait for existing jobs to finish before trying again"
            )
            self._return_to_setup()
        else:
            self._set_status("Conflicting jobs stopped — starting calculation…")
            self._retry_after_conflict()

    def _forget_conflicting_jobs(self, job_ids: tuple[str, ...]) -> None:
        """Forget explicitly selected records; never treat this as cancellation."""
        removed: list[str] = []
        failures: list[str] = []
        try:
            manager = self._conflict_manager()
            for job_id in job_ids:
                try:
                    manager.forget(job_id, force=True)
                except FileNotFoundError:
                    # Another client removed this record in the meantime.
                    removed.append(job_id)
                except Exception as exc:  # noqa: BLE001 - durable storage boundary
                    logger.exception("Failed to forget conflicting run %s", job_id)
                    failures.append(f"{job_id}: {exc}")
                else:
                    removed.append(job_id)
                self.persistentJobChanged.emit(job_id)
        except Exception as exc:  # noqa: BLE001 - manager creation boundary
            logger.exception("Could not access run history for removal")
            failures.append(str(exc))
        self.conflictForgetFinished.emit((removed, failures))

    @pyqtSlot(object)
    def _on_conflict_forget_finished(self, outcome: object) -> None:
        removed, errors = outcome
        self._conflict_cancellation_pending = False
        if self._close_requested:
            self.close()
            return
        if errors:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "Could not remove all job records",
                "The new calculation was NOT started.\n\n" + "\n".join(errors),
            )
            self._set_status("New calculation not started — record removal incomplete")
        elif removed:
            self._set_status(
                "Selected records removed; processes may still run. "
                "New calculation not started"
            )
        else:
            self._set_status("New calculation not started")
        self._return_to_setup()

    @pyqtSlot()
    def _retry_after_conflict(self) -> None:
        """Retry only a rejected preflight submission, with fresh runner state."""
        if self._close_requested:
            return
        previous = self._thread
        if previous is not None and previous.isRunning():
            previous.finished.connect(self._retry_after_conflict)
            return
        # The first worker ended at preflight, before any native job started.
        # Do not reuse its cancelled monitor state or its failed runner.
        self._thread = None
        self._worker = None
        self._cancellation = RunCancellation()
        self._stop_btn.setEnabled(True)
        if previous is not None:
            previous.deleteLater()
        self._start_worker()
