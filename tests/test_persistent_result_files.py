"""Result-file freshness checks for persistent calculation history."""
from __future__ import annotations

from kkrunner.runs import ExecutionMetadata, WorkingDirectory
from kkrunner.transports import LocalTransport
from types import SimpleNamespace

from ase2sprkkr_gui.gui.application.persistent_jobs import PersistentJob, PersistentJobSource


def _record(*, result_files=None):
    return SimpleNamespace(
        id="1234567890abcdef",
        state="finished",
        created_at="2026-10-13T06:00:00+00:00",
        updated_at="2026-10-13T06:30:00+00:00",
        finished_at="2026-10-13T06:20:00+00:00",
        metadata={"ase2sprkkr": {"task": "DOS", "dataset": "Fe-DOS"}},
        execution=ExecutionMetadata(LocalTransport(), WorkingDirectory("/tmp/calc")),
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


def test_gui_adoption_preserves_historical_auxiliary_file_identity(tmp_path):
    from ase2sprkkr.outputs.task_result import TaskResult
    from kkrunner.files import FileEntry, FileManifest, FileVersion

    from ase2sprkkr_gui.gui.application.result_loading import load_result
    from ase2sprkkr_gui.gui.application.result_store import ResultStore

    output, auxiliary, potential = (tmp_path / name for name in ("run.out", "curve.agr", "run.pot"))
    output.write_text("old OUT")
    auxiliary.write_text("@type xy\n0 1\n&\n")
    potential.write_text("old potential")
    versions = tuple(FileVersion.capture(path, require_digest=True)
                     for path in (output, auxiliary, potential))
    result = TaskResult(None, None, str(tmp_path), output_file=str(output), task_name="DOS")
    result.files.add_file("curve", str(auxiliary), "agr")
    result.files.add_file("potential", str(potential))
    result.run_record = _record(result_files=FileManifest(
        stdout=FileEntry(str(output)), output_versions=versions,
        captured_at="2026-11-16T00:00:00+00:00",
    ))
    auxiliary.write_text("@type xy\n0 999\n&\n")
    potential.write_text("new potential")

    loaded = load_result(result, fallback_directory=None)
    assert loaded.atoms is None
    assert "changed" in str(loaded.potential_error)
    record = ResultStore().add_result(
        result, structure_id=None, input_state_id=None, input_parameters=None,
        directory=str(tmp_path), output_path=output,
    )
    assert record.output_version == versions[0]
    assert record.result_files["curve"] == versions[1]
    assert record.result_files["potential"] == versions[2]
    assert record.result_files["curve"].state().value == "overwritten"
    assert result.files["curve"].actions() == ()


def test_unavailable_execution_keeps_local_history_visible(tmp_path):
    from dataclasses import replace

    from kkrunner.backends import BackendConfig
    from kkrunner.transports import transport_from_dict

    record = _record()
    record.execution = replace(
        record.execution, backend=BackendConfig("unknown-backend"),
        transport=transport_from_dict({"kind": "unknown-connection", "host": "old-host"}),
        backend_id="saved-id",
    )
    record.state = "running"
    job = PersistentJob.from_run_record(record)
    assert not job.attachable
    assert not job.cancelable
    assert "unavailable" in job.target


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
            return checked

    source = PersistentJobSource(SimpleNamespace(store=Store()))

    listed = source.jobs()[0]
    verified = source.check_result_files(stored.id)

    assert listed.result_files_state == "current"
    assert not listed.result_files_verified
    assert verified.result_files_state == "overwritten"
    assert verified.result_files_verified
    assert source.supports_result_file_check


def test_result_file_check_uses_persisted_store():
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

    assert source.supports_result_file_check
    assert source.check_result_files(record.id).result_files_verified

def test_result_file_check_detects_changed_historical_output(tmp_path):
    from kkrunner.files import FileEntry, FileManifest, FileVersion

    output = tmp_path / "result.out"
    output.write_text("before")
    record = _record(result_files=FileManifest(
        stdout=FileEntry(local_path=str(output)),
        output_versions=(FileVersion.capture(output, require_digest=True),),
        captured_at="2026-10-22T12:00:00+00:00",
    ))

    class Store:
        def runs(self):
            return (record,)

        def get(self, run_id):
            assert run_id == record.id
            return record

    source = PersistentJobSource(SimpleNamespace(store=Store()))
    output.write_text("after")
    checked = source.check_result_files(record.id)
    assert checked.result_files_state == "overwritten"
    assert checked.result_files_verified
