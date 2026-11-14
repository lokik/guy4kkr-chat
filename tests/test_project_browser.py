"""Qt tests for project-to-persistent-job browsing."""
from __future__ import annotations

from dataclasses import replace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QSizePolicy, QTreeWidgetItem, QWidget
from kkrunner.projects import ProjectRepository, ProjectRepositoryError

from guy4ase.gui.application.persistent_jobs import PersistentJob
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog


def _job(job_id: str, *, dataset: str, project_id=None, profile=None) -> PersistentJob:
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
        project_id=project_id,
        profile=profile,
    )


class _JobSource:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = False
    supports_attach = False
    supports_retry_download = False
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
    child = repository.create("Child", parent_id=root.id)
    source = _JobSource(
        (
            _job("parent-run", dataset="Parent", project_id=root.id),
            _job("child-run", dataset="Child", project_id=child.id),
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


def test_unassigned_runs_are_identified_from_authoritative_run_project(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")
    source = _JobSource((
        _job("owned", dataset="Owned", project_id=project.id),
        _job("free", dataset="Free"),
    ))
    dialog = _dialog(repository, source)
    item = _find_project_item(dialog, "Project")
    assert item.text(1) == "1"
    assert [job.id for job in dialog.jobs.visible_jobs] == ["owned"]
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
        snapshot.modify(name="Changed elsewhere"),
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
        current.modify(name="Externally renamed"),
        expected_generation=current.generation,
    )

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    saved = dialog._save_project_change(
        project,
        lambda current: current.modify(name="Local rename"),
        "Rename Project",
    )

    assert saved is not None
    persisted = repository.project(project.id)
    assert persisted.name == "Local rename"
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
        current.modify(name="Changed elsewhere"),
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
        lambda current: current.modify(name="Locally renamed"),
        "Rename Project",
    )

    assert saved is None
    assert save_calls == 2
    persisted = repository.project(project.id)
    assert persisted.name == "Changed elsewhere"

    assert _find_project_item(dialog, "Changed elsewhere").text(0) == "Changed elsewhere"
    dialog.close()


def test_project_edit_changes_name_and_directory(tmp_path, monkeypatch):
    from guy4ase.gui.dialogs.project_edit import ProjectEditDialog

    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    original = repository.create("Original")
    dialog = _dialog(repository, _JobSource(()))
    item = _find_project_item(dialog, "Original")
    dialog.project_tree.setCurrentItem(item)

    def edit(project_dialog):
        project_dialog.name_edit.setText("Edited")
        project_dialog.directory_edit.setText(str(tmp_path / "calculations"))
        return project_dialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectEditDialog, "exec", edit)
    dialog._edit_project()
    current = repository.project(original.id)
    assert current.name == "Edited"
    assert current.directory == str(tmp_path / "calculations")
    assert _find_project_item(dialog, "Edited").text(0) == "Edited"
    dialog.close()


def test_project_browser_separates_bulk_actions_from_single_result_detail(tmp_path):
    application = QApplication.instance() or QApplication([])
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    browser = _dialog(projects, _JobSource((_job("one", dataset="One", project_id=project.id),)))
    browser.show()
    application.processEvents()

    assert browser.jobs.result_widget.select_all_button.isHidden()
    assert browser.jobs.result_widget.assign_project_button.isHidden()
    assert browser.jobs.select_all_jobs_button.isVisible()
    assert browser.jobs.move_jobs_button.isVisible()
    assert not hasattr(browser, "imported_group")
    assert browser.jobs.add_result_button.isVisible()
    assert browser.jobs.load_result_button.text() == "Use result"
    assert browser.jobs.refresh_result_button.text() == "Refresh result"
    browser.close()


