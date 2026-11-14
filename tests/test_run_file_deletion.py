"""File cleanup must be opt-in, scoped, and independent of run metadata deletion."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from kkrunner.backends import BackendConfig
from kkrunner.client import SshTransport
from kkrunner.files import CacheEntry, FileEntry, FileManifest
from kkrunner.projects import ProjectRepository
from kkrunner.runs import ExecutionMetadata, RunState, WorkingDirectory

from guy4ase.gui.application.imported_project_results import assign
from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from guy4ase.gui.application.run_file_deletion import (
    delete_local_files, plan_file_deletion, referenced_local_paths,
)


class Store:
    def __init__(self, *records):
        self.records = {record.id: record for record in records}

    def runs(self):
        return tuple(self.records.values())

    def get(self, ref):
        return self.records[ref]


def _record(ref, directory, files, state=RunState.FINISHED):
    return SimpleNamespace(
        id=ref,
        state=state,
        created_at="2026-11-01T00:00:00+00:00",
        updated_at="2026-11-01T01:00:00+00:00",
        finished_at="2026-11-01T01:00:00+00:00",
        return_code=0,
        failure_phase=None,
        message=None,
        metadata={"ase2sprkkr": {"task": "DOS", "dataset": ref}},
        files=files,
        execution=ExecutionMetadata(
            SshTransport(host="cluster"),
            WorkingDirectory(str(directory), "/remote/directory"),
            backend=BackendConfig("psij", options={"executor_name": "slurm"}),
        ),
    )


def _source(*records, projects=None):
    store = Store(*records)
    def forget(ref, *, force=False):
        return store.records.pop(ref)
    return PersistentJobSource(
        SimpleNamespace(store=store, forget=forget), projects=projects,
    ), store


def test_plan_covers_inputs_outputs_caches_and_streams(tmp_path):
    paths = [tmp_path / name for name in ("in.inp", "out.dos", "cache.pot", "stderr.log")]
    for path in paths:
        path.write_text("test")
    manifest = FileManifest(
        inputs=(FileEntry(local_path=str(paths[0])),),
        outputs=(FileEntry(local_path=str(paths[1])),),
        caches=(CacheEntry(file=FileEntry(local_path=str(paths[2]))),),
        stderr=FileEntry(local_path=str(paths[3])),
        stdout=FileEntry(local_path=str(paths[1])),
    )
    assert referenced_local_paths(manifest, str(tmp_path)) == tuple(sorted(map(str, paths)))


def test_plan_skips_shared_symlinks_directories_and_missing_files(tmp_path):
    own = tmp_path / "own.out"
    shared = tmp_path / "shared.pot"
    missing = tmp_path / "missing.dos"
    directory = tmp_path / "folder"
    directory.mkdir()
    for path in (own, shared):
        path.write_text("data")
    link = tmp_path / "link.out"
    link.symlink_to(own)
    plan = plan_file_deletion(
        (str(own), str(shared), str(link), str(directory), str(missing)),
        other_references=(str(shared),),
        remote_references=("/remote/own.out",),
    )
    assert plan.files == (str(own),)
    assert plan.shared == (str(shared),)
    assert set(plan.unsafe) == {str(link), str(directory)}
    assert plan.missing == (str(missing),)
    assert plan.remote == ("/remote/own.out",)
    delete_local_files(plan.files)
    assert not own.exists()
    assert shared.exists() and link.is_symlink() and directory.exists()


def test_run_cleanup_keeps_files_referenced_by_other_runs(tmp_path):
    own = tmp_path / "own.dos"
    shared = tmp_path / "shared.pot"
    own.write_text("own")
    shared.write_text("shared")
    first = _record(
        "first", tmp_path,
        FileManifest(
            inputs=(FileEntry(local_path=str(shared)),),
            stdout=FileEntry(local_path=str(own), remote_path="/remote/own.dos"),
        ),
    )
    second = _record(
        "second", tmp_path,
        FileManifest(inputs=(FileEntry(local_path=str(shared)),)),
    )
    source, store = _source(first, second)
    plan = source.referenced_file_deletion("first")
    assert plan.files == (str(own),)
    assert plan.shared == (str(shared),)
    assert "/remote/own.dos" in plan.remote

    source.forget(
        "first", delete_files=True, expected_files=plan.files,
        expected_file_snapshots=plan.snapshots,
    )
    assert not own.exists()
    assert shared.exists()
    assert "first" not in store.records
    assert source.job("first") is None


def test_cleanup_requires_confirmed_current_preview(tmp_path):
    output = tmp_path / "one.out"
    output.write_text("data")
    first = _record(
        "first", tmp_path, FileManifest(stdout=FileEntry(local_path=str(output))),
    )
    source, store = _source(first)
    plan = source.referenced_file_deletion(first.id)
    with pytest.raises(ValueError, match="confirmed"):
        source.forget(first.id, delete_files=True)
    assert output.exists()

    store.records["second"] = _record(
        "second", tmp_path, FileManifest(inputs=(FileEntry(local_path=str(output)),)),
    )
    with pytest.raises(RuntimeError, match="changed since confirmation"):
        source.forget(
            first.id, delete_files=True, expected_files=plan.files,
            expected_file_snapshots=plan.snapshots,
        )
    assert output.exists()
    assert "first" in store.records


def test_run_record_only_keeps_referenced_files(tmp_path):
    output = tmp_path / "one.out"
    output.write_text("data")
    first = _record(
        "first", tmp_path, FileManifest(stdout=FileEntry(local_path=str(output))),
    )
    source, store = _source(first)
    source.forget(first.id)
    assert output.exists()
    assert "first" not in store.records


def test_imported_result_can_delete_its_file_but_not_other_references(tmp_path):
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    output = tmp_path / "old.out"
    output.write_text("imported")
    assign(
        projects, [SimpleNamespace(output_path=output, output_version=None)],
        project.id,
    )
    source, _store = _source(projects=projects)
    imported = next(job for job in source.jobs() if job.imported_path is not None)
    plan = source.referenced_file_deletion(imported.id)
    assert plan.files == (str(output),)
    source.forget(
        imported.id, delete_files=True, expected_files=plan.files,
        expected_file_snapshots=plan.snapshots,
    )
    assert not output.exists()
    assert source.job(imported.id) is None


def test_imported_reference_cannot_delete_a_tracked_runs_file(tmp_path):
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    output = tmp_path / "saved.out"
    output.write_text("run")
    assign(
        projects, [SimpleNamespace(output_path=output, output_version=None)],
        project.id,
    )
    run = _record("run", tmp_path, FileManifest(stdout=FileEntry(local_path=str(output))))
    source, _store = _source(run, projects=projects)
    imported = next(job for job in source.jobs() if job.imported_path is not None)
    plan = source.referenced_file_deletion(imported.id)
    assert plan.files == ()
    assert plan.shared == (str(output),)
    source.forget(imported.id)
    assert output.exists()


def test_file_changed_since_confirmation_cannot_be_deleted(tmp_path):
    output = tmp_path / "important.out"
    output.write_text("before")
    first = _record("run", tmp_path, FileManifest(stdout=FileEntry(local_path=str(output))))
    source, store = _source(first)
    old_plan = source.referenced_file_deletion(first.id)
    output.write_text("contents replaced after dialog opened")
    with pytest.raises(RuntimeError, match="last-modified times"):
        source.forget(
            first.id, delete_files=True, expected_files=old_plan.files,
            expected_file_snapshots=old_plan.snapshots,
        )
    assert output.read_text() == "contents replaced after dialog opened"
    assert "run" in store.records
