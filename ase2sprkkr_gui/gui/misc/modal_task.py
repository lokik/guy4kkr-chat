"""Run short blocking operations without freezing the Qt event loop."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QProgressDialog, QWidget

_T = TypeVar("_T")
_MISSING = object()


class _ModalTaskDialog(QProgressDialog):
    """Progress dialog which can only close after its worker has finished."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._may_close = False

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if not self._may_close:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:  # type: ignore[override]
        if self._may_close:
            super().reject()

    def finish_successfully(self) -> None:
        self._may_close = True
        self.accept()

    def finish_with_error(self) -> None:
        self._may_close = True
        super().reject()


class _ModalTaskWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self._operation = operation

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._operation()
        except Exception as exc:  # noqa: BLE001 - re-raised in the GUI thread
            self.failed.emit(exc)
        else:
            self.succeeded.emit(result)


class _ModalTaskReceiver(QObject):
    """Receive worker completion in the GUI thread and update the dialog."""

    def __init__(self, dialog: _ModalTaskDialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self.result: Any = _MISSING
        self.error: Exception | None = None

    @pyqtSlot(object)
    def succeeded(self, value: Any) -> None:
        self.result = value
        self._dialog.finish_successfully()

    @pyqtSlot(object)
    def failed(self, exc: Exception) -> None:
        self.error = exc
        self._dialog.finish_with_error()


def run_modal_task(
    parent: QWidget | None,
    operation: Callable[[], _T],
    *,
    title: str = "Please Wait",
    label: str = "Working…",
) -> _T:
    """Run ``operation`` in a worker while showing a responsive modal wait.

    Non-GUI callers may pass ``None``; in that case the operation runs directly.
    The modal cannot be dismissed while the worker is active because generic
    operations do not provide a cancellation contract.
    """
    if parent is None or not isinstance(parent, QWidget):
        return operation()

    dialog = _ModalTaskDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setRange(0, 0)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setCancelButton(None)

    thread = QThread()
    worker = _ModalTaskWorker(operation)
    worker.moveToThread(thread)
    receiver = _ModalTaskReceiver(dialog)

    worker.succeeded.connect(
        receiver.succeeded,
        Qt.ConnectionType.QueuedConnection,
    )
    worker.failed.connect(
        receiver.failed,
        Qt.ConnectionType.QueuedConnection,
    )
    worker.succeeded.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.succeeded.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    thread.started.connect(worker.run)

    thread.start()
    dialog.exec()
    thread.wait()

    if receiver.error is not None:
        raise receiver.error
    if receiver.result is _MISSING:
        raise RuntimeError("Modal task ended without a result.")
    return receiver.result
