from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

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
