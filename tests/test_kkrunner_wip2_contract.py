"""Integration contracts with the KKRunner wip2 record and project APIs."""

from dataclasses import replace

from kkrunner.backends import BackendConfig
from kkrunner.client import LocalTransport, SshTransport
from kkrunner.projects import ProjectRepository, ProjectRunManager
from kkrunner.runs import RunState

from ase2sprkkr_gui.gui.application.persistent_jobs import (
    PersistentJob,
    project_run_manager,
)


def test_project_manager_uses_explicit_repository_and_shared_store(tmp_path):
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    manager = project_run_manager(projects)
    assert isinstance(manager, ProjectRunManager)
    assert manager.store.directory == tmp_path / "projects_runs"
    bound = manager.for_project(project.id)
    record = bound.new_record(
        directory=tmp_path,
        metadata={"ase2sprkkr": {
            "task": "SCF",
            "dataset": "Fe",
            "input_definition": "SCF",
        }},
        transport=LocalTransport(),
        backend=BackendConfig("process"),
    )
    assert record.project_id == project.id
    job = PersistentJob.from_run_record(record)
    assert job.task == "SCF"
    assert job.dataset == "Fe"
    assert job.target == "Local · supervised"
    assert not job.attachable

    attached = replace(record, state=RunState.RUNNING,
                       execution=record.execution.submitted("native-id"))
    assert PersistentJob.from_run_record(attached).attachable


def test_direct_runs_are_not_reported_as_reattachable(tmp_path):
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    manager = project_run_manager(projects).for_project(project)
    record = manager.new_record(
        directory=tmp_path,
        transport=SshTransport(host="cluster.example"),
        backend=BackendConfig("direct"),
        metadata={"ase2sprkkr": {"task": "DOS"}},
    )
    running = replace(record, state=RunState.RUNNING,
                      execution=record.execution.submitted("pid:timestamp"))
    job = PersistentJob.from_run_record(running)
    assert job.target == "SSH · cluster.example"
    assert not job.attachable
    assert job.task == "DOS"
