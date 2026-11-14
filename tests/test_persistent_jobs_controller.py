"""Behavioral tests for the application-shared persistent-jobs controller."""
from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

import guy4ase.gui.controllers.persistent_jobs as controller_module
from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.application.run_file_deletion import (
    FileDeletionPlan, FileDeletionSnapshot, RemoteFileReview,
)
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.dialogs.delete_run_record import DeleteRunRecordDialog
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
    supports_retry_postprocessing = False
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

    def referenced_file_deletion(self, job_id):
        return FileDeletionPlan((), (), (), (), ())

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


def test_untracked_launch_without_id_does_not_break_monitoring_other_run(monkeypatch):
    _application = QApplication.instance() or QApplication([])
    job = _job("project-run")
    controller = PersistentJobsController(_Source((job,)))
    untracked = _LaunchWindow(SimpleNamespace())
    controller.track_launch_window(untracked)
    created = []

    def create_monitor(*args, **kwargs):
        window = _MonitorWindow()
        created.append(window)
        return window

    monkeypatch.setattr(
        controller_module, "create_attached_run_monitor_window", create_monitor
    )
    controller.open_monitor_window(job.id)

    assert len(created) == 1
    assert controller._monitor_windows[job.id] is created[0]
    assert untracked in controller._pending_monitor_windows


def test_postprocessing_retry_button_runs_worker_and_adopts_result(monkeypatch):
    from dataclasses import replace
    _application = QApplication.instance() or QApplication([])
    job = replace(_job('retry', state='failed'), failure_phase='postprocessing')
    source = _Source((job,))
    source.supports_retry_postprocessing = True
    result = object()
    calls = []

    def retry(job_id):
        calls.append(job_id)
        source.publish(replace(job, state='finished', failure_phase=None))
        return result

    source.retry_postprocessing = retry
    adopted = []
    controller = PersistentJobsController(source, result_adopter=lambda *args: adopted.append(args))
    view = _view()
    controller.bind_view(view)
    monkeypatch.setattr(controller_module, 'run_modal_task', lambda parent, operation, **kwargs: operation())
    view.show()
    view.tree.setCurrentItem(view.tree.topLevelItem(0).child(0))
    assert view.retry_postprocessing_button.isVisible()
    view.retry_postprocessing_button.click()
    assert calls == [job.id]
    assert adopted == [(job.id, result, False)]
    assert not view.retry_postprocessing_button.isVisible()
    view.close()

def test_reconnect_action_is_visible_with_explanation_for_unknown_direct_run():
    _application = QApplication.instance() or QApplication([])
    job = replace(
        _job("direct-run", state="unknown"),
        attachable=False,
        reattach_unavailable_reason="Direct backend cannot reattach.",
    )
    view = _view()
    view.set_jobs(
        (job,), available=True, unavailable_reason=None,
        supports_refresh=True, supports_results=True,
        supports_attach=True, supports_retry_download=True,
    )
    assert not view.monitor_button.isHidden()
    assert not view.monitor_button.isEnabled()
    assert not view.reattach_notice.isHidden()
    assert "Direct backend" in view.reattach_notice.text()
    assert "status unverified" in view.status_value.text()


def test_reconnect_action_is_enabled_for_unknown_supervised_run():
    _application = QApplication.instance() or QApplication([])
    view = _view()
    view.set_jobs(
        (_job("supervised-run", state="unknown"),),
        available=True, unavailable_reason=None,
        supports_refresh=True, supports_results=True,
        supports_attach=True, supports_retry_download=True,
    )
    assert not view.monitor_button.isHidden()
    assert view.monitor_button.isEnabled()
    assert view.reattach_notice.isHidden()


def test_unknown_run_can_be_forgotten_only_after_dangerous_confirmation(monkeypatch):
    _app = QApplication.instance() or QApplication([])
    job = _job("unresolved", state="unknown")
    source = _Source((job,))
    source.supports_forget = True
    calls = []

    def forget(job_id, *, force=False):
        calls.append((job_id, force))
        source._jobs.pop(job_id)
        for listener in tuple(source.listeners):
            listener(job_id)

    source.forget = forget
    controller = PersistentJobsController(source)
    view = _view()
    controller.bind_view(view)
    monkeypatch.setattr(controller_module, "run_modal_task", lambda _view, fn, **_kwargs: fn())
    confirmations = []

    def prompt(dialog):
        confirmations.extend(label.text() for label in dialog.findChildren(QLabel))
        assert dialog.selected_files == ()
        assert not dialog.select_all_button.isEnabled()
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(DeleteRunRecordDialog, "exec", prompt)
    view.forgetRequested.emit(job.id)
    assert calls == [(job.id, True)]
    assert any("might still be running" in item for item in confirmations)
    assert view.all_jobs == ()


