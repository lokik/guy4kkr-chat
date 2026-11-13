"""The browser preloads project results without changing the live workspace."""
from __future__ import annotations

import os
from threading import Event, get_ident

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.widgets.persistent_jobs import PersistentJobsWidget


def _job(job_id: str, updated: str = "2026-11-13T10:00:00+00:00") -> PersistentJob:
    return PersistentJob(
        id=job_id, state="finished", created_at=updated, updated_at=updated,
        finished_at=updated, task="DOS", directory="/tmp", dataset=job_id,
        target="Local", return_code=0, message=None,
    )


class _Source:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = True
    supports_attach = False
    supports_retry_download = False
    supports_retry_postprocessing = False
    supports_result_file_check = False

    def __init__(self):
        self.metadata = {"first": _job("first"), "second": _job("second")}
        self.started = Event()
        self.release = Event()
        self.calls = []
        self.listeners = []

    def subscribe(self, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def jobs(self):
        return tuple(self.metadata.values())

    def job(self, job_id):
        return self.metadata.get(job_id)

    def load_result(self, job_id):
        self.calls.append((job_id, get_ident()))
        self.started.set()
        assert self.release.wait(timeout=5)
        return {"name": job_id}


def _spin_until(app, predicate, timeout=5):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "Timed out waiting for background result"


def test_preloading_stays_off_gui_thread_and_never_adopts(monkeypatch):
    app = QApplication.instance() or QApplication([])
    source = _Source()
    adopted = []
    controller = PersistentJobsController(source, result_adopter=lambda *args: adopted.append(args))
    view = PersistentJobsWidget(lambda *_: None, auto_load_results=True)
    shown = []
    monkeypatch.setattr(view.result_widget, "set_result", shown.append)
    controller.bind_view(view)
    controller.preload_results(("first",))
    assert source.started.wait(timeout=5)
    assert source.calls[0][1] != get_ident()
    assert not adopted
    source.release.set()
    _spin_until(app, lambda: {"name": "first"} in shown)
    assert adopted == []

    # Switching away and back reuses the same cached parsed value.
    second = next(
        view.tree.topLevelItem(i).child(j)
        for i in range(view.tree.topLevelItemCount())
        for j in range(view.tree.topLevelItem(i).childCount())
        if view.tree.topLevelItem(i).child(j).data(0, int(Qt.ItemDataRole.UserRole)) == "second"
    )
    view.tree.setCurrentItem(second)
    first = next(
        view.tree.topLevelItem(i).child(j)
        for i in range(view.tree.topLevelItemCount())
        for j in range(view.tree.topLevelItem(i).childCount())
        if view.tree.topLevelItem(i).child(j).data(0, int(Qt.ItemDataRole.UserRole)) == "first"
    )
    view.tree.setCurrentItem(first)
    _spin_until(app, lambda: shown and shown[-1] == {"name": "first"})
    assert [name for name, _thread in source.calls].count("first") == 1
    view.close()
    controller._executor.shutdown(wait=True, cancel_futures=True)


def test_background_errors_are_not_cached_and_manual_loading_can_retry(monkeypatch):
    app = QApplication.instance() or QApplication([])
    source = _Source()
    source.release.set()
    attempts = []

    def flaky(job_id):
        attempts.append(job_id)
        if len(attempts) == 1:
            raise ValueError("invalid output")
        return {"ok": job_id}

    source.load_result = flaky
    controller = PersistentJobsController(source)
    view = PersistentJobsWidget(lambda *_: None, auto_load_results=True)
    controller.bind_view(view)
    controller.preload_results(("first",))
    _spin_until(app, lambda: "Result unavailable:" in view.result_widget._empty_label.text())
    monkeypatch.setattr(
        "guy4ase.gui.controllers.persistent_jobs.run_modal_task",
        lambda _view, operation, **_kwargs: operation(),
    )
    published = []
    monkeypatch.setattr(controller, "_publish_result", lambda *args, **kw: published.append((args, kw)))
    controller._load_result_requested(view, "first")
    assert published and published[0][0] == ("first", {"ok": "first"})
    view.close()
    controller._executor.shutdown(wait=True, cancel_futures=True)