def test_project_browser_moves_multiple_completed_records_to_another_project(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    projects = ProjectRepository(tmp_path / "projects")
    origin = projects.create("Origin")
    target = projects.create("Target")

    class MovingSource(_JobSource):
        supports_reassignment = True

        def __init__(self, jobs):
            super().__init__(jobs)
            self.calls = []

        def reassign_runs(self, _projects, run_ids, destination, *, expected_project_ids):
            self.calls.append((tuple(run_ids), destination, expected_project_ids))
            self._jobs = tuple(
                replace(job, project_id=destination) if job.id in run_ids else job
                for job in self._jobs
            )
            for job_id in run_ids:
                for listener in tuple(self._listeners):
                    listener(job_id)

    source = MovingSource((
        _job("run-1", dataset="A", project_id=origin.id),
        _job("run-2", dataset="B", project_id=origin.id),
    ))
    browser = _dialog(projects, source)
    browser.show()
    application.processEvents()

    from guy4ase.gui.dialogs.assign_results import AssignResultsDialog

    def choose_target(dialog):
        assert dialog.allow_unassigned
        assert dialog.project.currentIndex() == -1
        dialog.project.setCurrentIndex(dialog.project.findData(target.id))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AssignResultsDialog, "exec", choose_target)
    browser.jobs.select_all_jobs_button.click()
    assert set(browser.jobs.selected_persistent_refs) == {"run-1", "run-2"}
    browser.jobs.tree.header().sectionClicked.emit(4)  # Rebuilding grouped rows keeps multiselection.
    assert set(browser.jobs.selected_persistent_refs) == {"run-1", "run-2"}
    assert browser.jobs.move_jobs_button.isEnabled()
    browser.jobs.move_jobs_button.click()

    assert len(source.calls) == 1
    run_ids, destination, expected = source.calls[0]
    assert set(run_ids) == {"run-1", "run-2"}
    assert destination == target.id
    assert expected == {"run-1": origin.id, "run-2": origin.id}
    assert browser.active_project_id is None  # Moving records does not activate a project.
    assert {job.project_id for job in browser.jobs.visible_jobs} == {target.id}
    browser.close()


def test_project_browser_allows_reassignment_for_running_runs(tmp_path):
    application = QApplication.instance() or QApplication([])
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")

    class ReassignSource(_JobSource):
        supports_reassignment = True

    source = ReassignSource((_job("one", dataset="One", project_id=project.id),))
    browser = _dialog(projects, source)
    browser.show()
    application.processEvents()
    browser.jobs.select_all_jobs_button.click()
    assert browser.jobs.move_jobs_button.isEnabled()
    source.replace_jobs((replace(source.jobs()[0], state="running"),), "one")
    application.processEvents()
    assert browser.jobs.move_jobs_button.isEnabled()
    browser.close()


def test_project_browser_is_an_independent_non_modal_window(tmp_path):
    application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    parent = QWidget()
    parent.show()
    browser = ProjectBrowserDialog(
        repository, PersistentJobsController(_JobSource(())), parent=parent
    )
    browser.show()
    application.processEvents()

    # The browser must not block the structure manager even with a parent.
    assert browser.isWindow()
    assert not isinstance(browser, QDialog)
    assert browser.windowModality() == Qt.WindowModality.NonModal
    assert QApplication.activeModalWidget() is None
    assert parent.isVisible() and parent.isEnabled()
    assert browser.isVisible()

    browser.close()
    parent.close()


