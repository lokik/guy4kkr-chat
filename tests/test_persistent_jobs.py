"""Persistent history adapters use current project-backed ASE2SPRKKR API."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import os
from types import SimpleNamespace
import pytest
from kkrunner.runs import RunState, FailurePhase, ExecutionMetadata, WorkingDirectory
from kkrunner.client import SshTransport
from kkrunner.backends import BackendConfig
from kkrunner.files import FileManifest, FileEntry
import guy4ase.gui.application.persistent_jobs as module
from guy4ase.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


def record(state=RunState.RUNNING, *, backend_id="pid-42", failure_phase=None, return_code=None):
    return SimpleNamespace(
        id="run-1", state=state,
        created_at="2026-10-19T10:00:00+00:00",
        updated_at="2026-10-19T11:00:00+00:00", finished_at=None,
        metadata={"ase2sprkkr": {"task": "DOS", "dataset": "Fe-DOS"}},
        return_code=return_code,
        message=None, failure_phase=failure_phase,
        files=FileManifest(),
        execution=ExecutionMetadata(
            SshTransport(host="cluster"),
            WorkingDirectory("/tmp/calc", "/remote/calc"), backend_id=backend_id,
            backend=BackendConfig(name="psij", options={"executor_name": "slurm"}),
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
    calls = []
    result = SimpleNamespace(run_record=item)
    manager = SimpleNamespace(
        store=store,
        attach=lambda *args, **kwargs: None,
        retrieve_result_files=lambda *_args: None,
    )
    monkeypatch.setattr(module, "attach_project_run", lambda _manager, ref, **kwargs: calls.append("attach") or object())
    monkeypatch.setattr(module, "load_project_result", lambda _manager, ref: calls.append("load") or result)
    source = PersistentJobSource(manager)
    assert source.supports_results
    assert source.supports_result_file_check
    source.attach(item.id)
    assert source.load_result(item.id) is result
    assert calls == ["attach", "load"]

def test_postprocessing_retry_requires_successful_execution():
    ready = PersistentJob.from_run_record(
        record(RunState.FAILED, failure_phase=FailurePhase.POSTPROCESSING, return_code=0)
    )
    assert ready.can_retry_postprocessing
    assert not PersistentJob.from_run_record(
        record(RunState.FAILED, failure_phase=FailurePhase.EXECUTION, return_code=1)
    ).can_retry_postprocessing
    assert not PersistentJob.from_run_record(record(RunState.FINISHED)).can_retry_postprocessing


def test_history_excludes_records_from_other_applications():
    foreign = record(RunState.FINISHED)
    foreign.metadata = {"other_application": {"task": "DOS"}}
    source = PersistentJobSource(SimpleNamespace(store=Store(foreign)))
    assert source.jobs() == ()
    assert source.job_changed(foreign.id) is None


def test_explicit_postprocessing_retry_delegates_to_application(monkeypatch):
    item = record(RunState.FAILED, failure_phase=FailurePhase.POSTPROCESSING, return_code=0)
    store = Store(item)
    manager = SimpleNamespace(store=store, retry_postprocessing=lambda *_args: None)
    calls = []
    expected = object()

    def retry(received_manager, run_id):
        calls.append((received_manager, run_id))
        return expected

    monkeypatch.setattr(module, "retry_project_postprocessing", retry)
    source = PersistentJobSource(manager)
    assert source.supports_retry_postprocessing
    assert source.retry_postprocessing(item.id) is expected
    assert calls == [(manager, item.id)]
    assert store.calls == [item.id]

def test_unknown_supervised_ssh_run_can_be_reattached_after_restart():
    item = record(RunState.UNKNOWN)
    item.execution = replace(item.execution, backend=BackendConfig("process"))
    restored = PersistentJob.from_run_record(item)
    assert restored.attachable
    assert restored.reattach_unavailable_reason is None
    assert not restored.is_final


def test_unknown_direct_ssh_run_explains_why_it_cannot_be_reattached():
    item = record(RunState.UNKNOWN)
    item.execution = replace(item.execution, backend=BackendConfig("direct"))
    restored = PersistentJob.from_run_record(item)
    assert not restored.attachable
    assert "no saved output" in restored.reattach_unavailable_reason.lower()
    assert not restored.cancelable
    assert "verified PID" in restored.cancel_unavailable_reason


def test_submitting_run_explains_missing_backend_identity():
    restored = PersistentJob.from_run_record(
        record(RunState.SUBMITTING, backend_id=None)
    )
    assert not restored.attachable
    assert "Refresh statuses" in restored.reattach_unavailable_reason


def test_profile_comes_from_ase2sprkkr_metadata():
    item = record()
    item.metadata["ase2sprkkr"]["profile"] = "deleted-cluster"
    assert PersistentJob.from_run_record(item).profile == "deleted-cluster"

    # Explicitly unnamed profiles and legacy records have the same representation.
    item.metadata["ase2sprkkr"]["profile"] = None
    assert PersistentJob.from_run_record(item).profile is None
    item.metadata["ase2sprkkr"].pop("profile")
    assert PersistentJob.from_run_record(item).profile is None


def test_direct_run_with_saved_output_can_monitor_and_safely_cancel():
    item = record(RunState.UNKNOWN, backend_id="direct:42:137:00000000-0000-0000-0000-000000000000")
    item.execution = replace(item.execution, backend=BackendConfig("direct"))
    item.files = FileManifest(stdout=FileEntry(
        local_path="/tmp/calc/stdout.txt", remote_path="/remote/calc/stdout.txt",
    ))
    job = PersistentJob.from_run_record(item)
    assert job.attachable
    assert job.cancelable
    assert job.reattach_unavailable_reason is None


def test_source_cancel_and_forget_delegate_to_manager():
    item = record(RunState.UNKNOWN)
    store = Store(item)
    calls = []

    def forget(job_id, *, force=False):
        calls.append(("forget", job_id, force))
        store.current = None
        return item

    store.runs = lambda: (() if store.current is None else (store.current,))

    def get(job_id):
        if store.current is None:
            raise FileNotFoundError(job_id)
        return store.current

    store.get = get
    manager = SimpleNamespace(
        store=store,
        cancel=lambda job_id: calls.append(("cancel", job_id)),
        forget=forget,
    )
    source = PersistentJobSource(manager)
    assert source.supports_cancel
    assert source.supports_forget
    assert source.cancel(item.id) is not None
    source.forget(item.id, force=True)
    assert source.job(item.id) is None
    assert calls == [("cancel", item.id), ("forget", item.id, True)]


def test_file_only_results_join_project_history_without_fake_run(tmp_path, monkeypatch):
    from kkrunner.projects import ProjectRepository
    from guy4ase.gui.application.imported_project_results import assign

    projects = ProjectRepository(tmp_path / "projects")
    first = projects.create("First")
    second = projects.create("Second")
    output = tmp_path / "old-calculation.out"
    output.write_text("external calculation")
    finished = datetime(2025, 7, 18, 13, 42, 25, tzinfo=timezone.utc)
    os.utime(output, (finished.timestamp(), finished.timestamp()))
    assert assign(
        projects, [SimpleNamespace(output_path=output, output_version=None)], first.id
    ) == 1

    manager = SimpleNamespace(store=Store(record(RunState.FINISHED)))
    source = PersistentJobSource(manager, projects=projects)
    imported = next(job for job in source.jobs() if job.imported_path is not None)
    assert imported.id.startswith("external:")
    assert imported.dataset == "old-calculation.out"
    assert imported.project_id == first.id
    assert imported.state == "imported"
    assert imported.finished_at == finished.isoformat()
    assert imported.created_at == finished.isoformat()
    assert imported.is_final
    assert imported.return_code is None
    assert not imported.attachable
    assert not imported.cancelable

    expected_result = object()
    monkeypatch.setattr(
        module, "load_result_file",
        lambda path: SimpleNamespace(result=expected_result),
    )
    assert source.load_result(imported.id) is expected_result

    source.reassign_runs(
        projects, (imported.id,), second.id,
        expected_project_ids={imported.id: first.id},
    )
    assert source.job(imported.id).project_id == second.id

    source.forget(imported.id)
    assert source.job(imported.id) is None
    assert output.exists()


def test_missing_imported_file_remains_visible_for_removal(tmp_path):
    from kkrunner.projects import ProjectRepository
    from guy4ase.gui.application.imported_project_results import assign

    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    path = tmp_path / "missing.out"
    path.write_text("temporary")
    assign(projects, [SimpleNamespace(output_path=path, output_version=None)], project.id)
    path.unlink()

    source = PersistentJobSource(
        SimpleNamespace(store=Store(record(RunState.FINISHED))), projects=projects,
    )
    imported = next(job for job in source.jobs() if job.imported_path is not None)
    assert imported.result_files_state == "missing"
    assert imported.finished_at is None
    assert imported.is_final
    source.forget(imported.id)
    assert all(job.imported_path is None for job in source.jobs())
