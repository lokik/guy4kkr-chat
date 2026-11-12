"""Qt tests for reusable persistent calculation-job browsing."""
from __future__ import annotations

from datetime import datetime
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.dialogs.calculation_history import CalculationHistoryDialog


def _local_timestamp(value: str) -> str:
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _job(
    job_id: str,
    *,
    state: str,
    task: str,
    dataset: str,
    created_at: str,
    finished_at: str | None = None,
    target: str = "SSH · cluster",
    attachable: bool | None = None,
    result_files_state: str | None = None,
    result_files_verified: bool = False,
) -> PersistentJob:
    if attachable is None:
        attachable = state not in {"finished", "failed", "cancelled"}
    if result_files_state is None and state == "finished":
        result_files_state = "current"
    return PersistentJob(
        id=job_id,
        state=state,
        created_at=created_at,
        updated_at=created_at,
        finished_at=finished_at,
        task=task,
        directory=f"/tmp/{job_id}",
        dataset=dataset,
        target=target,
        return_code=0 if state == "finished" else None,
        message=None,
        result_files_state=result_files_state,
        attachable=attachable,
        result_files_verified=result_files_verified,
    )


class _Source:
    available = True
    unavailable_reason = None
    supports_refresh = True
    supports_results = True
    supports_attach = True
    supports_retry_download = False
    supports_result_file_check = False

    def __init__(self, jobs):
        self._jobs = tuple(jobs)
        self._listeners = []
        self.loaded = []
        self.refresh_calls = 0
        self.attach_calls = []
        self.runners = {}

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def jobs(self):
        return self._jobs

    def job(self, job_id):
        return next((job for job in self._jobs if job.id == job_id), None)

    def replace_job(self, replacement):
        self._jobs = tuple(
            replacement if job.id == replacement.id else job for job in self._jobs
        )
        for listener in tuple(self._listeners):
            listener(replacement.id)

    def refresh(self):
        self.refresh_calls += 1
        return self._jobs

    def job_changed(self, job_id):
        for listener in tuple(self._listeners):
            listener(job_id)
        return self.job(job_id)

    def attach(self, job_id, *, callback=None, output_listener=None):
        self.attach_calls.append(job_id)
        return self.runners.setdefault(job_id, object())

    def load_result(self, job_id):
        self.loaded.append(job_id)
        return type("Result", (), {"output_values": {}})()


def _dialog(source):
    return CalculationHistoryDialog(PersistentJobsController(source))


def _view(dialog):
    return dialog.jobs


def test_history_groups_jobs_and_shows_selected_metadata():
    _application = QApplication.instance() or QApplication([])
    source = _Source(
        (
            _job(
                "newer-running",
                state="running",
                task="SCF",
                dataset="Fe-SCF",
                created_at="2026-10-13T08:00:00+00:00",
            ),
            _job(
                "older-dos",
                state="finished",
                task="DOS",
                dataset="Fe-DOS",
                created_at="2026-10-12T08:00:00+00:00",
                finished_at="2026-10-12T08:45:00+00:00",
            ),
        )
    )
    dialog = _dialog(source)
    view = _view(dialog)

    assert dialog.windowTitle() == "Calculation Jobs"
    assert [view.group_by.itemText(i) for i in range(view.group_by.count())] == [
        "Started date",
        "Finished date",
        "Status",
        "Task",
        "Execution target",
    ]
    assert view.tree.headerItem().text(2) == "Started"
    assert view.tree.headerItem().text(3) == "Finished"
    assert view.tree.topLevelItem(0).text(0) == "2026-10-13"
    assert view.detail_title.text() == "Fe-SCF"
    assert view.status_value.text() == "Running"
    assert view.started_value.text() == _local_timestamp("2026-10-13T08:00:00+00:00")
    assert view.finished_value.text() == "—"
    assert view.result_files_value.text() == "—"
    assert view.result_widget._history_button is None
    assert not view.monitor_button.isHidden()
    assert view.load_result_button.isHidden()

    view.group_by.setCurrentText("Finished date")
    assert view.tree.topLevelItem(0).text(0) == "Not finished"
    assert view.tree.topLevelItem(1).text(0) == "2026-10-12"
    view.group_by.setCurrentText("Task")
    assert view.tree.topLevelItem(0).text(0) == "SCF"
    dialog.close()