def test_project_browser_displays_historical_execution_profile(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")
    source = _JobSource((
        _job("run-1", dataset="First", project_id=project.id,
             profile="remote-cluster"),
        _job("run-2", dataset="Old", project_id=project.id),
    ))
    browser = _dialog(repository, source)
    assert browser.jobs.tree.headerItem().text(6) == "Profile"
    assert browser.jobs.profile_value.text() == "remote-cluster"
    displayed = {
        row.text(0): row.text(6)
        for group_index in range(browser.jobs.tree.topLevelItemCount())
        for group in (browser.jobs.tree.topLevelItem(group_index),)
        for row in (group.child(i) for i in range(group.childCount()))
    }
    assert displayed == {"First": "remote-cluster", "Old": "—"}
    browser.close()


def test_project_browser_can_request_file_import_for_selected_project(tmp_path):
    app = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")
    browser = _dialog(repository, _JobSource(()))
    browser.show()
    app.processEvents()

    requested = []
    browser.addResultRequested.connect(requested.append)
    assert browser.jobs.add_result_button.isEnabled()
    browser.jobs.add_result_button.click()
    assert requested == [project.id]

    browser.project_tree.clearSelection()
    browser.project_tree.setCurrentItem(None)
    assert not browser.jobs.add_result_button.isEnabled()
    browser.close()


def test_project_browser_project_actions_are_below_tree(tmp_path):
    from PyQt6.QtWidgets import QGroupBox

    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    repository.create("Project")
    browser = _dialog(repository, _JobSource(()))
    layout = browser.project_tree.parentWidget().layout()

    assert layout.itemAt(0).widget().text() == "Projects"
    assert layout.itemAt(1).widget() is browser.project_tree
    buttons = layout.itemAt(2).layout()
    assert buttons.itemAtPosition(0, 0).widget() is browser.new_project_button
    assert buttons.itemAtPosition(0, 1).widget() is browser.edit_project_button
    assert buttons.itemAtPosition(1, 0).widget() is browser.move_project_button
    assert buttons.itemAtPosition(1, 1).widget() is browser.delete_project_button
    assert buttons.itemAtPosition(2, 0).widget() is browser.refresh_projects_button
    assert buttons.itemAtPosition(2, 1) is None

    for button in (
        browser.new_project_button, browser.edit_project_button,
        browser.move_project_button, browser.delete_project_button,
        browser.refresh_projects_button,
    ):
        assert not button.icon().isNull()
        assert button.toolTip()

    active_group = layout.itemAt(3).widget()
    assert isinstance(active_group, QGroupBox)
    assert active_group.title() == "Active project"
    assert buttons.columnStretch(0) == buttons.columnStretch(1) == 1
    assert browser.active_project_label.parentWidget() is active_group
    assert browser.set_active_project_button.parentWidget() is active_group
    assert browser.clear_active_project_button.parentWidget() is active_group
    browser.close()


def test_job_headers_group_without_losing_bulk_selection(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")
    source = _JobSource((
        _job("one", dataset="First", project_id=project.id, profile="local"),
        _job("two", dataset="Second", project_id=project.id, profile="remote"),
    ))
    browser = _dialog(repository, source)
    jobs = browser.jobs
    header = jobs.tree.header()
    assert header.sectionsClickable()
    assert not hasattr(jobs, "group_by")
    assert jobs._group_column == 2
    assert "Group" in jobs.tree.headerItem().toolTip(6)

    jobs.select_all_jobs_button.click()
    assert set(jobs.selected_persistent_refs) == {"one", "two"}
    header.sectionClicked.emit(6)  # Profile
    assert jobs._group_column == 6
    assert {jobs.tree.topLevelItem(i).text(0)
            for i in range(jobs.tree.topLevelItemCount())} == {"local", "remote"}
    assert set(jobs.selected_persistent_refs) == {"one", "two"}

    header.sectionClicked.emit(0)  # Job removes grouping
    assert jobs._group_column == 0
    assert jobs.tree.topLevelItemCount() == 2
    assert all(jobs.tree.topLevelItem(i).childCount() == 0 for i in range(2))
    assert set(jobs.selected_persistent_refs) == {"one", "two"}
    assert "without grouping" in jobs.tree.headerItem().toolTip(0)
    browser.close()


def test_bulk_buttons_below_job_tree_and_single_result_actions_share_footer(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")
    browser = _dialog(
        repository, _JobSource((_job("run", dataset="Result", project_id=project.id),)),
    )
    jobs = browser.jobs
    job_layout = jobs.tree.parentWidget().layout()
    assert job_layout.itemAt(0).widget().text() == "Jobs"
    assert job_layout.itemAt(1).widget() is jobs.backend_notice
    assert job_layout.itemAt(2).widget() is jobs.tree
    bulk = job_layout.itemAt(3).layout()
    assert bulk.itemAtPosition(0, 0).widget() is jobs.select_all_jobs_button
    assert bulk.itemAtPosition(0, 1).widget() is jobs.move_jobs_button
    assert bulk.itemAtPosition(0, 2).widget() is jobs.add_result_button
    assert [bulk.columnStretch(i) for i in range(3)] == [1, 1, 1]
    assert job_layout.itemAt(4).widget() is jobs.refresh_button
    assert not jobs.refresh_button.icon().isNull()
    assert jobs.refresh_button.toolTip()

    result_layout = jobs.result_widget.parentWidget().layout()
    assert result_layout.itemAt(0).widget().text() == "Result"
    preview_index = result_layout.indexOf(jobs.result_widget)
    main_actions = result_layout.itemAt(preview_index + 2).layout()
    assert main_actions.itemAtPosition(0, 0).widget() is jobs.load_result_button
    assert main_actions.itemAtPosition(0, 1).widget() is jobs.refresh_result_button
    assert main_actions.itemAtPosition(0, 2).widget() is jobs.forget_button
    assert [main_actions.columnStretch(i) for i in range(3)] == [1, 1, 1]
    assert jobs.load_result_button.text() == "Use result"
    assert not jobs.load_result_button.icon().isNull()
    assert not jobs.forget_button.icon().isNull()
    browser.close()


def test_project_job_result_headings_align_and_buttons_expand_equally(tmp_path):
    app = QApplication.instance() or QApplication([])
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    browser = _dialog(
        projects, _JobSource((_job("one", dataset="One", project_id=project.id),)),
    )
    browser.resize(1550, 800)
    browser.show()
    app.processEvents()

    project_layout = browser.project_tree.parentWidget().layout()
    jobs = browser.jobs
    job_layout = jobs.tree.parentWidget().layout()
    result_layout = jobs.result_widget.parentWidget().layout()
    headings = (
        project_layout.itemAt(0).widget(),
        job_layout.itemAt(0).widget(),
        result_layout.itemAt(0).widget(),
    )
    offsets = [heading.mapTo(browser, QPoint(0, 0)).y() for heading in headings]
    assert offsets[0] == offsets[1] == offsets[2]
    assert result_layout.contentsMargins().top() == 0

    # Even an unavailable backend must not displace the Jobs/Result headings.
    jobs.backend_notice.setText("Backend unavailable")
    jobs.backend_notice.show()
    app.processEvents()
    assert [
        heading.mapTo(browser, QPoint(0, 0)).y() for heading in headings
    ] == offsets

    project_buttons = project_layout.itemAt(2).layout()
    new = project_buttons.itemAtPosition(0, 0).widget()
    edit = project_buttons.itemAtPosition(0, 1).widget()
    assert abs(new.width() - edit.width()) <= 2

    active = project_layout.itemAt(3).widget()
    active_buttons = active.layout().itemAt(1).layout()
    assert active_buttons.columnStretch(0) == active_buttons.columnStretch(1) == 1
    assert all(
        button.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
        for button in (
            browser.new_project_button,
            browser.edit_project_button,
            browser.move_project_button,
            browser.delete_project_button,
            browser.set_active_project_button,
            browser.clear_active_project_button,
            jobs.select_all_jobs_button,
            jobs.move_jobs_button,
            jobs.add_result_button,
            jobs.load_result_button,
            jobs.refresh_result_button,
            jobs.forget_button,
        )
    )
    assert abs(
        browser.set_active_project_button.width()
        - browser.clear_active_project_button.width()
    ) <= 2

    bulk = job_layout.itemAt(3).layout()
    widths = [bulk.itemAtPosition(0, i).widget().width() for i in range(3)]
    assert max(widths) - min(widths) <= 2
    browser.close()


def test_add_result_is_disabled_for_unassigned_and_enabled_for_project(tmp_path):
    app = QApplication.instance() or QApplication([])
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    browser = _dialog(
        projects, _JobSource((
            _job("external-job", dataset="Unassigned", project_id=None),
        )),
    )
    browser.show()
    app.processEvents()

    assert browser.jobs.add_result_button.isEnabled()
    browser.project_tree.setCurrentItem(_find_project_item(browser, "Unassigned"))
    assert not browser.jobs.add_result_button.isEnabled()
    browser.project_tree.setCurrentItem(_find_project_item(browser, "Project"))
    assert browser.jobs.add_result_button.isEnabled()
    browser.close()


def test_imported_result_groups_by_estimated_finish_time(tmp_path):
    from datetime import datetime

    app = QApplication.instance() or QApplication([])
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Project")
    finished = "2025-07-18T13:42:25+00:00"
    imported = replace(
        _job("external:result", dataset="old.out", project_id=project.id),
        imported_path=str(tmp_path / "old.out"),
        state="imported",
        finished_at=finished,
        return_code=None,
    )
    browser = _dialog(projects, _JobSource((imported,)))
    browser.show()
    app.processEvents()

    jobs = browser.jobs
    jobs.tree.header().sectionClicked.emit(3)
    expected_date = datetime.fromisoformat(finished).astimezone().strftime("%Y-%m-%d")
    assert jobs.tree.topLevelItem(0).text(0) == expected_date
    item = jobs.tree.topLevelItem(0).child(0)
    assert item.text(3) == datetime.fromisoformat(finished).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert "last modification time" in item.toolTip(3)
    assert jobs.finished_value.text() == item.text(3)
    assert jobs.finished_value.toolTip() == item.toolTip(3)
    browser.close()
