"""Automatic recovery only for interrupted postprocessing and downloads."""
from types import SimpleNamespace
import guy4ase.gui.application.persistent_jobs as module
from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from ase2sprkkr.execution import RunState, Execution, ExecutorEndpoint, WorkingDirectory, FileManifest

def _record(state=RunState.POSTPROCESSING):
    return SimpleNamespace(
        id="run-1", state=state,
        created_at="2026-10-19T10:00:00+00:00",
        updated_at="2026-10-19T10:01:00+00:00",
        finished_at=None, task="DOS", dataset=None,
        return_code=0, message=None, failure_phase=None,
        files=FileManifest(),
        execution=Execution(ExecutorEndpoint(), WorkingDirectory("/tmp/calc"), "pid-42"),
    )

class Store:
    def __init__(self, rec): self.record = rec
    def runs(self): return (self.record,)
    def get(self, value): return self.record

def test_recovery_failure_updates_terminal_metadata(monkeypatch):
    store = Store(_record())
    manager = SimpleNamespace(store=store, attach=lambda *args, **kw: None)
    def attach(*args, **kwargs):
        store.record = _record(RunState.FAILED)
        store.record.message = "cannot reconstruct historical result"
        raise RuntimeError(store.record.message)
    monkeypatch.setattr(module, "attach_project_run", attach)
    source = PersistentJobSource(manager)
    assert source.active_recovery_ids == ()
    assert source.job("run-1").state == "failed"
    assert source.job("run-1").message == "cannot reconstruct historical result"

def test_transient_recovery_failure_does_not_recurse(monkeypatch):
    manager = SimpleNamespace(store=Store(_record()), attach=lambda *args, **kw: None)
    calls = []
    def attach(*args, **kwargs):
        calls.append(1)
        raise OSError("connection lost")
    monkeypatch.setattr(module, "attach_project_run", attach)
    source = PersistentJobSource(manager)
    assert calls == [1]
    assert source.active_recovery_ids == ()
    assert source.job("run-1").state == "postprocessing"