def test_finished_job_shows_stable_finished_time_and_can_load_result():
    _application = QApplication.instance() or QApplication([])
    job = _job(
        "finished-dos",
        state="finished",
        task="DOS",
        dataset="Fe-DOS",
        created_at="2026-10-13T08:00:00+00:00",
        finished_at="2026-10-13T08:37:00+00:00",
    )
    source = _Source((job,))
    dialog = _dialog(source)
    view = _view(dialog)

    finished = _local_timestamp("2026-10-13T08:37:00+00:00")
    assert view.finished_value.text() == finished
    assert view.tree.topLevelItem(0).child(0).text(3) == finished
    assert view.result_files_value.text() == "Current (stored, not checked)"
    assert view.monitor_button.isHidden()
    assert not view.load_result_button.isHidden()
    view.load_result_button.click()
    assert source.loaded == [job.id]
    dialog.close()


def test_selected_final_job_verifies_result_files():
    _application = QApplication.instance() or QApplication([])
    job = _job(
        "finished-overwritten",
        state="finished",
        task="DOS",
        dataset="Fe-DOS",
        created_at="2026-10-13T08:00:00+00:00",
        finished_at="2026-10-13T08:37:00+00:00",
    )

    class Source(_Source):
        supports_result_file_check = True

        def __init__(self, jobs):
            super().__init__(jobs)
            self.checked = []

        def check_result_files(self, job_id):
            self.checked.append(job_id)
            return _job(
                job_id,
                state="finished",
                task="DOS",
                dataset="Fe-DOS",
                created_at="2026-10-13T08:00:00+00:00",
                finished_at="2026-10-13T08:37:00+00:00",
                result_files_state="overwritten",
                result_files_verified=True,
            )

    source = Source((job,))
    dialog = _dialog(source)
    view = _view(dialog)

    assert source.checked == [job.id]
    assert view.result_files_value.text() == "Overwritten"
    assert view._jobs_by_id[job.id].result_files_verified
    dialog.close()


def test_source_change_rebuilds_view_without_widget_owned_recovery():
    application = QApplication.instance() or QApplication([])
    running = _job(
        "job",
        state="running",
        task="DOS",
        dataset="Fe-DOS",
        created_at="2026-10-13T08:00:00+00:00",
    )
    finished = _job(
        "job",
        state="finished",
        task="DOS",
        dataset="Fe-DOS",
        created_at=running.created_at,
        finished_at="2026-10-13T08:45:00+00:00",
        attachable=False,
    )
    source = _Source((running,))
    dialog = _dialog(source)
    view = _view(dialog)

    source.replace_job(finished)
    application.processEvents()

    assert view._jobs_by_id[finished.id].state == "finished"
    assert not view.load_result_button.isHidden()
    assert not hasattr(view, "_recovery")
    dialog.close()


def test_nonattachable_active_job_does_not_offer_monitor():
    _application = QApplication.instance() or QApplication([])
    source = _Source(
        (
            _job(
                "legacy-local",
                state="running",
                task="SCF",
                dataset="Fe-SCF",
                created_at="2026-10-13T08:00:00+00:00",
                attachable=False,
            ),
        )
    )
    dialog = _dialog(source)
    assert _view(dialog).monitor_button.isHidden()
    dialog.close()


def test_empty_backend_shows_empty_state():
    _application = QApplication.instance() or QApplication([])
    dialog = _dialog(_Source(()))
    view = _view(dialog)

    assert not view.backend_notice.isHidden()
    assert view.backend_notice.text() == (
        "No persistent calculation jobs have been recorded yet."
    )
    assert view.tree.topLevelItemCount() == 0
    dialog.close()


def test_unavailable_backend_is_an_empty_nonfatal_history():
    _application = QApplication.instance() or QApplication([])

    class Source(_Source):
        available = False
        unavailable_reason = "Persistent jobs are not available yet."
        supports_refresh = False
        supports_results = False
        supports_attach = False
        supports_retry_download = False
        supports_result_file_check = False

    dialog = _dialog(Source(()))
    view = _view(dialog)

    assert not view.backend_notice.isHidden()
    assert view.backend_notice.text() == "Persistent jobs are not available yet."
    assert not view.refresh_button.isEnabled()
    assert view.tree.topLevelItemCount() == 0
    dialog.close()
