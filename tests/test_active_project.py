"""Tests for active-project ownership of newly created persistent runs."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from ase2sprkkr.execution import ProjectRepository

from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog
from guy4ase.main import GuiApplication


class _JobSource:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = False
    supports_attach = False
    supports_retry_finalization = False
    supports_result_file_check = False

    def __init__(self):
        self.changed = []
        self._listeners = []
        self._jobs = {}

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def jobs(self):
        return tuple(self._jobs.values())

    def job(self, job_id):
        return self._jobs.get(str(job_id))

    def job_changed(self, job_id):
        self.changed.append(str(job_id))
        return self._jobs.get(str(job_id))

    @staticmethod
    def refresh():
        return ()


class _LaunchWindow(QWidget):
    persistentJobChanged = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.execution_context = None

    def set_execution_context(self, manager, *, project_id=None):
        self.execution_context = (manager, project_id)


def test_active_project_is_explicit_not_current_browser_selection(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    first = repository.create("First")
    second = repository.create("Second")
    source = _JobSource()
    dialog = ProjectBrowserDialog(repository, PersistentJobsController(source))
    requested = []
    dialog.activeProjectRequested.connect(requested.append)

    dialog.set_active_project(first.id)
    assert dialog.active_project_id == first.id
    assert dialog.active_project_label.text() == "Active project: First"

    # Browsing another project does not silently change calculation ownership.
    second_item = dialog.project_tree.topLevelItem(1)
    assert second_item.text(0) == "Second"
    dialog.project_tree.setCurrentItem(second_item)
    assert dialog.active_project_id == first.id
    assert requested == []

    dialog.set_active_project_button.click()
    assert requested == [second.id]
    dialog.close()


def test_setting_active_project_does_not_read_repository(tmp_path, monkeypatch):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Project")
    source = _JobSource()
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=source,
        project_repository=repository,
    )

    def unexpected_lookup(_project_id):
        raise AssertionError("active-project selection must not read the repository")

    monkeypatch.setattr(repository, "project", unexpected_lookup)
    gui.set_active_project(project.id)

    assert gui.active_project_id == project.id


def test_launch_captures_active_project_before_later_selection_change(tmp_path):
    _application = QApplication.instance() or QApplication([])
    repository = ProjectRepository(tmp_path / "projects")
    launch_project = repository.create("Launch")
    later_project = repository.create("Later")
    source = _JobSource()
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=source,
        project_repository=repository,
    )
    gui.set_active_project(launch_project.id)
    monitor_window = _LaunchWindow()

    gui._track_launch_monitor(monitor_window)
    captured_manager, captured_project = monitor_window.execution_context

    gui.set_active_project(later_project.id)

    assert captured_manager is gui.execution_manager
    assert captured_manager.projects is repository
    assert captured_project == launch_project.id
    assert gui.active_project_id == later_project.id
    monitor_window.close()
