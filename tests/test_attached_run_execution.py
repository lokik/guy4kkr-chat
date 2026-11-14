from __future__ import annotations

import pytest

from ase2sprkkr_gui.gui.application.attached_run_execution import AttachedRunExecution
from ase2sprkkr_gui.gui.application.execution_cancellation import ExecutionCancelled


class _Cancellation:
    def __init__(self, *, requested: bool = False):
        self.requested = requested
        self.runner = None

    def register(self, runner):
        self.runner = runner
        return not self.requested


class _Source:
    def __init__(self, runner):
        self.runner = runner
        self.calls = []

    def attach(self, job_id, *, output_listener):
        self.calls.append(job_id)
        output_listener("replayed\n", "out")
        return self.runner


def test_attached_execution_replays_output_and_waits_for_result():
    result = object()
    output = []
    attached = []

    class Runner:
        def wait(self):
            return result

        def cancel(self):  # pragma: no cover - successful execution never cancels
            raise AssertionError("unexpected cancellation")

    runner = Runner()
    source = _Source(runner)
    cancellation = _Cancellation()
    execution = AttachedRunExecution(
        source,
        "run-1",
        cancellation,
        output=lambda text, kind: output.append((text, kind)),
        attached=attached.append,
    )

    assert execution.run() is result
    assert source.calls == ["run-1"]
    assert output == [("replayed\n", "out")]
    assert attached == [runner]
    assert cancellation.runner is runner


def test_attached_execution_honors_cancellation_before_registration():
    events = []

    class Runner:
        def wait(self):  # pragma: no cover - cancellation stops before wait
            events.append("wait")

        def stop_observation(self):
            events.append("stop_observation")

        def cancel(self):
            raise AssertionError("An attached observer must not kill the job")

    with pytest.raises(ExecutionCancelled):
        AttachedRunExecution(
            _Source(Runner()),
            "run-1",
            _Cancellation(requested=True),
        ).run()

    assert events == ["stop_observation"]


def test_attached_execution_converts_wait_failure_after_cancel_to_cancellation():
    cancellation = _Cancellation()

    class Runner:
        def wait(self):
            cancellation.requested = True
            raise RuntimeError("backend stopped")

        def cancel(self):
            pass

    with pytest.raises(ExecutionCancelled):
        AttachedRunExecution(_Source(Runner()), "run-1", cancellation).run()


def test_attached_execution_propagates_backend_failure_when_not_cancelled():
    class Runner:
        def wait(self):
            raise RuntimeError("backend failed")

        def cancel(self):
            pass

    with pytest.raises(RuntimeError, match="backend failed"):
        AttachedRunExecution(_Source(Runner()), "run-1", _Cancellation()).run()
