"""File cleanup must be opt-in, scoped, and independent of run metadata deletion."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from kkrunner.backends import BackendConfig
from kkrunner.client import SshTransport
from kkrunner.files import CacheEntry, FileEntry, FileManifest
from kkrunner.projects import ProjectRepository
from kkrunner.runs import ExecutionMetadata, RunState, WorkingDirectory

from ase2sprkkr_gui.gui.application.imported_project_results import assign
from ase2sprkkr_gui.gui.application.persistent_jobs import PersistentJobSource
from ase2sprkkr_gui.gui.application.run_file_deletion import (
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
        expected_kinds={str(directory): "directory"},
    )
    assert plan.files == (str(own),)
    assert plan.shared == (str(shared),)
    assert plan.unsafe == (str(link),)
    assert plan.directories == (str(directory),)
    assert plan.directory_snapshots[0].kind == "directory"
    assert plan.missing == (str(missing),)
    assert plan.remote == ("/remote/own.out",)
    delete_local_files(plan.files, snapshots=plan.snapshots)
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



def test_partial_selection_removes_only_checked_files(tmp_path):
    one = tmp_path / "one.dos"
    two = tmp_path / "two.pot"
    for file in (one, two):
        file.write_text(file.name)
    run = _record(
        "run", tmp_path,
        FileManifest(outputs=(
            FileEntry(local_path=str(one)), FileEntry(local_path=str(two)),
        )),
    )
    source, store = _source(run)
    plan = source.referenced_file_deletion(run.id)
    selected = (str(one),)
    source.forget(
        run.id,
        delete_files=True,
        expected_files=selected,
        expected_file_snapshots=tuple(
            snapshot for snapshot in plan.snapshots if snapshot.path in selected
        ),
    )
    assert not one.exists()
    assert two.exists()
    assert "run" not in store.records


def test_shared_file_requires_explicit_override_and_matching_references(tmp_path):
    shared = tmp_path / "shared.pot"
    shared.write_text("shared")
    first = _record(
        "first", tmp_path, FileManifest(outputs=(FileEntry(local_path=str(shared)),)),
    )
    second = _record(
        "second", tmp_path, FileManifest(inputs=(FileEntry(local_path=str(shared)),)),
    )
    source, store = _source(first, second)
    plan = source.referenced_file_deletion(first.id)
    assert plan.files == ()
    assert plan.shared == (str(shared),)
    assert plan.referrers(str(shared)) and "second" in plan.referrers(str(shared))[0]

    with pytest.raises(RuntimeError, match="explicit confirmation"):
        source.forget(
            first.id, delete_files=True, expected_files=(str(shared),),
            expected_file_snapshots=plan.shared_snapshots,
            expected_shared_files=(str(shared),),
        )
    assert shared.exists() and "first" in store.records

    source.forget(
        first.id, delete_files=True, expected_files=(str(shared),),
        expected_file_snapshots=plan.shared_snapshots,
        expected_shared_files=(str(shared),), allow_shared_files=True,
    )
    assert not shared.exists()
    assert "first" not in store.records
    assert "second" in store.records


def test_new_other_run_reference_after_preview_forces_review(tmp_path):
    file = tmp_path / "output.dos"
    file.write_text("original")
    first = _record(
        "first", tmp_path, FileManifest(stdout=FileEntry(local_path=str(file))),
    )
    source, store = _source(first)
    plan = source.referenced_file_deletion(first.id)
    store.records["another"] = _record(
        "another", tmp_path,
        FileManifest(inputs=(FileEntry(local_path=str(file)),)),
    )
    with pytest.raises(RuntimeError, match="Shared file references changed"):
        source.forget(
            first.id, delete_files=True, expected_files=plan.files,
            expected_file_snapshots=plan.snapshots,
            allow_shared_files=True,
        )
    assert file.exists() and "first" in store.records


def test_symlink_cannot_be_selected_even_when_other_run_references_it(tmp_path):
    target = tmp_path / "result.dos"
    target.write_text("target")
    link = tmp_path / "alias.dos"
    link.symlink_to(target)
    plan = plan_file_deletion((str(link),), other_references=(str(link),))
    assert plan.selectable_files == ()
    assert plan.unsafe == (str(link),)



def test_ssh_preview_uses_manifest_and_detects_shared_remote_references(tmp_path):
    path = "/remote/directory/shared.pot"
    solo = "/remote/directory/unique.out"
    first = _record(
        "first", tmp_path,
        FileManifest(outputs=(
            FileEntry(remote_path=path),
            FileEntry(remote_path=solo),
        )),
    )
    second = _record(
        "second", tmp_path,
        FileManifest(inputs=(FileEntry(remote_path=path),)),
    )
    source, _store = _source(first, second)

    class Client:
        def inspect_remote_files(self, record, paths):
            assert set(paths) == {path, solo}
            return (
                {"path": path, "status": "ok", "mtime_ns": 5,
                 "size": 12, "device": 1, "inode": 8},
                {"path": solo, "status": "ok", "mtime_ns": 7,
                 "size": 22, "device": 1, "inode": 9},
            )

    source._manager.client_for = lambda _record: Client()
    review = source.remote_file_review(first.id)
    assert {item.path for item in review.snapshots} == {path, solo}
    assert review.shared == (path,)
    assert "second" in review.referrers_for(path)[0]


def test_ssh_cleanup_failure_does_not_prevent_local_or_history_deletion(tmp_path):
    local = tmp_path / "local.out"
    local.write_text("data")
    remote = "/remote/directory/output.out"
    run = _record(
        "run", tmp_path,
        FileManifest(outputs=(
            FileEntry(local_path=str(local), remote_path=remote),
        )),
    )
    source, store = _source(run)

    class OfflineClient:
        def inspect_remote_files(self, record, paths):
            return ({"path": remote, "status": "ok", "mtime_ns": 5,
                     "size": 12, "device": 1, "inode": 8},)

        def delete_remote_files(self, record, expected):
            raise ConnectionError("SSH unreachable")

    source._manager.client_for = lambda _record: OfflineClient()
    review = source.remote_file_review(run.id)
    plan = source.referenced_file_deletion(run.id)
    record = source.capture_remote_cleanup(run.id)
    source.forget(
        run.id, delete_files=True, expected_files=plan.files,
        expected_file_snapshots=plan.snapshots,
    )
    assert not local.exists()
    assert run.id not in store.records

    replies = source.cleanup_remote_files(record, review, (remote,))
    assert replies[0]["status"] == "skipped"
    assert "SSH unreachable" in replies[0]["message"]


def test_ssh_cleanup_skips_newly_shared_file_without_affecting_other_files(tmp_path):
    first_path = "/remote/directory/first.out"
    second_path = "/remote/directory/second.out"
    run = _record(
        "run", tmp_path,
        FileManifest(outputs=(
            FileEntry(remote_path=first_path),
            FileEntry(remote_path=second_path),
        )),
    )
    source, store = _source(run)
    calls = []

    class Client:
        def inspect_remote_files(self, record, paths):
            return tuple(
                {"path": path, "status": "ok", "mtime_ns": 5,
                 "size": 12, "device": 1, "inode": 8}
                for path in paths
            )

        def delete_remote_files(self, record, expected):
            calls.append(expected)
            return tuple(
                {"path": path, "status": "deleted"} for path in expected
            )

    source._manager.client_for = lambda _record: Client()
    review = source.remote_file_review(run.id)
    record = source.capture_remote_cleanup(run.id)
    store.records["later"] = _record(
        "later", tmp_path,
        FileManifest(inputs=(FileEntry(remote_path=first_path),)),
    )
    source.forget(run.id)
    results = source.cleanup_remote_files(
        record, review, (first_path, second_path),
    )
    assert len(calls) == 1 and tuple(calls[0]) == (second_path,)
    assert {item["status"] for item in results} == {"skipped", "deleted"}



def test_declared_local_directory_is_deleted_recursively(tmp_path):
    taudir = tmp_path / "scratch" / "tau"
    (taudir / "nested").mkdir(parents=True)
    (taudir / "nested" / "Fe.tau").write_text("tau")
    (taudir / "save.dat").write_text("save")
    outside = tmp_path / "scratch" / "other-run.out"
    outside.write_text("keep")
    run = _record(
        "run", tmp_path,
        FileManifest(outputs=(FileEntry(local_path=str(taudir), kind="directory"),)),
    )
    source, store = _source(run)
    plan = source.referenced_file_deletion("run")
    assert plan.directories == (str(taudir),)
    assert len(plan.directory_snapshots[0].contents) == 3
    source.forget(
        "run", delete_files=True, expected_files=(str(taudir),),
        expected_file_snapshots=plan.directory_snapshots,
    )
    assert not taudir.exists() and outside.exists()
    assert "run" not in store.records


def test_declared_directory_becomes_shared_when_other_run_uses_descendant(tmp_path):
    taudir = tmp_path / "tau"
    taudir.mkdir()
    used = taudir / "used.tau"
    used.write_text("in use")
    first = _record(
        "first", tmp_path,
        FileManifest(outputs=(FileEntry(local_path=str(taudir), kind="directory"),)),
    )
    other = _record(
        "second", tmp_path,
        FileManifest(inputs=(FileEntry(local_path=str(used)),)),
    )
    source, store = _source(first, other)
    plan = source.referenced_file_deletion("first")
    assert plan.directories == ()
    assert plan.shared_directories == (str(taudir),)
    assert "second" in plan.referrers(str(taudir))[0]
    with pytest.raises(RuntimeError, match="explicit confirmation"):
        source.forget(
            "first", delete_files=True,
            expected_files=(str(taudir),),
            expected_file_snapshots=plan.shared_directory_snapshots,
            expected_shared_files=(str(taudir),),
        )
    assert taudir.exists() and "first" in store.records


def test_directory_changed_after_confirmation_is_not_deleted(tmp_path):
    taudir = tmp_path / "tau"
    taudir.mkdir()
    (taudir / "original.tau").write_text("before")
    run = _record(
        "run", tmp_path,
        FileManifest(outputs=(FileEntry(local_path=str(taudir), kind="directory"),)),
    )
    source, store = _source(run)
    plan = source.referenced_file_deletion("run")
    (taudir / "unexpected.tau").write_text("new file")
    with pytest.raises(RuntimeError, match="last-modified times"):
        source.forget(
            "run", delete_files=True,
            expected_files=plan.directories,
            expected_file_snapshots=plan.directory_snapshots,
        )
    assert (taudir / "unexpected.tau").exists()
    assert "run" in store.records


def test_remote_directory_review_and_recursive_delete_identity(tmp_path):
    taudir = "/remote/path/TAUDIR"
    record = _record(
        "run", tmp_path, FileManifest(outputs=(FileEntry(remote_path=taudir, kind="directory"),)),
    )
    source, store = _source(record)
    children = [{
        "path": taudir + "/Fe.tau", "kind": "file", "mtime_ns": 2,
        "size": 5, "device": 1, "inode": 2,
    }]
    recorded = []

    class Client:
        def inspect_remote_files(self, _record, paths):
            assert paths == (taudir,)
            return ({
                "path": taudir, "status": "ok", "kind": "directory",
                "mtime_ns": 1, "size": 4, "device": 1, "inode": 1,
                "contents": children,
            },)

        def delete_remote_files(self, _record, expected):
            recorded.append(expected)
            return ({"path": taudir, "status": "deleted"},)

    source._manager.client_for = lambda record: Client()
    review = source.remote_file_review("run")
    assert review.snapshots[0].kind == "directory"
    assert len(review.snapshots[0].contents) == 1
    captured = source.capture_remote_cleanup("run")
    source.forget("run")
    response = source.cleanup_remote_files(captured, review, (taudir,))
    assert response[0]["status"] == "deleted"
    assert recorded[0][taudir]["kind"] == "directory"
    assert recorded[0][taudir]["contents"] == children



def test_cleanup_rejects_declared_kind_mismatch(tmp_path):
    declared_file = tmp_path / "misleading.dir"
    declared_file.mkdir()
    declared_directory = tmp_path / "TAUDIR"
    declared_directory.write_text("ordinary data")
    run = _record(
        "run", tmp_path,
        FileManifest(outputs=(
            FileEntry(local_path=str(declared_file), kind="file"),
            FileEntry(local_path=str(declared_directory), kind="directory"),
        )),
    )
    source, _store = _source(run)
    plan = source.referenced_file_deletion(run.id)
    assert plan.selectable_files == ()
    assert set(plan.unsafe) == {str(declared_file), str(declared_directory)}
    assert declared_file.is_dir() and declared_directory.is_file()
