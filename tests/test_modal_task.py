from __future__ import annotations

import os
from threading import Event

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

from ase2sprkkr_gui.gui.misc import modal_task
from ase2sprkkr_gui.gui.misc.modal_task import _ModalTaskDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_modal_task_dialog_cannot_close_while_running():
    _app()
    parent = QWidget()
    dialog = _ModalTaskDialog(parent)
    dialog.show()

    dialog.reject()
    assert dialog.result() == 0
    assert dialog.isVisible()

    event = QCloseEvent()
    dialog.closeEvent(event)
    assert not event.isAccepted()
    assert dialog.isVisible()

    dialog.finish_successfully()
    assert dialog.result() == QDialog.DialogCode.Accepted


@pytest.mark.parametrize("fail", [False, True])
def test_modal_task_returns_result_or_reraises_worker_error(fail):
    app = _app()
    parent = QWidget()
    value = object()
    error = ValueError("loading failed")

    def operation():
        assert QThread.currentThread() is not app.thread()
        if fail:
            raise error
        return value

    if fail:
        with pytest.raises(ValueError) as caught:
            modal_task.run_modal_task(parent, operation)
        assert caught.value is error
    else:
        assert modal_task.run_modal_task(parent, operation) is value


def test_modal_task_prepares_on_gui_thread_before_hiding_wait_dialog():
    app = _app()
    parent = QWidget()
    called = []

    def read():
        assert QThread.currentThread() is not app.thread()
        return 21

    def prepare(value):
        assert QThread.currentThread() is app.thread()
        dialog = parent.findChild(_ModalTaskDialog)
        assert dialog is not None and dialog.isVisible()
        called.append(value)
        return 2 * value

    assert modal_task.run_modal_task(parent, read, on_success=prepare) == 42
    assert called == [21]


def test_modal_task_preparation_error_is_reported_to_caller():
    _app()
    parent = QWidget()
    error = ValueError("editor preparation failed")

    def prepare(_value):
        raise error

    with pytest.raises(ValueError) as caught:
        modal_task.run_modal_task(parent, lambda: 21, on_success=prepare)
    assert caught.value is error


@pytest.mark.parametrize("fail", [False, True])
def test_modal_task_shutdown_does_not_require_another_gui_event(fail, monkeypatch):
    app = _app()
    parent = QWidget()
    completed = Event()

    class CheckedThread(QThread):
        def wait(self):
            stopped = super().wait(2000)
            if not stopped:
                # Clean up before failing, instead of hanging/crashing pytest.
                self.quit()
                super().wait()
            # Deliver the queued result/error after checking that shutdown did
            # not depend on the GUI dispatching a queued thread.quit() call.
            app.processEvents()
            assert stopped, "Worker shutdown waited for the blocked GUI thread"

    def finish_dialog_without_dispatching_more_events(_dialog):
        # Model the modal loop ending before pending GUI calls are delivered.
        assert completed.wait(2)
        return QDialog.DialogCode.Accepted

    def operation():
        completed.set()
        if fail:
            raise ValueError("loading failed")
        return 42

    monkeypatch.setattr(modal_task, "QThread", CheckedThread)
    monkeypatch.setattr(_ModalTaskDialog, "exec", finish_dialog_without_dispatching_more_events)
    if fail:
        with pytest.raises(ValueError, match="loading failed"):
            modal_task.run_modal_task(parent, operation)
    else:
        assert modal_task.run_modal_task(parent, operation) == 42
