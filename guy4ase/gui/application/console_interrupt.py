"""Bridge terminal Ctrl+C into the Qt event loop without polling."""
from __future__ import annotations

import signal
import socket
from collections.abc import Callable
from types import FrameType

from PyQt6.QtCore import QObject, QSocketNotifier


class ConsoleInterrupt(QObject):
    """Wake Qt on SIGINT and run the shutdown callback on the GUI thread."""

    def __init__(
        self, on_interrupt: Callable[[], None], *, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._on_interrupt = on_interrupt
        self._interrupted = False
        self._closed = False
        self._reader, self._writer = socket.socketpair()
        self._reader.setblocking(False)
        self._writer.setblocking(False)
        self._notifier = QSocketNotifier(
            self._reader.fileno(), QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self._on_readable)
        self._previous_handler = signal.getsignal(signal.SIGINT)
        try:
            self._previous_wakeup_fd = signal.set_wakeup_fd(self._writer.fileno())
            try:
                signal.signal(signal.SIGINT, self._mark_interrupt)
            except BaseException:
                signal.set_wakeup_fd(self._previous_wakeup_fd)
                raise
        except BaseException:
            self._notifier.setEnabled(False)
            self._reader.close()
            self._writer.close()
            raise

    def _mark_interrupt(self, _signum: int, _frame: FrameType | None) -> None:
        self._interrupted = True

    def _on_readable(self, *_args) -> None:
        while True:
            try:
                if not self._reader.recv(4096):
                    break
            except BlockingIOError:
                break
        if self._interrupted:
            self._interrupted = False
            self._on_interrupt()

    def close(self) -> None:
        """Restore process signal state and close wakeup sockets."""
        if self._closed:
            return
        self._closed = True
        self._notifier.setEnabled(False)
        signal.signal(signal.SIGINT, self._previous_handler)
        signal.set_wakeup_fd(self._previous_wakeup_fd)
        self._reader.close()
        self._writer.close()
