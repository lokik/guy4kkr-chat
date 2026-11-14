"""GUI workflow coordination for persistent calculation jobs."""
from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from typing import Any
from weakref import ReferenceType, ref

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMessageBox

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from guy4ase.gui.application.result_cache import ResultLRU
from guy4ase.gui.dialogs.attached_run import create_attached_run_monitor_window
from guy4ase.gui.dialogs.delete_run_record import DeleteRunRecordDialog
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow
from guy4ase.gui.dialogs.run_monitor import RunMonitorWindow
from guy4ase.gui.misc.modal_task import run_modal_task
from guy4ase.gui.widgets.persistent_jobs import PersistentJobsWidget


logger = logging.getLogger(__name__)
PersistentResultAdopter = Callable[[str, Any, bool], None]


class _SourceSignals(QObject):
    changed = pyqtSignal(str)


class _ResultSignals(QObject):
    ready = pyqtSignal(str, object, object)


def _result_version(job: PersistentJob) -> tuple[Any, ...]:
    """Metadata affecting the persisted result, excluding file-check bookkeeping."""
    return (
        job.state, job.updated_at, job.finished_at, job.result_files_state,
        job.failure_phase, job.return_code, job.directory, job.dataset, job.task,
    )


def _can_load_result(job: PersistentJob | None, source: PersistentJobSource) -> bool:
    return bool(
        job is not None and job.is_final and not job.can_retry_download
        and source.supports_results
    )


