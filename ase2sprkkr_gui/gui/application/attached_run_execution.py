"""Backend execution service for attaching to one persistent calculation."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ase2sprkkr_gui.gui.application.execution_cancellation import (
    Cancellation,
    ExecutionCancelled,
    wait_for_runner,
)
from ase2sprkkr_gui.gui.application.persistent_jobs import PersistentJobSource


class AttachedRunExecution:
    """Attach to and wait for one persistent run without any Qt dependency."""

    def __init__(
        self,
        source: PersistentJobSource,
        job_id: str,
        cancellation: Cancellation,
        *,
        output: Callable[[str, str], None] | None = None,
        attached: Callable[[Any], None] | None = None,
    ) -> None:
        self._source = source
        self._job_id = str(job_id)
        self._cancellation = cancellation
        self._output = output or (lambda _text, _kind: None)
        self._attached = attached or (lambda _runner: None)

    def _attach(self) -> Any:
        runner = self._source.attach(
            self._job_id,
            output_listener=self._output,
        )
        # Stop on an attached observer must never kill the underlying job,
        # including when Stop was requested before registration finished.
        if not self._cancellation.register(runner):
            runner.stop_observation()
            raise ExecutionCancelled
        self._attached(runner)
        return runner

    def run(self) -> Any:
        """Attach, wait for completion, and return the backend result."""
        return wait_for_runner(self._cancellation, self._attach())
