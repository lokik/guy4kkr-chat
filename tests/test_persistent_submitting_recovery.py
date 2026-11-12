from __future__ import annotations

from types import SimpleNamespace
from ase2sprkkr.execution import Execution, ExecutorEndpoint, WorkingDirectory, FileManifest

from guy4ase.gui.application.persistent_jobs import PersistentJobSource


def _record(state: str):
    return SimpleNamespace(
        id="run-id",
        state=SimpleNamespace(value=state),
        created_at="2026-10-17T08:00:00+00:00",
        updated_at="2026-10-17T08:00:00+00:00",
        finished_at=None,
        task="SCF",
        execution=Execution(ExecutorEndpoint(), WorkingDirectory("/tmp/calc")),
        files=FileManifest(), failure_phase=None,
        dataset=None,

        return_code=None,
        message=None,

    )


class _Store:
    def __init__(self, record):
        self.record = record

    def runs(self):
        return (self.record,)

    def get(self, _job_id):
        return self.record


def test_refresh_recovers_submitting_before_backend_refresh():
    store = _Store(_record("submitting"))
    calls = []

    class Manager:
        def __init__(self):
            self.store = store

        def recover_submitting(self, record):
            calls.append(("recover", record.state.value))
            recovered = _record("running")
            recovered.execution = Execution(ExecutorEndpoint(), WorkingDirectory("/tmp/calc"), "pid-42")
            self.store.record = recovered
            return recovered

        def refresh(self):
            calls.append(("refresh", self.store.record.state.value))

    source = PersistentJobSource(Manager())

    jobs = source.refresh()

    assert calls == [("recover", "submitting"), ("refresh", "running")]
    assert jobs[0].state == "running"
    assert jobs[0].attachable


def test_refresh_does_not_recover_non_submitting_runs():
    store = _Store(_record("running"))
    calls = []

    class Manager:
        def __init__(self):
            self.store = store

        def recover_submitting(self, record):
            calls.append(("recover", record.state.value))

        def refresh(self):
            calls.append(("refresh", self.store.record.state.value))

    source = PersistentJobSource(Manager())

    source.refresh()

    assert calls == [("refresh", "running")]
