"""Behavioral tests for the application-shared persistent-jobs controller."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

import guy4ase.gui.controllers.persistent_jobs as controller_module
from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.widgets.persistent_jobs import PersistentJobsWidget


def _job(
    job_id: str,
    *,
    state: str = "running",
    updated_at: str = "2026-10-14T08:00:00+00:00",
) -> PersistentJob:
    return PersistentJob(
        id=job_id,
        state=state,
        created_at="2026-10-14T08:00:00+00:00",
        updated_at=updated_at,
        task="SCF",
        directory=f"/tmp/{job_id}",
        dataset="Fe-SCF",
        target="Local",
        message=None,
        attachable=state not in {"finished", "failed", "cancelled"},
        failure_phase=("download" if state == "failed" else None),
        return_code=0 if state == "failed" else None,
    )


class _Source:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = False
    supports_attach = True
    supports_retry_download = True
    supports_result_file_check = False

    def __init__(self, jobs: tuple[PersistentJob, ...]) -> None:
        self._jobs = {job.id: job for job in jobs}
        self.listeners = []
        self.subscribe_calls = 0
        self.job_changed_calls = []

    def subscribe(self, listener):
        self.subscribe_calls += 1
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener) if listener in self.listeners else None

    def jobs(self):
        return tuple(self._jobs.values())

    def job(self, job_id):
        return self._jobs.get(job_id)

    def publish(self, job: PersistentJob) -> None:
        self._jobs[job.id] = job
        for listener in tuple(self.listeners):
            listener(job.id)

    def job_changed(self, job_id):
        self.job_changed_calls.append(job_id)
        job = self.job(job_id)
        if job is not None:
            for listener in tuple(self.listeners):
                listener(job_id)
        return job

    def refresh(self):
        return self.jobs()


class _MonitorWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.show_calls = 0
        self.start_calls = 0
        self.raise_calls = 0
        self.activate_calls = 0
        self.close_calls = 0

    def show(self) -> None:
        self.show_calls += 1

    def start(self) -> None:
        self.start_calls += 1

    def raise_(self) -> None:
        self.raise_calls += 1

    def activateWindow(self) -> None:
        self.activate_calls += 1

    def close(self) -> bool:
        self.close_calls += 1
        return True


class _LaunchWindow(_MonitorWindow):
    persistentJobChanged = pyqtSignal(str)

    def __init__(self, runner=None) -> None:
        super().__init__()
        self._runner = runner

    @property
    def runner(self):
        return self._runner


def _view() -> PersistentJobsWidget:
    return PersistentJobsWidget(lambda _value, _action: None)


def test_two_views_share_one_attached_monitor_window(monkeypatch):
    _application = QApplication.instance() or QApplication([])
    job = _job("run-17")
    source = _Source((job,))
    controller = PersistentJobsController(source)
    first = _view()
    second = _view()
    controller.bind_view(first)
    controller.bind_view(second)

    created = []

    def create_monitor_window(
        _job,
        _source,
        parent=None,
        *,
        on_finished=None,
        autostart=True,
    ):
        assert _job is job
        assert _source is source
        assert parent is None
        assert autostart is False
        window = _MonitorWindow()
        created.append((window, on_finished))
        return window

    monkeypatch.setattr(
        controller_module,
        "create_attached_run_monitor_window",
        create_monitor_window,
    )

    first.monitorRequested.emit(job.id)
    second.monitorRequested.emit(job.id)

    assert source.subscribe_calls == 1
    assert len(created) == 1
    monitor_window = created[0][0]
    assert controller._monitor_windows == {job.id: monitor_window}
    assert monitor_window.start_calls == 1
    assert monitor_window.show_calls == 2
    assert monitor_window.raise_calls == 1
    assert monitor_window.activate_calls == 1


def test_finalization_retry_uses_attached_monitor_without_marking_job_active(monkeypatch):
    _application = QApplication.instance() or QApplication([])
    job = _job("run-17", state="failed")
    source = _Source((job,))
    controller = PersistentJobsController(source)
    view = _view()
    controller.bind_view(view)
    created = []

    def create_monitor_window(
        _job,
        _source,
        parent=None,
        *,
        on_finished=None,
        autostart=True,
    ):
        assert _job is job
        assert _source is source
        assert parent is None
        assert autostart is False
        window = _MonitorWindow()
        created.append(window)
        return window

    monkeypatch.setattr(
        controller_module,
        "create_attached_run_monitor_window",
        create_monitor_window,
    )

    assert job.is_final
    assert not job.attachable
    assert job.can_retry_download
    assert view.retry_download_button.isVisible() is False
    # The parent-less test widget is itself hidden, so inspect hidden state rather
    # than QWidget.isVisible(), which includes ancestor visibility.
    assert not view.retry_download_button.isHidden()

    view.retryDownloadRequested.emit(job.id)

    assert len(created) == 1
    assert controller._monitor_windows == {job.id: created[0]}
    assert created[0].start_calls == 1
    assert created[0].show_calls == 1


def test_pending_launch_runner_is_reused_before_lifecycle_signal(monkeypatch):
    job = _job("run-17")
    source = _Source((job,))
    controller = PersistentJobsController(source)
    launch_window = _LaunchWindow(SimpleNamespace(id=job.id))
    controller.track_launch_window(launch_window)

    def fail_create(*_args, **_kwargs):
        raise AssertionError("pending launch must be promoted instead of attaching")

    monkeypatch.setattr(
        controller_module,
        "create_attached_run_monitor_window",
        fail_create,
    )

    controller.open_monitor_window(job.id)

    assert launch_window not in controller._pending_monitor_windows
    assert controller._monitor_windows == {job.id: launch_window}
    assert source.job_changed_calls == [job.id]
    assert launch_window.show_calls == 1
    assert launch_window.raise_calls == 1
    assert launch_window.activate_calls == 1


def test_launch_monitor_is_owned_before_id_and_publishes_lifecycle_updates(monkeypatch):
    job = _job("run-17")
    source = _Source((job,))
    controller = PersistentJobsController(source)
    launch_window = _LaunchWindow()
    updates = []
    controller.launchUpdated.connect(
        lambda job_id, window: updates.append((job_id, window))
    )
    controller.track_launch_window(launch_window)

    assert launch_window in controller._pending_monitor_windows
    assert launch_window in controller._launch_monitor_windows
    assert controller._monitor_windows == {}

    launch_window.persistentJobChanged.emit(job.id)

    assert launch_window not in controller._pending_monitor_windows
    assert controller._monitor_windows == {job.id: launch_window}
    assert source.job_changed_calls == [job.id]
    assert updates == [(job.id, launch_window)]

    launch_window.persistentJobChanged.emit(job.id)
    assert source.job_changed_calls == [job.id, job.id]
    assert updates == [(job.id, launch_window), (job.id, launch_window)]

    def fail_create(*_args, **_kwargs):
        raise AssertionError("an attached monitor must not be created")

    monkeypatch.setattr(
        controller_module,
        "create_attached_run_monitor_window",
        fail_create,
    )
    controller.open_monitor_window(job.id)
    assert launch_window.show_calls == 1
    assert launch_window.raise_calls == 1
    assert launch_window.activate_calls == 1


def test_two_launch_monitors_cannot_claim_same_persistent_job():
    job = _job("run-17")
    source = _Source((job,))
    controller = PersistentJobsController(source)
    first = _LaunchWindow()
    second = _LaunchWindow()
    controller.track_launch_window(first)
    controller.track_launch_window(second)

    first.persistentJobChanged.emit(job.id)

    with pytest.raises(ValueError, match="another monitor window"):
        controller.register_launch_job(job.id, second)

    assert controller._monitor_windows == {job.id: first}
    assert second in controller._pending_monitor_windows
    assert second.close_calls == 0


def test_launch_cannot_replace_existing_attached_monitor(monkeypatch):
    job = _job("run-17")
    source = _Source((job,))
    controller = PersistentJobsController(source)
    attached_window = _MonitorWindow()
    monkeypatch.setattr(
        controller_module,
        "create_attached_run_monitor_window",
        lambda *_args, **_kwargs: attached_window,
    )
    controller.open_monitor_window(job.id)

    launch_window = _LaunchWindow()
    controller.track_launch_window(launch_window)
    with pytest.raises(ValueError, match="another monitor window"):
        controller.register_launch_job(job.id, launch_window)

    assert controller._monitor_windows == {job.id: attached_window}
    assert launch_window in controller._pending_monitor_windows
    assert attached_window.close_calls == 0


def test_failed_first_reload_publishes_later_successful_lifecycle_updates():
    job = _job("run-17")

    class RecoveringSource(_Source):
        def __init__(self, jobs):
            super().__init__(jobs)
            self.fail = True

        def job_changed(self, job_id):
            self.job_changed_calls.append(job_id)
            if self.fail:
                self.fail = False
                raise OSError(f"cannot reload {job_id}")
            return self.job(job_id)

    source = RecoveringSource((job,))
    controller = PersistentJobsController(source)
    launch_window = _LaunchWindow()
    updates = []
    controller.launchUpdated.connect(
        lambda job_id, window: updates.append((job_id, window))
    )
    controller.track_launch_window(launch_window)

    launch_window.persistentJobChanged.emit(job.id)
    assert controller._monitor_windows == {job.id: launch_window}
    assert updates == []

    launch_window.persistentJobChanged.emit(job.id)
    assert source.job_changed_calls == [job.id, job.id]
    assert updates == [(job.id, launch_window)]

    launch_window.persistentJobChanged.emit(job.id)
    assert updates == [(job.id, launch_window), (job.id, launch_window)]


def test_source_change_upserts_job_in_all_bound_views():
    source = _Source((_job("first"),))
    controller = PersistentJobsController(source)
    first = _view()
    second = _view()
    controller.bind_view(first)
    controller.bind_view(second)

    source.publish(_job("second", updated_at="2026-10-14T09:00:00+00:00"))

    assert {job.id for job in first.all_jobs} == {"first", "second"}
    assert {job.id for job in second.all_jobs} == {"first", "second"}


def test_metadata_updates_do_not_clear_loaded_result(monkeypatch):
    first_job = _job("first")
    source = _Source((first_job, _job("second")))
    controller = PersistentJobsController(source)
    view = _view()
    controller.bind_view(view)
    rendered = []
    monkeypatch.setattr(view.result_widget, "set_result", rendered.append)
    result = object()

    view.set_result(first_job.id, result)
    source.publish(_job("first", updated_at="2026-10-14T09:00:00+00:00"))
    source.publish(_job("second", updated_at="2026-10-14T10:00:00+00:00"))

    assert rendered == [result]
    assert view.selected_persistent_ref == first_job.id


def test_destroyed_view_is_removed_from_controller_registry():
    source = _Source((_job("run-17"),))
    controller = PersistentJobsController(source)
    view = _view()
    view.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    controller.bind_view(view)

    assert len(controller._views) == 1
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    assert len(controller._views) == 0


def test_modal_result_loading_publishes_only_on_gui_thread(monkeypatch):
    from threading import get_ident

    _application = QApplication.instance() or QApplication([])
    gui_thread = get_ident()
    source = _Source((_job("completed", state="finished"),))
    source.supports_results = True
    result = object()
    load_threads = []
    published = []

    def load_result(job_id):
        assert job_id == "completed"
        load_threads.append(get_ident())
        return result

    source.load_result = load_result
    controller = PersistentJobsController(source)
    monkeypatch.setattr(
        controller, "_publish_result",
        lambda job_id, value, *, select_result: published.append(
            (get_ident(), job_id, value, select_result)
        ),
    )
    view = _view()

    controller._load_result_requested(view, "completed")

    assert len(load_threads) == 1
    assert load_threads[0] != gui_thread
    assert published == [(gui_thread, "completed", result, True)]
    view.close()