def test_cancel_uses_native_backend_and_keeps_history(monkeypatch):
    _app = QApplication.instance() or QApplication([])
    job = replace(_job("active"), cancelable=True)
    source = _Source((job,))
    source.supports_cancel = True
    calls = []
    source.cancel = lambda job_id: calls.append(job_id)
    controller = PersistentJobsController(source)
    view = _view()
    controller.bind_view(view)
    monkeypatch.setattr(controller_module, "run_modal_task", lambda _view, fn, **_kwargs: fn())
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    view.cancelRequested.emit(job.id)
    assert calls == [job.id]
    assert view.all_jobs == (job,)


def test_delete_file_selection_is_explicit_and_displays_shared_references(monkeypatch, tmp_path):
    _app = QApplication.instance() or QApplication([])
    from datetime import datetime
    from PyQt6.QtCore import Qt
    import os

    job = _job("completed", state="finished")
    source = _Source((job,))
    source.supports_forget = True
    own = tmp_path / "output.dos"
    shared = tmp_path / "shared.pot"
    own.write_text("output")
    shared.write_text("shared")
    os.utime(own, (1_700_000_000, 1_700_000_000))
    source.referenced_file_deletion = lambda _job_id: FileDeletionPlan(
        (str(own),), (str(shared),), (), (), ("/remote/output.dos",),
        shared_referrers=((str(shared), ("Run other (Fe-SCF, project 123)",)),),
    )
    calls = []
    source.forget = lambda job_id, **kwargs: calls.append((job_id, kwargs))
    controller = PersistentJobsController(source)
    view = _view()
    controller.bind_view(view)
    monkeypatch.setattr(controller_module, "run_modal_task", lambda _view, fn, **_kwargs: fn())

    def prompt_record_only(dialog):
        assert dialog.selected_files == ()
        assert dialog.select_all_button.isEnabled()
        assert dialog.select_unshared_button.isEnabled()
        tree = dialog.file_table
        assert tree.topLevelItemCount() == 3
        first = tree.topLevelItem(0)
        assert first.text(0) == str(own)
        assert first.text(1) == datetime.fromtimestamp(
            own.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M:%S")
        assert first.checkState(0) == Qt.CheckState.Unchecked
        shared_row = tree.topLevelItem(1)
        assert shared_row.text(0) == str(shared)
        assert "Shared" in shared_row.text(2)
        assert "Run other" in shared_row.toolTip(2)
        assert tree.topLevelItem(2).text(2) == "SSH — checking"
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(DeleteRunRecordDialog, "exec", prompt_record_only)
    view.forgetRequested.emit(job.id)
    assert calls == [(job.id, {"force": False})]

    def prompt_select_unshared(dialog):
        dialog.select_unshared_button.click()
        assert dialog.selected_files == (str(own),)
        assert dialog.selected_shared_files == ()
        assert dialog.confirm_button.text() == "Delete run record and 1 file(s)"
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(DeleteRunRecordDialog, "exec", prompt_select_unshared)
    view.forgetRequested.emit(job.id)
    assert calls[-1] == (
        job.id, {
            "force": False,
            "delete_files": True,
            "expected_files": (str(own),),
            "expected_file_snapshots": (),
            "expected_shared_files": (),
            "allow_shared_files": False,
        },
    )

    def prompt_select_shared(dialog):
        dialog.select_all_button.click()
        assert dialog.selected_files == tuple(sorted((str(own), str(shared))))
        assert dialog.selected_shared_files == (str(shared),)
        assert "WARNING" in dialog.selection_summary.text()
        dialog.select_none_button.click()
        assert dialog.selected_files == ()
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(DeleteRunRecordDialog, "exec", prompt_select_shared)
    view.forgetRequested.emit(job.id)
    assert calls[-1] == (job.id, {"force": False})


def test_shared_file_requires_second_confirmation(monkeypatch, tmp_path):
    _app = QApplication.instance() or QApplication([])
    from PyQt6.QtWidgets import QMessageBox

    path = tmp_path / "shared.out"
    path.write_text("important")
    plan = FileDeletionPlan(
        (), (str(path),), (), (), (),
        shared_referrers=((str(path), ("Run another-job (DOS, project B)",)),),
    )
    dialog = DeleteRunRecordDialog(_job("done", state="finished"), plan)
    dialog.select_all_files()
    prompts = []

    def cancel_first(_parent, title, question, *_buttons):
        prompts.append((title, question))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "warning", cancel_first)
    dialog._confirm_selection()
    assert dialog.result() != dialog.DialogCode.Accepted
    assert "Run another-job" in prompts[0][1]

    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    dialog._confirm_selection()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_deletion_dialog_cancel_has_no_effect(monkeypatch):
    _app = QApplication.instance() or QApplication([])
    job = _job("finished", state="finished")
    source = _Source((job,))
    source.supports_forget = True
    source.forget = lambda *_args, **_kwargs: pytest.fail("must not forget")
    controller = PersistentJobsController(source)
    view = _view()
    controller.bind_view(view)
    monkeypatch.setattr(
        DeleteRunRecordDialog, "exec",
        lambda dialog: dialog.DialogCode.Rejected,
    )
    view.forgetRequested.emit(job.id)
    assert source.job(job.id) is job