class PersistentJobsController(QObject):
    """Coordinate persistent-job GUI workflows across all registered views.

    ``PersistentJobSource`` owns persistent metadata, cache/recovery semantics,
    and backend operations. This controller is application-owned and owns the
    Qt-facing workflow shared by all persistent-job views: one source
    subscription, modal progress/error presentation, lazy result-file checks,
    result loading, and exactly one monitor window per persistent process.

    A newly launched monitor is owned here *before* its worker starts. Once its
    runner exists, its stable id can promote that pending monitor even before a
    queued lifecycle notification reaches the GUI. Because runner registration
    precedes persistent submission, a browser cannot legitimately create an
    attached monitor for the same newly launched process first. Any remaining
    two-window collision is therefore an invariant violation, not a recovery
    case to paper over.

    Registered views are weakly referenced because their Qt parents own their
    lifetime. Monitor windows are strongly referenced because this controller,
    not any particular browser or workspace window, owns their GUI lifetime.
    """

    launchUpdated = pyqtSignal(str, object)
    resultOpened = pyqtSignal(str)

    def __init__(
        self,
        source: PersistentJobSource,
        *,
        result_adopter: PersistentResultAdopter | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = source
        self._result_adopter = result_adopter
        self._views: set[ReferenceType[PersistentJobsWidget]] = set()
        self._launch_monitor_windows: set[SprkkrRunWindow] = set()
        self._pending_monitor_windows: set[SprkkrRunWindow] = set()
        self._monitor_windows: dict[str, RunMonitorWindow] = {}
        self._result_cache = ResultLRU()
        self._cached_presentations: dict[str, tuple[Any, ...]] = {}
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="guy4ase-result")
        self._loads: dict[str, tuple[tuple[Any, ...], Future[Any]]] = {}
        self._preload_ids: tuple[str, ...] = ()
        self._selected_preload_id: str | None = None
        self._result_signals = _ResultSignals(self)
        self._result_signals.ready.connect(
            self._background_result_ready, Qt.ConnectionType.QueuedConnection
        )
        self.destroyed.connect(
            lambda *_args, executor=self._executor: executor.shutdown(
                wait=False, cancel_futures=True
            )
        )

        self._source_signals = _SourceSignals(self)
        self._source_signals.changed.connect(self._source_changed)
        self._unsubscribe = self._source.subscribe(self._source_signals.changed.emit)
        self.destroyed.connect(lambda *_args: self._unsubscribe())

    def bind_view(self, view: PersistentJobsWidget) -> None:
        """Register one persistent-jobs view with this shared controller."""
        if any(bound_view() is view for bound_view in self._views):
            raise ValueError("persistent-jobs view is already bound")
        view_ref = ref(view)
        self._views.add(view_ref)
        view.destroyed.connect(
            lambda *_args, bound_view=view_ref: self._views.discard(bound_view)
        )
        view.refreshRequested.connect(
            lambda bound_view=view: self._refresh_requested(bound_view)
        )
        view.monitorRequested.connect(self.open_monitor_window)
        view.cancelRequested.connect(lambda job_id, bound_view=view: self._cancel_requested(bound_view, job_id))
        view.forgetRequested.connect(lambda job_id, bound_view=view: self._forget_requested(bound_view, job_id))
        view.retryDownloadRequested.connect(self.retry_download)
        view.retryPostprocessingRequested.connect(
            lambda job_id, bound_view=view: self._retry_postprocessing_requested(bound_view, job_id)
        )
        view.loadResultRequested.connect(
            lambda job_id, bound_view=view: self._load_result_requested(
                bound_view, job_id
            )
        )
        view.refreshResultRequested.connect(
            lambda job_id, bound_view=view: self._refresh_result_requested(
                bound_view, job_id
            )
        )
        view.jobSelected.connect(
            lambda job_id, bound_view=view_ref: self._job_selected(job_id, bound_view())
        )
        self.refresh_view(view)

    def _live_views(self) -> tuple[PersistentJobsWidget, ...]:
        return tuple(
            view
            for view_ref in tuple(self._views)
            if (view := view_ref()) is not None
        )

    def refresh_view(self, view: PersistentJobsWidget) -> None:
        """Project the complete cached source state into one registered view."""
        view.set_jobs(
            self._source.jobs(),
            available=self._source.available,
            unavailable_reason=self._source.unavailable_reason,
            supports_refresh=self._source.supports_refresh,
            supports_results=self._source.supports_results,
            supports_attach=self._source.supports_attach,
            supports_retry_download=self._source.supports_retry_download,
            supports_retry_postprocessing=getattr(self._source, "supports_retry_postprocessing", False),
            supports_cancel=getattr(self._source, "supports_cancel", False),
            supports_forget=getattr(self._source, "supports_forget", False),
        )

    def refresh_views(self) -> None:
        """Project the complete cached source state into all registered views."""
        for view in self._live_views():
            self.refresh_view(view)

    def load_result(self, job_id: str, *, select_result: bool = True) -> Any:
        """Synchronously obtain and publish a cached or persisted result."""
        job_id = str(job_id)
        job = self._source.job(job_id)
        if job is not None and job.can_retry_download:
            raise RuntimeError(
                f"Persistent job {job_id} requires download retry before loading"
            )
        found, result = self._cached_result(job_id)
        if not found:
            loading = self._loads.get(job_id)
            if loading is not None and job is not None and loading[0] == _result_version(job):
                result = loading[1].result()
            else:
                result = self._source.load_result(job_id)
            self._ensure_current_result(job_id, job)
        self._publish_result(job_id, result, select_result=select_result)
        return result

    def _cached_result(self, job_id: str) -> tuple[bool, Any]:
        job = self._source.job(job_id)
        if not _can_load_result(job, self._source):
            return False, None
        return self._result_cache.lookup(job_id, _result_version(job))

    def _ensure_current_result(self, job_id: str, before: PersistentJob | None) -> None:
        """Never display a result loaded against an obsolete run revision."""
        after = self._source.job(job_id)
        if before is not None and (
            after is None or _result_version(after) != _result_version(before)
        ):
            raise RuntimeError(f"Calculation {job_id} changed while loading its result")

    def preload_results(self, job_ids: Any) -> None:
        """Queue a bounded slice of the selected project's history for background parsing."""
        if not self._source.supports_results:
            return
        eligible = []
        for job_id in job_ids:
            job_id = str(job_id)
            if _can_load_result(self._source.job(job_id), self._source):
                eligible.append(job_id)
            if len(eligible) == self._result_cache.max_entries:
                break
        self._preload_ids = tuple(eligible)
        self._keep_relevant_loads()
        for job_id in eligible:
            self._load_in_background(job_id)

    def _keep_relevant_loads(self) -> None:
        wanted = set(self._preload_ids)
        if self._selected_preload_id is not None:
            wanted.add(self._selected_preload_id)
        for job_id, (_version, future) in tuple(self._loads.items()):
            if job_id not in wanted and future.cancel():
                self._loads.pop(job_id, None)

    def _load_in_background(self, job_id: str) -> None:
        job = self._source.job(job_id)
        if not _can_load_result(job, self._source):
            return
        version = _result_version(job)
        found, result = self._result_cache.lookup(job_id, version)
        if found:
            self._set_result_in_views(job_id, result)
            return
        loading = self._loads.get(job_id)
        if loading is not None:
            if loading[0] == version:
                return
            loading[1].cancel()
        future = self._executor.submit(self._source.load_result, job_id)
        self._loads[job_id] = (version, future)
        future.add_done_callback(
            lambda completed, key=job_id, revision=version:
                self._result_signals.ready.emit(key, revision, completed)
        )
        for view in self._live_views():
            if view.auto_load_results:
                view.set_result_pending(job_id)

    @pyqtSlot(str, object, object)
    def _background_result_ready(
        self, job_id: str, version: tuple[Any, ...], future: Future[Any]
    ) -> None:
        loading = self._loads.get(job_id)
        if loading is None or loading != (version, future):
            return
        self._loads.pop(job_id, None)
        wanted = set(self._preload_ids)
        if self._selected_preload_id is not None:
            wanted.add(self._selected_preload_id)
        if job_id not in wanted or future.cancelled():
            return
        job = self._source.job(job_id)
        if not _can_load_result(job, self._source) or _result_version(job) != version:
            if job_id == self._selected_preload_id:
                self._load_in_background(job_id)
            return
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001 - parse/backend data boundary
            logger.debug("Could not preload result for %s", job_id, exc_info=True)
            for view in self._live_views():
                if view.auto_load_results:
                    view.set_result_error(job_id, str(exc))
            return
        self._result_cache.store(job_id, version, result)
        # Preloading is browsing, not a request to adopt a result in the workspace.
        self._set_result_in_views(job_id, result)

    @pyqtSlot(str)
    def _source_changed(self, job_id: str) -> None:
        """Project one authoritative source change without rebuilding unrelated state."""
        job = self._source.job(job_id)
        if job is None:
            self._result_cache.invalidate(job_id)
            self._loads.pop(job_id, None)
            self.refresh_views()
            return
        shown_version = self._cached_presentations.get(job_id)
        if shown_version is not None and shown_version != _result_version(job):
            self._cached_presentations.pop(job_id, None)
            self._result_cache.invalidate(job_id)
            self._set_result_in_views(job_id, None)
        for view in self._live_views():
            view.update_job(job)
        if job_id in self._preload_ids or job_id == self._selected_preload_id:
            self._load_in_background(job_id)

    def track_launch_window(self, monitor_window: SprkkrRunWindow) -> None:
        """Own and observe a launch monitor before its worker is started."""
        if monitor_window in self._launch_monitor_windows:
            raise ValueError("launch monitor window is already tracked")
        if monitor_window in self._monitor_windows.values():
            raise ValueError("launch monitor window is already registered")

        monitor_ref = ref(monitor_window)
        self._watch_monitor_window(monitor_window)
        monitor_window.persistentJobChanged.connect(
            lambda job_id, window_ref=monitor_ref: self._launch_job_changed(
                job_id,
                window_ref,
            )
        )
        self._launch_monitor_windows.add(monitor_window)
        self._pending_monitor_windows.add(monitor_window)

    def _launch_job_changed(
        self,
        job_id: str,
        monitor_ref: ReferenceType[SprkkrRunWindow],
    ) -> None:
        monitor_window = monitor_ref()
        if monitor_window is not None:
            self.register_launch_job(job_id, monitor_window)

    def _pending_launch_for_job(self, job_id: str) -> SprkkrRunWindow | None:
        """Find a pending launch whose already-created runner owns ``job_id``."""
        for monitor_window in tuple(self._pending_monitor_windows):
            runner = monitor_window.runner
            if runner is not None and str(getattr(runner, "id", "")) == job_id:
                return monitor_window
        return None

    def register_launch_job(
        self,
        job_id: str,
        monitor_window: SprkkrRunWindow,
    ) -> None:
        """Promote a pending launch monitor to its stable persistent run id."""
        job_id = str(job_id)
        registered = self._monitor_windows.get(job_id)

        if registered is monitor_window:
            self._reload_and_publish_launch(job_id, monitor_window)
            return
        if registered is not None:
            raise ValueError(
                f"persistent job {job_id!r} already has another monitor window"
            )
        if monitor_window not in self._pending_monitor_windows:
            raise ValueError("launch monitor window was not registered before start")
        for other_job_id, other_window in self._monitor_windows.items():
            if other_window is monitor_window and other_job_id != job_id:
                raise ValueError(
                    "launch monitor window is already bound to another persistent job"
                )

        self._pending_monitor_windows.remove(monitor_window)
        self._monitor_windows[job_id] = monitor_window
        self._reload_and_publish_launch(job_id, monitor_window)

    def _reload_and_publish_launch(
        self,
        job_id: str,
        monitor_window: SprkkrRunWindow,
    ) -> PersistentJob | None:
        """Reload launch metadata and publish every successful lifecycle update."""
        job = self._reload_job(job_id)
        if job is not None:
            self.launchUpdated.emit(job_id, monitor_window)
        return job

    def _reload_job(self, job_id: str) -> PersistentJob | None:
        try:
            return self._source.job_changed(str(job_id))
        except (OSError, RuntimeError, ValueError):
            logger.exception("Failed to reload persistent job %s", job_id)
            return None

    def _watch_monitor_window(self, monitor_window: RunMonitorWindow) -> None:
        monitor_window.destroyed.connect(
            lambda *_args, window=monitor_window: self._monitor_window_destroyed(
                window
            )
        )

    def _monitor_window_destroyed(self, monitor_window: RunMonitorWindow) -> None:
        self._launch_monitor_windows.discard(monitor_window)
        self._pending_monitor_windows.discard(monitor_window)
        for job_id, registered in tuple(self._monitor_windows.items()):
            if registered is monitor_window:
                self._monitor_windows.pop(job_id, None)

    def _job_selected(
        self, job_id: object, view: PersistentJobsWidget | None = None
    ) -> None:
        if view is not None and view.auto_load_results:
            self._selected_preload_id = None if job_id is None else str(job_id)
            self._keep_relevant_loads()
            if job_id is not None and _can_load_result(
                self._source.job(str(job_id)), self._source
            ):
                self._load_in_background(str(job_id))
                return
        if job_id is None or not self._source.supports_result_file_check:
            return
        job = self._source.job(str(job_id))
        if (
            job is None
            or not job.is_final
            or job.can_retry_download
            or job.result_files_verified
        ):
            return
        try:
            checked = self._source.check_result_files(job.id)
        except (OSError, RuntimeError, ValueError):
            return
        if self._source.job(job.id) != checked:
            for view in self._live_views():
                view.update_job(checked)

    def _refresh_requested(self, view: PersistentJobsWidget) -> None:
        try:
            run_modal_task(
                view,
                self._source.refresh,
                title="Refreshing Calculations",
                label="Checking active calculation statuses…",
            )
        except Exception as exc:  # noqa: BLE001 - execution backend boundary
            QMessageBox.warning(view, "Status Refresh Failed", str(exc))

    def _cancel_requested(self, view: PersistentJobsWidget, job_id: str) -> None:
        """Cancel a native process, not its historical metadata."""
        job = self._source.job(job_id)
        if job is None or job.is_final or not job.cancelable or not self._source.supports_cancel:
            return
        answer = QMessageBox.question(
            view,
            "Cancel calculation process?",
            f"Request termination of {job.dataset or job.id}? "
            "The calculation may be running on another computer. "
            "Its history and result files will be preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            run_modal_task(
                view,
                lambda: self._source.cancel(job_id),
                title="Cancelling Calculation",
                label="Requesting process termination…",
            )
        except Exception as exc:  # noqa: BLE001 - remote execution boundary
            QMessageBox.warning(view, "Cancellation Failed", str(exc))

    def _forget_requested(self, view: PersistentJobsWidget, job_id: str) -> None:
        """Show every referenced file and its modification date before deletion."""
        job = self._source.job(job_id)
        if job is None or not self._source.supports_forget:
            return
        active = not job.is_final
        plan = None
        if not active:
            try:
                plan = self._source.referenced_file_deletion(job_id)
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                QMessageBox.warning(view, "Cannot Review Referenced Files", str(exc))
                return

        dialog = DeleteRunRecordDialog(job, plan, view)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        delete_files = dialog.delete_files
        kwargs = {"force": active}
        if delete_files:
            kwargs.update(
                delete_files=True, expected_files=plan.files,
                expected_file_snapshots=plan.snapshots,
            )
        try:
            run_modal_task(
                view,
                lambda: self._source.forget(job_id, **kwargs),
                title="Removing Calculation Record",
                label=(
                    "Removing referenced local files and saved calculation history…"
                    if delete_files else "Removing saved calculation history…"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - filesystem/persistent storage boundary
            QMessageBox.warning(view, "Delete Run Record Failed", str(exc))

    @staticmethod
    def _show_monitor_window(monitor_window: RunMonitorWindow) -> None:
        monitor_window.show()
        monitor_window.raise_()
        monitor_window.activateWindow()

    def _create_attached_monitor(self, job: PersistentJob) -> None:
        job_id = job.id

        def finished(result: Any) -> None:
            self._reload_job(job_id)
            self._publish_result(job_id, result, select_result=False)

        monitor_window = create_attached_run_monitor_window(
            job,
            self._source,
            parent=None,
            on_finished=finished,
            autostart=False,
        )
        try:
            self._watch_monitor_window(monitor_window)
            self._monitor_windows[job_id] = monitor_window
            monitor_window.show()
            monitor_window.start()
        except BaseException:
            if self._monitor_windows.get(job_id) is monitor_window:
                self._monitor_windows.pop(job_id, None)
            monitor_window.close()
            raise

    @pyqtSlot(str)
    def open_monitor_window(self, job_id: str) -> None:
        """Show the single active monitor window for ``job_id``."""
        job_id = str(job_id)
        monitor_window = self._monitor_windows.get(job_id)
        if monitor_window is None:
            pending_launch = self._pending_launch_for_job(job_id)
            if pending_launch is not None:
                self.register_launch_job(job_id, pending_launch)
                monitor_window = pending_launch
        if monitor_window is not None:
            self._show_monitor_window(monitor_window)
            return

        job = self._source.job(job_id)
        if job is None or not job.attachable or not self._source.supports_attach:
            return
        self._create_attached_monitor(job)

    @pyqtSlot(str)
    def retry_download(self, job_id: str) -> None:
        """Explicitly retry a terminal download failure through the backend."""
        job_id = str(job_id)
        monitor_window = self._monitor_windows.get(job_id)
        if monitor_window is not None:
            self._show_monitor_window(monitor_window)
            return

        job = self._source.job(job_id)
        if (
            job is None
            or not job.can_retry_download
            or not self._source.supports_retry_download
        ):
            return
        self._create_attached_monitor(job)

    def _retry_postprocessing_requested(self, view: PersistentJobsWidget, job_id: str) -> None:
        job = self._source.job(str(job_id))
        if job is None or not job.can_retry_postprocessing or not self._source.supports_retry_postprocessing:
            return
        try:
            result = run_modal_task(
                view, lambda: self._source.retry_postprocessing(job.id),
                title="Retrying Postprocessing", label="Reading preserved calculation results…",
            )
        except Exception as exc:  # noqa: BLE001 - application result boundary
            self._reload_job(job.id)
            QMessageBox.warning(view, "Postprocessing Failed", str(exc))
            return
        self._reload_job(job.id)
        self._result_cache.invalidate(job.id)
        self._publish_result(job.id, result, select_result=False)

    def _publish_result(
        self,
        job_id: str,
        result: Any,
        *,
        select_result: bool,
    ) -> None:
        job = self._source.job(job_id)
        if _can_load_result(job, self._source):
            self._result_cache.store(job_id, _result_version(job), result)
            self._cached_presentations[job_id] = _result_version(job)
        if self._result_adopter is not None:
            self._result_adopter(job_id, result, select_result)
        self._set_result_in_views(job_id, result)

    def _set_result_in_views(self, job_id: str, result: Any) -> None:
        if result is not None:
            job = self._source.job(job_id)
            if job is not None:
                self._cached_presentations[job_id] = _result_version(job)
        for view in self._live_views():
            view.set_result(job_id, result)

    def _load_result_requested(
        self,
        view: PersistentJobsWidget,
        job_id: str,
    ) -> None:
        job = self._source.job(job_id)
        if (
            job is None
            or not job.is_final
            or job.can_retry_download
            or not self._source.supports_results
        ):
            return
        try:
            found, result = self._cached_result(job_id)
            if not found:
                revision = _result_version(job)
                loading = self._loads.get(job_id)
                operation = (
                    (lambda: loading[1].result())
                    if loading is not None and loading[0] == revision
                    else (lambda: self._source.load_result(job_id))
                )
                # Only file parsing runs in the worker; adoption belongs to Qt.
                result = run_modal_task(
                    view, operation,
                    title="Loading Calculation Result",
                    label="Loading result files…",
                )
                self._ensure_current_result(job_id, job)
            self._publish_result(job_id, result, select_result=True)
            self.resultOpened.emit(job_id)
        except Exception as exc:  # noqa: BLE001 - persisted/backend data boundary
            QMessageBox.warning(view, "Result Load Failed", str(exc))

    def _refresh_result_requested(
        self, view: PersistentJobsWidget, job_id: str,
    ) -> None:
        """Force a file reread for browser preview, without adopting it in the workspace."""
        job = self._source.job(job_id)
        if not _can_load_result(job, self._source):
            return
        try:
            result = run_modal_task(
                view, lambda: self._source.load_result(job_id),
                title="Refreshing Calculation Result",
                label="Reading result files…",
            )
            self._ensure_current_result(job_id, job)
            pending = self._loads.pop(job_id, None)
            if pending is not None:
                pending[1].cancel()
            self._result_cache.store(job_id, _result_version(job), result)
            self._set_result_in_views(job_id, result)
        except Exception as exc:  # noqa: BLE001 - persisted/backend data boundary
            QMessageBox.warning(view, "Result Refresh Failed", str(exc))

    @property
    def supports_reassignment(self) -> bool:
        return bool(getattr(self._source, "supports_reassignment", False))

    def reassign_runs(
        self, projects, job_ids: tuple[str, ...], project_id: str | None,
        *, expected_project_ids: dict[str, str | None],
    ) -> None:
        self._source.reassign_runs(
            projects, job_ids, project_id, expected_project_ids=expected_project_ids
        )
