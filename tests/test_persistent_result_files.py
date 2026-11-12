"""Result-file freshness checks for persistent calculation history."""
from __future__ import annotations

from ase2sprkkr.execution import Execution, ExecutorEndpoint, WorkingDirectory
from types import SimpleNamespace

from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


def _record(*, result_files=None):
    return SimpleNamespace(
        id="1234567890abcdef",
        state="finished",
        created_at="2026-10-13T06:00:00+00:00",
        updated_at="2026-10-13T06:30:00+00:00",
        finished_at="2026-10-13T06:20:00+00:00",
        task="dos",
        execution=Execution(ExecutorEndpoint(), WorkingDirectory("/tmp/calc")),
        dataset="Fe-DOS",
        failure_phase=None,
        return_code=0,
        message=None,
        files=result_files,
    )


def test_result_file_state_is_exposed():
    record = _record(
        result_files=SimpleNamespace(state=SimpleNamespace(value="overwritten")),
    )

    job = PersistentJob.from_run_record(record)

    assert job.result_files_state == "overwritten"
    assert not job.result_files_verified


def test_explicit_result_file_check_marks_state_as_verified():
    stored = _record(
        result_files=SimpleNamespace(state=SimpleNamespace(value="current")),
    )
    checked = _record(
        result_files=SimpleNamespace(state=SimpleNamespace(value="overwritten")),
    )

    class Store:
        @staticmethod
        def runs():
            return (stored,)

        @staticmethod
        def get(run_id):
            assert run_id == stored.id
            return stored

    class Manager:
        store = Store()

        def __init__(self):
            self.checked = []

        def check_result_files(self, run_id):
            self.checked.append(run_id)
            return checked

    manager = Manager()
    source = PersistentJobSource(manager)

    listed = source.jobs()[0]
    verified = source.check_result_files(stored.id)

    assert listed.result_files_state == "current"
    assert not listed.result_files_verified
    assert verified.result_files_state == "overwritten"
    assert verified.result_files_verified
    assert manager.checked == [stored.id]


def test_result_file_check_requires_backend_operation():
    record = _record(
        result_files=SimpleNamespace(state=SimpleNamespace(value="current")),
    )

    class Store:
        @staticmethod
        def runs():
            return (record,)

        @staticmethod
        def get(run_id):
            assert run_id == record.id
            return record

    source = PersistentJobSource(SimpleNamespace(store=Store()))

    assert not source.supports_result_file_check