def test_deletion_dialog_lists_all_files_and_last_modified_dates(tmp_path):
    _app = QApplication.instance() or QApplication([])
    from datetime import datetime
    from PyQt6.QtCore import Qt
    import os

    paths = tuple(tmp_path / f"result_{index:02d}.dos" for index in range(24))
    for index, path in enumerate(paths):
        path.write_text(f"result {index}")
        os.utime(path, (1_700_000_000 + index * 60,) * 2)
    plan = FileDeletionPlan(tuple(str(path) for path in paths), (), (), (), ())
    dialog = DeleteRunRecordDialog(_job("complete", state="finished"), plan)
    assert dialog.file_table.topLevelItemCount() == 24
    assert not dialog.delete_files

    first = dialog.file_table.topLevelItem(0)
    last = dialog.file_table.topLevelItem(23)
    assert first.text(0) == str(paths[0])
    assert first.text(1) == datetime.fromtimestamp(
        paths[0].stat().st_mtime
    ).strftime("%Y-%m-%d %H:%M:%S")
    assert last.text(0) == str(paths[-1])
    assert last.text(1) == datetime.fromtimestamp(
        paths[-1].stat().st_mtime
    ).strftime("%Y-%m-%d %H:%M:%S")

    dialog.select_all_button.click()
    assert dialog.delete_files
    assert len(dialog.selected_files) == 24
    assert all(
        dialog.file_table.topLevelItem(i).checkState(0) == Qt.CheckState.Checked
        for i in range(24)
    )
    dialog.select_none_button.click()
    assert dialog.selected_files == ()
    # Each individual checkbox can be changed independently.
    dialog.file_table.topLevelItem(5).setCheckState(0, Qt.CheckState.Checked)
    assert dialog.selected_files == (str(paths[5]),)
    dialog.close()



def test_ssh_preview_does_not_disable_local_selection(tmp_path):
    _app = QApplication.instance() or QApplication([])
    from PyQt6.QtCore import Qt

    local = tmp_path / "local.out"
    local.write_text("local")
    remote = "/remote/run/output.out"
    missing = "/remote/run/missing.out"
    plan = FileDeletionPlan((str(local),), (), (), (), (remote, missing))
    dialog = DeleteRunRecordDialog(_job("done", state="finished"), plan)
    assert dialog.selected_remote_files == ()
    assert dialog.select_all_button.isEnabled()
    dialog.select_unshared_button.click()
    assert dialog.selected_files == (str(local),)
    assert dialog.selected_remote_files == ()
    review = RemoteFileReview(
        "cluster", (FileDeletionSnapshot(remote, 1_700_000_000_000_000_000, 8, 1, 3),),
        unavailable=((missing, "missing"),),
    )
    dialog.set_remote_preview(review)
    assert dialog.file_table.topLevelItem(1).text(1).startswith("2023")
    dialog.select_unshared_button.click()
    assert dialog.selected_files == (str(local),)
    assert dialog.selected_remote_files == (remote,)
    assert dialog.file_table.topLevelItem(2).flags() & Qt.ItemFlag.ItemIsUserCheckable == 0
    dialog.select_none()
    assert dialog.selected_files == dialog.selected_remote_files == ()
    dialog.close()


def test_shared_ssh_files_are_not_bulk_selected_as_unshared(tmp_path):
    _app = QApplication.instance() or QApplication([])
    from PyQt6.QtWidgets import QMessageBox
    local = tmp_path / "own.out"
    local.write_text("local")
    remote = "/remote/Fe.pot"
    dialog = DeleteRunRecordDialog(
        _job("done", state="finished"),
        FileDeletionPlan((str(local),), (), (), (), (remote,)),
    )
    dialog.set_remote_preview(RemoteFileReview(
        "cluster", (FileDeletionSnapshot(remote, 1700000000000000000, 5, 1, 2),),
        shared=(remote,),
        referrers=((remote, ("Run second (DOS, project B)",)),),
    ))
    dialog.select_unshared_files()
    assert dialog.selected_files == (str(local),)
    assert dialog.selected_remote_files == ()
    dialog.select_all_files()
    assert dialog.selected_remote_shared_files == (remote,)
    assert "Run second" in dialog.file_table.topLevelItem(1).toolTip(2)
    dialog.close()


