"""Regression tests for explicit worker-to-GUI thread boundaries."""
from __future__ import annotations

from threading import get_ident

from PyQt6.QtWidgets import QApplication, QWidget

from ase2sprkkr_gui.gui.misc import modal_task


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_modal_task_completion_updates_dialog_in_gui_thread(monkeypatch):
    _application()
    parent = QWidget()
    gui_thread = get_ident()
    operation_threads = []
    finish_threads = []

    original_finish = modal_task._ModalTaskDialog.finish_successfully

    def finish_successfully(dialog):
        finish_threads.append(get_ident())
        original_finish(dialog)

    monkeypatch.setattr(
        modal_task._ModalTaskDialog,
        "finish_successfully",
        finish_successfully,
    )

    def operation():
        operation_threads.append(get_ident())
        return 42

    try:
        assert modal_task.run_modal_task(parent, operation) == 42
        assert operation_threads and operation_threads[0] != gui_thread
        assert finish_threads == [gui_thread]
    finally:
        parent.close()
