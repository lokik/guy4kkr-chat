"""Project selection in execution setup is per run, not a workspace mutation."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication
from ase2sprkkr.execution import ProjectRepository

from guy4ase.gui.dialogs import profiles as profiles_module
from guy4ase.gui.dialogs.profiles import ProfileSelectionDialog


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_execution_dialog_lists_projects_and_preselects_active(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    parent = repository.create("Materials")
    nested = repository.create("Fe calculations", parent_id=parent.id)
    other = repository.create("Other")

    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=nested.id,
        directory=str(tmp_path),
    )
    assert dialog.project_id() == nested.id
    assert dialog.project_selector.currentText() == "Materials / Fe calculations"
    assert dialog.project_selector.count() == 4  # Unassigned + 3 projects

    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(other.id)
    )
    assert dialog.project_id() == other.id
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_execution_dialog_can_explicitly_select_unassigned(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    active = repository.create("Current")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=active.id,
        directory=str(tmp_path),
    )
    assert dialog.project_id() == active.id
    dialog.project_selector.setCurrentIndex(0)
    assert dialog.project_id() is None
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_unknown_active_project_falls_back_to_unassigned(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    repository.create("Available")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id="deleted-project",
        directory=str(tmp_path),
    )
    assert dialog.project_id() is None
    dialog.close()


def test_create_project_in_execution_dialog_is_selected_and_persisted(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    dialog = ProfileSelectionDialog(
        project_repository=repository, directory=str(tmp_path)
    )
    monkeypatch.setattr(
        profiles_module.QInputDialog, "getText",
        lambda *_args: ("New calculation", True),
    )
    dialog.new_project_button.click()

    created_id = dialog.project_id()
    assert created_id is not None
    assert repository.project(created_id).name == "New calculation"
    assert repository.project(created_id).parent_id is None
    assert dialog.project_selector.currentText() == "New calculation"
    assert dialog.project_selector.count() == 2
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()

    # The project is durable; it can be chosen in a later launch.
    again = ProfileSelectionDialog(
        project_repository=repository, directory=str(tmp_path)
    )
    assert again.project_selector.findData(created_id) >= 0
    again.close()


def test_create_subproject_under_current_selection(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    parent = repository.create("Materials")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=parent.id,
        directory=str(tmp_path),
    )
    monkeypatch.setattr(
        profiles_module.QInputDialog, "getText",
        lambda *_args: ("Fe", True),
    )
    dialog.new_project_button.click()

    child_id = dialog.project_id()
    assert child_id is not None and child_id != parent.id
    assert repository.project(child_id).parent_id == parent.id
    assert dialog.project_selector.currentText() == "Materials / Fe"
    assert dialog.project_selector.count() == 3
    dialog.close()


def test_cancel_create_project_preserves_selection(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    current = repository.create("Current")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=current.id,
        directory=str(tmp_path),
    )
    monkeypatch.setattr(
        profiles_module.QInputDialog, "getText",
        lambda *_args: ("Discarded", False),
    )
    dialog.new_project_button.click()

    assert dialog.project_id() == current.id
    assert dialog.project_selector.count() == 2
    assert [project.name for project in repository.projects()] == ["Current"]
    dialog.close()


def test_project_creation_error_does_not_close_execution_dialog(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    current = repository.create("Current")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=current.id,
        directory=str(tmp_path),
    )
    monkeypatch.setattr(
        profiles_module.QInputDialog, "getText",
        lambda *_args: ("Invalid", True),
    )

    def fail_create(name, *, parent_id=None):
        assert name == "Invalid"
        assert parent_id == current.id
        raise ValueError("Invalid project name")

    monkeypatch.setattr(repository, "create", fail_create)
    warnings = []
    monkeypatch.setattr(
        profiles_module.QMessageBox, "warning",
        lambda _dialog, title, message: warnings.append((title, message)),
    )
    dialog.new_project_button.click()

    assert warnings == [("Create Project Failed", "Invalid project name")]
    assert dialog.project_id() == current.id
    assert dialog.result() == dialog.DialogCode.Rejected
    dialog.close()
