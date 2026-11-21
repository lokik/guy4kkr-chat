"""Bridge terminal Ctrl+C into the Qt event loop without polling.

Qt documents the socket-pair + QSocketNotifier pattern for Unix signals:
https://doc.qt.io/qt-6/unix-signals.html

Qt APIs cannot safely run in a POSIX signal handler. Python's
signal.set_wakeup_fd() writes a byte to the socket on SIGINT; the notifier
then wakes Qt so the normal shutdown callback runs on the GUI thread.
"""
from __future__ import annotations

import os
import signal
import socket
from time import monotonic
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
        self._handling_interrupt = False
        self._first_interrupt_at: float | None = None
        self._force_exit_delay = 0.5
        self._force_exit_window = 3.0
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

    @staticmethod
    def _console_notice(message: bytes) -> None:
        """Only use async-signal-safe output from the SIGINT handler."""
        try:
            os.write(2, message)
        except OSError:
            pass  # The process may have been launched without stderr.

    def _mark_interrupt(self, _signum: int, _frame: FrameType | None) -> None:
        now = monotonic()
        if self._interrupted or self._handling_interrupt:
            # The force-exit window must expire even while Qt is inside a
            # modal Save/Discard/Cancel dialog (and the callback is running).
            # Re-arm lazily on SIGINT; no Qt timer or reentrant callback needed.
            elapsed = now - self._first_interrupt_at
            if elapsed > self._force_exit_window:
                self._first_interrupt_at = now
                self._console_notice(
                    b"Ctrl+C: force-exit window expired; resetting.\n"
                    b"Hit CTRL+C again to force terminate (after 500 ms, within 3 s).\n"
                )
                return
            # A terminal may send two SIGINTs for an accidental key repeat.
            # Ignore them during the initial debounce period.
            if elapsed >= self._force_exit_delay:
                # Qt may be inside a nested Save/Discard/Cancel dialog. The
                # synchronous callback cannot reliably be reentered.
                self._console_notice(b"Ctrl+C again: forcing exit.\n")
                os._exit(130)
            return
        self._interrupted = True
        self._first_interrupt_at = now
        self._console_notice(
            b"Ctrl+C: shutdown requested.\n"
            b"Hit CTRL+C again to force terminate (after 500 ms, within 3 s).\n"
        )

    def _on_readable(self, *_args) -> None:
        while True:
            try:
                if not self._reader.recv(4096):
                    break
            except BlockingIOError:
                break
        if self._interrupted:
            self._interrupted = False
            self._handling_interrupt = True
            try:
                self._on_interrupt()
            finally:
                self._handling_interrupt = False
                self._first_interrupt_at = None

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
