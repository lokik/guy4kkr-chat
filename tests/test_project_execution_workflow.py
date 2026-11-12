"""Regression for the ASE2SPRKKR project-run public contract."""
from __future__ import annotations

from types import SimpleNamespace
from ase2sprkkr.execution import Execution, ExecutorEndpoint, WorkingDirectory, FileManifest, RunState, FailurePhase
from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource
from guy4ase.gui.application import persistent_jobs as jobs_module


def record(state=RunState.RUNNING, *, phase=None, code=None, backend_id="backend-42"):
    return SimpleNamespace(
        id="project-run-1", state=state, created_at="2026-10-19T10:00:00+00:00",
        updated_at="2026-10-19T10:01:00+00:00", finished_at=None,
        task="DOS", dataset=None, return_code=code, message=None,
        failure_phase=phase, files=FileManifest(),
        execution=Execution(
            ExecutorEndpoint(executor="ssh", host="cluster.example"),
            WorkingDirectory("/tmp/project", "/scratch/run"),
            backend_id=backend_id,
        ),
    )


def test_record_uses_authoritative_execution_and_files():
    job = PersistentJob.from_run_record(record())
    assert job.target == "SSH · cluster.example"
    assert job.directory == "/tmp/project"
    assert job.attachable
    assert not job.is_final


def test_only_completed_execution_download_can_be_retried():
    job = PersistentJob.from_run_record(record(RunState.FAILED, phase=FailurePhase.DOWNLOAD, code=0))
    assert job.is_final
    assert job.can_retry_download
    assert not job.attachable
    assert not PersistentJob.from_run_record(
        record(RunState.FAILED, phase=FailurePhase.EXECUTION, code=1)
    ).can_retry_download


def test_attach_and_result_loading_delegate_to_backend():
    item = record(RunState.FINISHED)

    class Store:
        def runs(self):
            return (item,)

        def get(self, job_id):
            assert job_id == item.id
            return item

    calls = []
    runner = object()
    result = SimpleNamespace(run_record=item)
    manager = SimpleNamespace(
        store=Store(),
        attach_sprkkr=lambda ref, **kwargs: calls.append(("attach", ref)) or runner,
        load_result=lambda ref: calls.append(("load", ref)) or result,
    )
    source = PersistentJobSource(manager)
    assert source.attach(item.id) is runner
    assert source.load_result(item.id) is result
    assert calls == [("attach", item.id), ("load", item.id)]