def test_ssh_cleanup_starts_only_after_local_record_removal(monkeypatch, tmp_path):
    _app = QApplication.instance() or QApplication([])
    job = _job("finished", state="finished")
    source = _Source((job,))
    source.supports_forget = True
    own = tmp_path / "output.out"
    own.write_text("local")
    remote = "/remote/output.out"
    source.referenced_file_deletion = lambda _id: FileDeletionPlan(
        (str(own),), (), (), (), (remote,),
    )
    remote_review = RemoteFileReview(
        "cluster", (FileDeletionSnapshot(remote, 1_700_000_000_000_000_000, 5, 2, 3),),
    )
    events = []
    pending = []

    class FakeThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            pending.append(self.target)

    source.capture_remote_cleanup = lambda _id: object()

    def forget(_id, **kwargs):
        assert own.exists()
        own.unlink()
        events.append(("local", kwargs))

    def cleanup(*args):
        assert not own.exists()
        events.append(("remote", args))
        raise OSError("SSH disconnected")

    source.forget = forget
    source.cleanup_remote_files = cleanup
    controller = PersistentJobsController(source)
    view = _view()
    controller.bind_view(view)
    monkeypatch.setattr(controller_module, "Thread", FakeThread)
    monkeypatch.setattr(controller_module, "run_modal_task", lambda _view, fn, **kw: fn())

    def prompt(dialog):
        dialog.set_remote_preview(remote_review)
        dialog.select_all_files()
        assert dialog.selected_files == (str(own),)
        assert dialog.selected_remote_files == (remote,)
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(DeleteRunRecordDialog, "exec", prompt)
    view.forgetRequested.emit(job.id)
    assert len(pending) == 2  # inspection and deferred deletion
    assert not own.exists()
    assert [event[0] for event in events] == ["local"]
    pending[-1]()  # Failure is reported asynchronously, not raised by local cleanup.
    assert [event[0] for event in events] == ["local", "remote"]



def test_local_directory_shows_children_and_requires_recursive_confirmation(
    monkeypatch, tmp_path,
):
    _app = QApplication.instance() or QApplication([])
    from PyQt6.QtWidgets import QMessageBox
    from guy4ase.gui.application.run_file_deletion import plan_file_deletion

    taudir = tmp_path / "tau"
    (taudir / "nested").mkdir(parents=True)
    (taudir / "nested" / "Fe.tau").write_text("tau")
    plan = plan_file_deletion((str(taudir),), other_references=(), expected_kinds={str(taudir): "directory"})
    dialog = DeleteRunRecordDialog(_job("done", state="finished"), plan)
    root = dialog.file_table.topLevelItem(0)
    assert root.text(0) == str(taudir)
    assert root.childCount() == 2
    assert root.child(1).text(1)  # Children's modification dates are displayed.
    dialog.select_unshared_files()
    assert dialog.selected_files == (str(taudir),)
    prompts = []

    def warning(*args):
        prompts.append((args[1], args[2]))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "warning", warning)
    dialog._confirm_selection()
    assert prompts[0][0] == "Delete entire directories?"
    assert dialog.result() != dialog.DialogCode.Accepted
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *_args: QMessageBox.StandardButton.Yes,
    )
    dialog._confirm_selection()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_remote_directory_tree_preview_is_not_confused_with_local_file(tmp_path):
    _app = QApplication.instance() or QApplication([])
    from PyQt6.QtCore import Qt

    path = "/scratch/TAUDIR"
    child = path + "/Fe.tau"
    review = RemoteFileReview(
        "cluster", (FileDeletionSnapshot(
            path, 1_700_000_000_000_000_000, 64, 1, 10, "directory",
            ((child, "file", 1_700_000_000_000_000_001, 6, 1, 11),),
        ),),
    )
    dialog = DeleteRunRecordDialog(
        _job("done", state="finished"),
        FileDeletionPlan((), (), (), (), (path,)),
    )
    dialog.set_remote_preview(review)
    directory = dialog.file_table.topLevelItem(0)
    assert directory.childCount() == 1
    assert directory.child(0).text(0) == child
    assert not (directory.child(0).flags() & Qt.ItemFlag.ItemIsUserCheckable)
    dialog.select_unshared_files()
    assert dialog.selected_remote_files == (path,)
    assert dialog.selected_remote_snapshots[0].kind == "directory"
    assert "recursively" in dialog.selection_summary.text()
    dialog.close()
