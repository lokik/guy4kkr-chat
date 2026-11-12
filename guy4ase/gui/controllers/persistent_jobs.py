"""GUI workflow coordination for persistent calculation jobs."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from weakref import ReferenceType, ref

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QMessageBox

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from guy4ase.gui.dialogs.attached_run import create_attached_run_monitor_window
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow
from guy4ase.gui.dialogs.run_monitor import RunMonitorWindow
from guy4ase.gui.misc.modal_task import run_modal_task
from guy4ase.gui.widgets.persistent_jobs import PersistentJobsWidget


logger = logging.getLogger(__name__)
PersistentResultAdopter = Callable[[str, Any, bool], None]


class _SourceSignals(QObject):
    changed = pyqtSignal(str)


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
        view.retryDownloadRequested.connect(self.retry_download)
        view.loadResultRequested.connect(
            lambda job_id, bound_view=view: self._load_result_requested(
                bound_view, job_id
            )
        )
        view.jobSelected.connect(self._job_selected)
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
        )

    def refresh_views(self) -> None:
        """Project the complete cached source state into all registered views."""
        for view in self._live_views():
            self.refresh_view(view)

    def load_result(self, job_id: str, *, select_result: bool = True) -> Any:
        """Load a persisted result and publish it through the application bridge."""
        job_id = str(job_id)
        job = self._source.job(job_id)
        if job is not None and job.can_retry_download:
            raise RuntimeError(
                f"Persistent job {job_id} requires download retry before loading"
            )
        result = self._source.load_result(job_id)
        self._publish_result(job_id, result, select_result=select_result)
        return result

    @pyqtSlot(str)
    def _source_changed(self, job_id: str) -> None:
        """Project one authoritative source change without rebuilding unrelated state."""
        job = self._source.job(job_id)
        if job is None:
            self.refresh_views()
            return
        for view in self._live_views():
            view.update_job(job)

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
            if runner is not None and str(runner.id) == job_id:
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

    @pyqtSlot(object)
    def _job_selected(self, job_id: object) -> None:
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

    def _publish_result(
        self,
        job_id: str,
        result: Any,
        *,
        select_result: bool,
    ) -> None:
        if self._result_adopter is not None:
            self._result_adopter(job_id, result, select_result)
        self._set_result_in_views(job_id, result)

    def _set_result_in_views(self, job_id: str, result: Any) -> None:
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
            # Backend/file I/O belongs in the worker. Result adoption modifies
            # WorkspaceController and Qt widgets, so publish only on the GUI thread
            # after the modal worker has returned its value.
            result = run_modal_task(
                view,
                lambda: self._source.load_result(job_id),
                title="Loading Calculation Result",
                label="Loading result files…",
            )
            self._publish_result(job_id, result, select_result=True)
        except Exception as exc:  # noqa: BLE001 - persisted/backend data boundary
            QMessageBox.warning(view, "Result Load Failed", str(exc))
