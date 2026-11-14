from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import QTimer, pyqtSignal, pyqtSlot
from kkrunner import RunState
from kkrunner.runs import DuplicateSubmissionError
from kkrunner.runs.conflicts import submission_conflicts

from ase2sprkkr_gui.gui.application.execution_cancellation import (
    ExecutionCancelled,
    RunCancellation,
)
from ase2sprkkr_gui.gui.application.sprkkr_execution import SprkkrExecution
from ase2sprkkr_gui.gui.application.workspace_controller import CalculationRequest
from ase2sprkkr_gui.gui.dialogs.run_monitor import RunMonitorWindow, RunMonitorWorker
from ase2sprkkr_gui.gui.dialogs.run_conflict import SubmissionConflictDialog


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
    conflictActionFinished = pyqtSignal(object)

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
        self._conflict_dialog: SubmissionConflictDialog | None = None
        self.conflictActionFinished.connect(self._on_conflict_action_finished)

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
        """Keep the resolution dialog available while any conflict remains."""
        self._set_status("New calculation not started — files are in use")
        dialog = SubmissionConflictDialog(conflict, parent=self)
        self._conflict_dialog = dialog
        dialog.actionRequested.connect(self._on_conflict_action)
        try:
            decision = dialog.exec()
        finally:
            self._conflict_dialog = None
            dialog.deleteLater()
        if decision == dialog.DialogCode.Accepted:
            self._set_status("Conflicts resolved — starting calculation…")
            self._retry_after_conflict()
        else:
            self._set_status("New calculation cancelled; existing jobs were kept")
            self._return_to_setup()

    def _conflict_manager(self):
        if self._execution_manager is not None:
            return self._execution_manager
        from ase2sprkkr.sprkkr.projects import default_project_repository
        from ase2sprkkr_gui.gui.application.persistent_jobs import project_run_manager

        return project_run_manager(default_project_repository())

    @pyqtSlot(str, object)
    def _on_conflict_action(self, action: str, selected: object) -> None:
        if self._conflict_cancellation_pending or self._conflict_dialog is None:
            return
        self._conflict_cancellation_pending = True
        proposed = self._conflict_dialog.proposed_record
        self._background_thread_factory(
            target=lambda: self._resolve_conflict_action(action, tuple(selected), proposed),
            name="resolve-conflicting-runs",
            daemon=True,
        ).start()

    def _resolve_conflict_action(
        self, action: str, selected: tuple[str, ...], proposed
    ) -> None:
        """Resolve only selected records, then recheck the global reservations.

        An overridden FAILED state or a deleted record does not terminate a
        native process. User confirmation for these operations belongs to the
        dialog, and the actual new submission still goes through reserve().
        """
        errors: dict[str, str] = {}
        updated = False
        conflicts = None
        try:
            manager = self._conflict_manager()
            if action == "refresh":
                try:
                    manager.refresh()
                except Exception as exc:  # noqa: BLE001 - backend status query
                    logger.exception("Failed to refresh conflicting job statuses")
                    errors["Refresh"] = str(exc)
            elif action in ("stop", "fail", "delete"):
                for run_id in selected:
                    try:
                        record = manager.store.get(run_id)
                        if action == "stop":
                            if not record.state.is_terminal:
                                manager.cancel(run_id)
                        elif action == "fail":
                            if not record.state.is_terminal:
                                result = manager.transition(
                                    record,
                                    state=RunState.FAILED,
                                    expected_record=record,
                                    message=(
                                        "Manually marked failed to clear a file "
                                        "reservation; process termination was NOT verified."
                                    ),
                                )
                                if result.state != RunState.FAILED:
                                    raise RuntimeError(
                                        "The job could not be marked failed in its current state"
                                    )
                                updated = True
                        else:
                            manager.forget(run_id, force=True)
                            updated = True
                        self.persistentJobChanged.emit(run_id)
                    except FileNotFoundError:
                        # The record was removed concurrently; verify the
                        # complete active set below rather than assume success.
                        self.persistentJobChanged.emit(run_id)
                    except Exception as exc:  # noqa: BLE001 - backend/store boundary
                        logger.exception(
                            "Could not %s conflicting job %s", action, run_id
                        )
                        errors[run_id] = str(exc)
            else:
                errors["Action"] = f"Unsupported conflict action: {action}"

            # Use the same collision predicate and global store as reserve().
            # Do not assume that the initial conflict list remains complete.
            active = (
                record for record in manager.store.runs(active=True)
                if record.id != proposed.id and submission_conflicts(proposed, record)
            )
            conflicts = DuplicateSubmissionError(proposed, tuple(active))
        except Exception as exc:  # noqa: BLE001 - manager/storage boundary
            logger.exception("Could not check run reservation conflicts")
            errors["Reservation check"] = str(exc)
        self.conflictActionFinished.emit((action, conflicts, errors, updated))

    @pyqtSlot(object)
    def _on_conflict_action_finished(self, outcome: object) -> None:
        action, conflicts, errors, updated = outcome
        self._conflict_cancellation_pending = False
        if self._close_requested:
            self.close()
            return
        dialog = self._conflict_dialog
        if dialog is None:
            return
        if conflicts is not None:
            dialog.set_conflicts(
                conflicts,
                errors=errors,
                manually_changed=updated and action in ("fail", "delete"),
            )
        elif errors:
            # A failed store check cannot justify enabling Calculate.
            dialog.set_verification_error(errors)
        dialog.set_busy(False)

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
