"""Thread-safe cancellation contract shared by backend execution services."""
from __future__ import annotations

import asyncio
import logging
from threading import Lock, Thread
from typing import Any, Protocol


logger = logging.getLogger(__name__)


class ExecutionCancelled(Exception):
    """Execution was cancelled before a result could be delivered."""


class Cancellation(Protocol):
    """Cancellation state required by backend execution services."""

    @property
    def requested(self) -> bool: ...

    def register(self, runner: Any) -> bool: ...


def register_runner(cancellation: Cancellation, runner: Any) -> None:
    """Register a runner or cancel it when cancellation was already latched."""
    if cancellation.register(runner):
        return
    runner.cancel()
    raise ExecutionCancelled


def wait_for_runner(cancellation: Cancellation, runner: Any) -> Any:
    """Wait for a runner while normalizing backend cancellation semantics."""
    try:
        result = runner.wait()
    except asyncio.CancelledError as exc:
        raise ExecutionCancelled from exc
    except Exception as exc:
        if cancellation.requested:
            raise ExecutionCancelled from exc
        raise

    if cancellation.requested:
        raise ExecutionCancelled
    return result


class RunCancellation:
    """Bridge a cancellation request to a runner that may not exist yet."""

    def __init__(self, *, observation_only: bool = False) -> None:
        self._observation_only = observation_only
        self._lock = Lock()
        self._requested = False
        self._runner: Any | None = None

    @property
    def requested(self) -> bool:
        with self._lock:
            return self._requested

    @property
    def runner(self) -> Any | None:
        with self._lock:
            return self._runner

    def register(self, runner: Any) -> bool:
        """Register the runner unless cancellation was already requested."""
        with self._lock:
            if self._requested:
                return False
            self._runner = runner
            return True

    def _cancel_runner(self, runner: Any) -> None:
        try:
            if self._observation_only:
                runner.stop_observation()
            else:
                runner.cancel()
        except Exception:  # noqa: BLE001 - backend observer/cancellation boundary
            logger.exception(
                "Failed to stop observing calculation" if self._observation_only
                else "Failed to cancel calculation"
            )

    def request(self) -> None:
        """Latch cancellation and cancel an already-registered runner off-thread."""
        with self._lock:
            if self._requested:
                return
            self._requested = True
            runner = self._runner

        if runner is not None:
            Thread(
                target=self._cancel_runner,
                args=(runner,),
                name="run-cancel",
                daemon=True,
            ).start()
