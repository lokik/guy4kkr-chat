"""Qt tests for project-to-persistent-job browsing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox, QTreeWidgetItem
from ase2sprkkr.execution import ProjectRepository, ProjectRepositoryError

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog


def _job(job_id: str, *, dataset: str) -> PersistentJob:
    return PersistentJob(
        id=job_id,
        state="finished",
        created_at="2026-10-13T08:00:00+00:00",
        updated_at="2026-10-13T08:45:00+00:00",
        finished_at="2026-10-13T08:45:00+00:00",
        task="DOS",
        directory=f"/tmp/{job_id}",
        dataset=dataset,
        target="Local",
        return_code=0,
        message=None,
        result_files_state="current",
    )


class _JobSource:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = False
    supports_attach = False
    supports_retry_finalization = False
    supports_result_file_check = False

    def __init__(self, jobs):
        self._jobs = tuple(jobs)
        self._listeners = []

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def jobs(self):
        return self._jobs

    def job(self, job_id):
        return next((job for job in self._jobs if job.id == job_id), None)

    def replace_jobs(self, jobs, changed_id):
        self._jobs = tuple(jobs)
        for listener in tuple(self._listeners):
            listener(changed_id)

    def refresh(self):
        return self._jobs

    def job_changed(self, job_id):
        for listener in tuple(self._listeners):
            listener(job_id)
        return self.job(job_id)


def _dialog(repository, source):
    return ProjectBrowserDialog(repository, PersistentJobsController(source))


def _find_project_item(dialog: ProjectBrowserDialog, label: str) -> QTreeWidgetItem:
    pending = [
        dialog.project_tree.topLevelItem(index)
        for index in range(dialog.project_tree.topLevelItemCount())
    ]
    while pending:
        item = pending.pop(0)
        if item.text(0) == label:
            return item
        pending.extend(item.child(index) for index in range(item.childCount()))
    raise AssertionError(f"Project {label!r} not found")


def test_project_browser_uses_parent_hierarchy_and_direct_run_membership(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    root = repository.create("Root")
    root = repository.save(
        root.add_run("parent-run"), expected_generation=root.generation
    )
    child = repository.create("Child", parent_id=root.id)
    repository.save(
        child.add_run("child-run"), expected_generation=child.generation
    )
    source = _JobSource(
        (
            _job("parent-run", dataset="Parent"),
            _job("child-run", dataset="Child"),
        )
    )

    dialog = _dialog(repository, source)

    root_item = _find_project_item(dialog, "Root")
    assert root_item.child(0).text(0) == "Child"
    assert [job.id for job in dialog.jobs.visible_jobs] == ["parent-run"]

    dialog.project_tree.setCurrentItem(root_item.child(0))
    assert [job.id for job in dialog.jobs.visible_jobs] == ["child-run"]
    assert dialog.jobs.detail_title.text() == "Child"
    dialog.close()


def test_unassigned_and_missing_references_are_explicit(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")
    repository.save(
        project.add_run("owned").add_run("missing"),
        expected_generation=project.generation,
    )
    source = _JobSource(
        (
            _job("owned", dataset="Owned"),
            _job("free", dataset="Free"),
        )
    )
    dialog = _dialog(repository, source)

    project_item = _find_project_item(dialog, "Project")
    assert project_item.text(1) == "1/2"
    assert not dialog.project_notice.isHidden()
    assert "1 persistent run reference" in dialog.project_notice.text()

    unassigned = _find_project_item(dialog, "Unassigned")
    assert unassigned.text(1) == "1"
    dialog.project_tree.setCurrentItem(unassigned)
    assert [job.id for job in dialog.jobs.visible_jobs] == ["free"]
    dialog.close()


def test_job_source_change_recomputes_project_projection(tmp_path):
    application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    repository.create("Project")
    source = _JobSource((_job("free-1", dataset="First"),))
    dialog = _dialog(repository, source)

    assert _find_project_item(dialog, "Unassigned").text(1) == "1"

    source.replace_jobs(
        (
            _job("free-1", dataset="First"),
            _job("free-2", dataset="Second"),
        ),
        "free-2",
    )
    application.processEvents()

    assert _find_project_item(dialog, "Unassigned").text(1) == "2"
    dialog.close()


def test_repository_refresh_updates_open_project_browser(tmp_path):
    application = QApplication.instance() or QApplication([])
    directory = tmp_path / "projects"
    repository = ProjectRepository(directory)
    project = repository.create("Original")
    source = _JobSource(())
    dialog = _dialog(repository, source)

    second = ProjectRepository(directory)
    snapshot = second.project(project.id)
    second.save(
        snapshot.rename("Changed elsewhere"),
        expected_generation=snapshot.generation,
    )

    repository.refresh()
    application.processEvents()

    assert _find_project_item(dialog, "Changed elsewhere").text(0) == "Changed elsewhere"
    dialog.close()


def test_conflict_replays_only_requested_project_change(tmp_path, monkeypatch):
    _application = QApplication.instance() or QApplication([])
    directory = tmp_path / "projects"
    repository = ProjectRepository(directory)
    project = repository.create("Original")
    dialog = _dialog(repository, _JobSource((_job("external-run", dataset="Run"),)))

    external = ProjectRepository(directory)
    current = external.project(project.id)
    external.save(
        current.add_run("external-run"),
        expected_generation=current.generation,
    )

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    saved = dialog._save_project_change(
        project,
        lambda current: current.rename("Local rename"),
        "Rename Project",
    )

    assert saved is not None
    persisted = repository.project(project.id)
    assert persisted.name == "Local rename"
    assert persisted.persistent_refs == ("external-run",)
    assert persisted.generation == 3
    dialog.close()


def test_failed_conflict_retry_reloads_external_project_state(tmp_path, monkeypatch):
    _application = QApplication.instance() or QApplication([])
    directory = tmp_path / "projects"
    repository = ProjectRepository(directory)
    project = repository.create("Original")
    dialog = _dialog(repository, _JobSource(()))

    external = ProjectRepository(directory)
    current = external.project(project.id)
    external.save(
        current.rename("Changed elsewhere"),
        expected_generation=current.generation,
    )

    original_save = repository.save
    save_calls = 0

    def fail_retry(edited, *, expected_generation):
        nonlocal save_calls
        save_calls += 1
        if save_calls == 2:
            raise ProjectRepositoryError("simulated write failure")
        return original_save(edited, expected_generation=expected_generation)

    monkeypatch.setattr(repository, "save", fail_retry)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)

    saved = dialog._save_project_change(
        project,
        lambda current: current.add_run("local-run"),
        "Add Run to Project",
    )

    assert saved is None
    assert save_calls == 2
    persisted = repository.project(project.id)
    assert persisted.name == "Changed elsewhere"
    assert persisted.persistent_refs == ()
    assert _find_project_item(dialog, "Changed elsewhere").text(0) == "Changed elsewhere"
    dialog.close()
