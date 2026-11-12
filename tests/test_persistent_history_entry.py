"""Regression tests for the application-owned project browser entry point."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from ase2sprkkr.execution import ProjectRepository

import guy4ase.main as main_module
from guy4ase.main import GuiApplication


class _JobSource:
    available = True
    unavailable_reason = None
    supports_refresh = False
    supports_results = False
    supports_attach = False
    supports_retry_download = False
    supports_result_file_check = False

    def __init__(self) -> None:
        self._listeners = []

    def subscribe(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    @staticmethod
    def jobs():
        return ()

    @staticmethod
    def job(_job_id):
        return None

    @staticmethod
    def job_changed(_job_id):
        return None

    @staticmethod
    def refresh():
        return ()


def test_workflow_project_entry_is_separate_from_workspace_results(tmp_path):
    _application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=_JobSource(),
        project_repository=ProjectRepository(tmp_path / "projects"),
    )
    window = gui.create_workflow_window()

    assert not gui.controller.result_store.results
    assert window.browser_panel.project_browser_button.text() == "Project Browser…"
    window.close()


def test_project_browser_lifecycle_belongs_to_application(monkeypatch, tmp_path):
    _application = QApplication.instance() or QApplication([])
    events: list[tuple[str, object]] = []

    class _Signal:
        def __init__(self) -> None:
            self._callbacks = []

        def connect(self, callback) -> None:
            self._callbacks.append(callback)

        def emit(self, *args) -> None:
            for callback in tuple(self._callbacks):
                callback(*args)

    class FakeProjectBrowserDialog:
        instances: list["FakeProjectBrowserDialog"] = []

        def __init__(
            self,
            repository,
            persistent_jobs_controller,
            *,
            active_project_id=None,
        ) -> None:
            self.repository = repository
            self.persistent_jobs_controller = persistent_jobs_controller
            self.active_project_id = active_project_id
            self.destroyed = _Signal()
            self.activeProjectRequested = _Signal()
            self.delete_on_close = False
            type(self).instances.append(self)

        def set_active_project(self, project_id) -> None:
            self.active_project_id = project_id

        def setAttribute(self, attribute) -> None:
            self.delete_on_close = attribute == main_module.Qt.WidgetAttribute.WA_DeleteOnClose

        def show(self) -> None:
            events.append(("show", self))

        def raise_(self) -> None:
            events.append(("raise", self))

        def activateWindow(self) -> None:
            events.append(("activate", self))

        def close(self) -> None:
            self.destroyed.emit()

    monkeypatch.setattr(main_module, "ProjectBrowserDialog", FakeProjectBrowserDialog)
    repository = ProjectRepository(tmp_path / "projects")
    job_source = _JobSource()
    gui = GuiApplication(
        recent_files_path=tmp_path / "recent.json",
        settings_path=tmp_path / "settings.json",
        persistent_jobs=job_source,
        project_repository=repository,
    )
    workflow = gui.create_workflow_window()
    expert = gui.create_main_window()

    workflow.browser_panel.project_browser_button.click()
    first_dialog = FakeProjectBrowserDialog.instances[0]
    expert.browser_panel.project_browser_button.click()

    assert len(FakeProjectBrowserDialog.instances) == 1
    assert first_dialog.repository is repository
    assert first_dialog.persistent_jobs_controller is gui.persistent_jobs_controller
    assert first_dialog.active_project_id is None
    assert first_dialog.delete_on_close
    assert [name for name, _dialog in events] == [
        "show",
        "raise",
        "activate",
        "show",
        "raise",
        "activate",
    ]
    assert all(dialog is first_dialog for _name, dialog in events)

    first_dialog.close()
    workflow.browser_panel.project_browser_button.click()

    assert len(FakeProjectBrowserDialog.instances) == 2
    second_dialog = FakeProjectBrowserDialog.instances[1]
    assert second_dialog is not first_dialog
    assert second_dialog.persistent_jobs_controller is gui.persistent_jobs_controller
    assert second_dialog.delete_on_close
    assert events[-3:] == [
        ("show", second_dialog),
        ("raise", second_dialog),
        ("activate", second_dialog),
    ]

    workflow.close()
    expert.close()
