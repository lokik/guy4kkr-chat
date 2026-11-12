"""UI contract for terminal finalization failures."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import guy4ase.gui.controllers.persistent_jobs as controller_module
from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.widgets.persistent_jobs import PersistentJobsWidget


def _job() -> PersistentJob:
    return PersistentJob(
        id="failed-finalization",
        state="failed",
        created_at="2026-10-15T12:00:00+00:00",
        updated_at="2026-10-15T12:05:00+00:00",
        finished_at="2026-10-15T12:05:00+00:00",
        task="DOS",
        directory="/tmp/calc",
        dataset="case",
        target="Local",
        return_code=0,
        failure_phase="download",
        message="result download failed",
        attachable=False,
    )


class _Source:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = True
    supports_attach = True
    supports_retry_download = True
    supports_result_file_check = False

    def __init__(self, job):
        self._job = job

    def subscribe(self, _listener):
        return lambda: None

    def jobs(self):
        return (self._job,)

    def job(self, job_id):
        return self._job if job_id == self._job.id else None


def test_finalization_failure_offers_retry_instead_of_load_result():
    _application = QApplication.instance() or QApplication([])
    job = _job()
    view = PersistentJobsWidget(lambda _value, _action: None)

    view.set_jobs(
        (job,),
        available=True,
        unavailable_reason=None,
        supports_refresh=False,
        supports_results=True,
        supports_attach=True,
        supports_retry_download=True,
    )

    assert not view.retry_download_button.isHidden()
    assert view.load_result_button.isHidden()
    assert view.monitor_button.isHidden()


def test_controller_cannot_bypass_finalization_retry_with_result_load(monkeypatch):
    _application = QApplication.instance() or QApplication([])
    job = _job()
    source = _Source(job)
    controller = PersistentJobsController(source)
    view = PersistentJobsWidget(lambda _value, _action: None)
    called = []
    monkeypatch.setattr(
        controller_module,
        "run_modal_task",
        lambda *_args, **_kwargs: called.append(True),
    )

    controller._load_result_requested(view, job.id)

    assert called == []
