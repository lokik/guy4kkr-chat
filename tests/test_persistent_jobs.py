"""Persistent history adapters use current project-backed ASE2SPRKKR API."""
from __future__ import annotations

from types import SimpleNamespace
import pytest
from ase2sprkkr.execution import (
    RunState, FailurePhase, Execution, ExecutorEndpoint, WorkingDirectory, FileManifest
)
import guy4ase.gui.application.persistent_jobs as module
from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


def record(state=RunState.RUNNING, *, backend_id="pid-42", failure_phase=None, return_code=None):
    return SimpleNamespace(
        id="run-1", state=state,
        created_at="2026-10-19T10:00:00+00:00",
        updated_at="2026-10-19T11:00:00+00:00", finished_at=None,
        task="DOS", dataset="Fe-DOS", return_code=return_code,
        message=None, failure_phase=failure_phase,
        files=FileManifest(),
        execution=Execution(
            ExecutorEndpoint(executor="ssh", host="cluster", psij_backend="slurm"),
            WorkingDirectory("/tmp/calc", "/remote/calc"), backend_id=backend_id,
        ),
    )


class Store:
    def __init__(self, value):
        self.current = value
        self.calls = []
    def runs(self):
        return (self.current,)
    def get(self, run_id):
        self.calls.append(run_id)
        return self.current


def test_record_metadata_maps_canonical_backend_contract():
    job = PersistentJob.from_run_record(record())
    assert job.target == "SSH · cluster · PSI/J slurm"
    assert job.directory == "/tmp/calc"
    assert job.attachable
    assert not job.is_final


@pytest.mark.parametrize("state", (RunState.FINISHED, RunState.FAILED, RunState.CANCELLED))
def test_terminal_runs_cannot_be_attached(state):
    job = PersistentJob.from_run_record(record(state))
    assert job.is_final
    assert not job.attachable


def test_submitting_run_without_backend_identity_cannot_be_attached():
    assert not PersistentJob.from_run_record(record(RunState.SUBMITTING, backend_id=None)).attachable


def test_download_retry_is_explicit_and_requires_successful_execution():
    job = PersistentJob.from_run_record(record(RunState.FAILED, failure_phase=FailurePhase.DOWNLOAD, return_code=0))
    assert job.can_retry_download
    assert not job.attachable
    assert not PersistentJob.from_run_record(record(RunState.FAILED, failure_phase=FailurePhase.EXECUTION, return_code=1)).can_retry_download


def test_source_tracks_authoritative_changes():
    initial = record()
    store = Store(initial)
    source = PersistentJobSource(SimpleNamespace(store=store))
    assert source.jobs()[0].state == "running"
    updates = []
    source.subscribe(updates.append)
    store.current = record(RunState.FINISHED)
    source.job_changed(initial.id)
    assert updates == [initial.id]
    assert store.calls == [initial.id]
    assert source.jobs()[0].state == "finished"


def test_attach_and_load_delegate_to_backend_api(monkeypatch):
    item = record(RunState.FINISHED)
    store = Store(item)
    manager = SimpleNamespace(
        store=store, attach=lambda *args, **kwargs: None,
        retrieve_result_files=lambda x: x, check_result_files=lambda x: x,
        input_file_is_current=lambda x: True, output_file_is_current=lambda x: True,
    )
    calls = []
    result = SimpleNamespace(run_record=item)
    monkeypatch.setattr(module, "attach_project_run", lambda *args, **kwargs: calls.append("attach") or object())
    monkeypatch.setattr(module, "load_project_result", lambda *args, **kwargs: calls.append("load") or result)
    source = PersistentJobSource(manager)
    source.attach(item.id)
    assert source.load_result(item.id) is result
    assert calls == ["attach", "load"]
