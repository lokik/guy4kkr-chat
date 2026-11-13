"""Project selection and directory handling in the execution setup dialog."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication
from kkrunner.projects import ProjectRepository

from guy4ase.gui.dialogs import profiles as profiles_module
from guy4ase.gui.dialogs import project_edit as project_edit_module
from guy4ase.gui.dialogs.project_edit import ProjectEditDialog
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
        ProjectEditDialog, "exec",
        lambda self: (self.name_edit.setText("New calculation") or self.DialogCode.Accepted),
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
        ProjectEditDialog, "exec",
        lambda self: (self.name_edit.setText("Fe") or self.DialogCode.Accepted),
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
    monkeypatch.setattr(ProjectEditDialog, "exec", lambda self: self.DialogCode.Rejected)
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
        ProjectEditDialog, "exec",
        lambda self: (self.name_edit.setText("Invalid") or self.DialogCode.Accepted),
    )

    def fail_create(name, *, parent_id=None, directory=None):
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


def test_project_directory_switch_and_manual_override(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    first_directory = tmp_path / "project_work"
    second_directory = tmp_path / "other_work"
    first = repository.create("First", directory=first_directory)
    second = repository.create("Second", directory=second_directory)
    no_directory = repository.create("No directory")
    initial = str(tmp_path / "workspace")
    dialog = ProfileSelectionDialog(
        project_repository=repository, directory=initial
    )
    assert dialog.directory_name() == initial

    # Before any explicit selection, the project's directory follows its choice.
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(first.id))
    assert dialog.directory_name() == str(first_directory)
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(second.id))
    assert dialog.directory_name() == str(second_directory)
    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(no_directory.id)
    )
    assert dialog.directory_name() == initial
    dialog.project_selector.setCurrentIndex(0)
    assert dialog.directory_name() == initial

    # An explicit directory is a per-run override, even after switching projects.
    manual = str(tmp_path / "manual")
    dialog.directory_edit.setText(manual)
    dialog._directory_edited(manual)
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(first.id))
    assert dialog.directory_name() == manual
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(second.id))
    assert dialog.directory_name() == manual
    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(no_directory.id)
    )
    assert dialog.directory_name() == manual
    dialog.project_selector.setCurrentIndex(0)
    assert dialog.directory_name() == manual
    dialog.close()


def test_active_project_directory_is_default_on_dialog_open(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    project_directory = tmp_path / "project"
    active = repository.create("Active", directory=project_directory)
    workspace_directory = tmp_path / "workspace"
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=active.id,
        directory=str(workspace_directory),
    )
    assert dialog.project_id() == active.id
    assert dialog.directory_name() == str(project_directory)
    dialog.project_selector.setCurrentIndex(0)
    assert dialog.directory_name() == str(workspace_directory)
    dialog.close()

    # No inherited workspace directory is required for a project default.
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=active.id,
        directory=None,
    )
    assert dialog.directory_name() == str(project_directory)
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_browsed_directory_is_explicit_even_after_project_change(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    first = repository.create("First", directory=tmp_path / "first")
    second = repository.create("Second", directory=tmp_path / "second")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=first.id,
    )
    assert dialog.directory_name() == str(tmp_path / "first")

    chosen = str(tmp_path / "chosen")
    monkeypatch.setattr(
        profiles_module.QFileDialog, "getExistingDirectory",
        lambda *_args: chosen,
    )
    dialog._browse_directory()
    assert dialog.directory_name() == chosen
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(second.id))
    assert dialog.directory_name() == chosen
    dialog.close()


def test_typing_directory_after_project_selection_overrides_project(
    application, tmp_path
):
    from PyQt6.QtTest import QTest

    repository = ProjectRepository(tmp_path / "projects")
    first = repository.create("First", directory=tmp_path / "first")
    second = repository.create("Second", directory=tmp_path / "second")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=first.id
    )
    assert dialog.directory_name() == str(tmp_path / "first")

    dialog.directory_edit.clear()
    QTest.keyClicks(dialog.directory_edit, str(tmp_path / "manual"))
    assert dialog.directory_name() == str(tmp_path / "manual")
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(second.id))
    assert dialog.directory_name() == str(tmp_path / "manual")
    dialog.close()


def test_new_project_dialog_sets_working_directory(application, monkeypatch, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    directory = tmp_path / "new-project"
    dialog = ProfileSelectionDialog(project_repository=repository, directory=str(tmp_path))

    def create(project_dialog):
        project_dialog.name_edit.setText("New")
        project_dialog.directory_edit.setText(str(directory))
        return project_dialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectEditDialog, "exec", create)
    dialog.new_project_button.click()
    project_id = dialog.project_id()
    assert project_id is not None
    assert repository.project(project_id).directory == str(directory)
    assert dialog.directory_name() == str(directory)
    dialog.close()


def test_project_editing_controls_and_directory_defaults(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    assigned = repository.create("Assigned", directory=tmp_path / "existing")
    empty = repository.create("Empty")
    dialog = ProfileSelectionDialog(
        project_repository=repository, directory=str(tmp_path / "workspace")
    )
    assert not dialog.edit_project_button.isEnabled()
    assert not dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()

    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(assigned.id))
    assert dialog.edit_project_button.isEnabled()
    assert not dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()

    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(empty.id))
    assert dialog.edit_project_button.isEnabled()
    assert dialog.assign_directory_checkbox.isEnabled()
    assert dialog.assign_directory_checkbox.isChecked()
    dialog.project_selector.setCurrentIndex(0)
    assert not dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()
    dialog.close()


def test_edit_current_project_updates_label_and_directory(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    current = repository.create("Original", directory=tmp_path / "old")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=current.id,
        directory=str(tmp_path / "workspace"),
    )

    def edit(project_dialog):
        assert project_dialog.name_edit.text() == "Original"
        assert project_dialog.project_directory() == str(tmp_path / "old")
        project_dialog.name_edit.setText("Renamed")
        project_dialog.directory_edit.setText(str(tmp_path / "new"))
        return project_dialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectEditDialog, "exec", edit)
    dialog.edit_project_button.click()

    saved = repository.project(current.id)
    assert saved.name == "Renamed"
    assert saved.directory == str(tmp_path / "new")
    assert dialog.project_id() == current.id
    assert dialog.project_selector.currentText() == "Renamed"
    assert dialog.directory_name() == str(tmp_path / "new")
    assert not dialog.assign_directory_checkbox.isChecked()
    dialog.close()


def test_edit_project_does_not_override_explicit_run_directory(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    current = repository.create("Original", directory=tmp_path / "old")
    manual = str(tmp_path / "manual")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=current.id,
    )
    dialog.directory_edit.setText(manual)
    dialog._directory_edited(manual)

    def edit(project_dialog):
        project_dialog.directory_edit.setText(str(tmp_path / "new"))
        return project_dialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectEditDialog, "exec", edit)
    dialog.edit_project_button.click()
    assert repository.project(current.id).directory == str(tmp_path / "new")
    assert dialog.directory_name() == manual
    dialog.close()


def test_edit_project_cancel_and_failure_do_not_change_repository(
    application, monkeypatch, tmp_path
):
    from kkrunner.projects import ProjectRepositoryError

    repository = ProjectRepository(tmp_path / "projects")
    current = repository.create("Original")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=current.id,
    )
    monkeypatch.setattr(ProjectEditDialog, "exec", lambda self: self.DialogCode.Rejected)
    dialog.edit_project_button.click()
    assert repository.project(current.id) == current

    def edit(project_dialog):
        project_dialog.name_edit.setText("Failed")
        return project_dialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectEditDialog, "exec", edit)
    def fail_save(*_args, **_kwargs):
        raise ProjectRepositoryError("Concurrent edit")
    monkeypatch.setattr(repository, "save", fail_save)
    warnings = []
    monkeypatch.setattr(
        profiles_module.QMessageBox, "warning",
        lambda _dialog, title, message: warnings.append((title, message)),
    )
    dialog.edit_project_button.click()
    assert warnings == [("Edit Project Failed", "Concurrent edit")]
    assert repository.project(current.id) == current
    assert dialog.project_id() == current.id
    dialog.close()


def test_assign_directory_by_default_for_project_without_one(application, tmp_path):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Empty")
    directory = str(tmp_path / "workspace")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=project.id, directory=directory,
    )
    assert dialog.assign_directory_checkbox.isChecked()
    assert dialog.directory_name() == directory
    assert repository.project(project.id).directory is None
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert repository.project(project.id).directory == directory
    dialog.close()


def test_assign_directory_does_not_modify_project_when_unchecked(
    application, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Existing", directory=tmp_path / "project")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=project.id,
    )
    manual = str(tmp_path / "run-only")
    dialog.directory_edit.setText(manual)
    dialog._directory_edited(manual)
    assert not dialog.assign_directory_checkbox.isChecked()
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.directory_name() == manual
    assert repository.project(project.id).directory == str(tmp_path / "project")
    dialog.close()


def test_assign_directory_checkbox_can_update_existing_project(
    application, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Existing", directory=tmp_path / "project")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=project.id,
    )
    manual = str(tmp_path / "new-default")
    dialog.directory_edit.setText(manual)
    dialog._directory_edited(manual)
    dialog.assign_directory_checkbox.setChecked(True)
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert repository.project(project.id).directory == manual
    dialog.close()


def test_assignment_only_happens_on_accept_and_never_for_unassigned(
    application, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Empty")
    directory = str(tmp_path / "workspace")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=project.id, directory=directory,
    )
    dialog.reject()
    assert repository.project(project.id).directory is None
    dialog.close()

    dialog = ProfileSelectionDialog(
        project_repository=repository, directory=directory,
    )
    assert not dialog.assign_directory_checkbox.isEnabled()
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert repository.project(project.id).directory is None
    dialog.close()


def test_assign_directory_save_failure_keeps_dialog_open(
    application, monkeypatch, tmp_path
):
    from kkrunner.projects import ProjectRepositoryError

    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Empty")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=project.id,
        directory=str(tmp_path / "run"),
    )
    warnings = []
    monkeypatch.setattr(
        profiles_module.QMessageBox, "warning",
        lambda _dialog, title, message: warnings.append((title, message)),
    )

    def fail_save(*_args, **_kwargs):
        raise ProjectRepositoryError("Changed by another process")

    monkeypatch.setattr(repository, "save", fail_save)
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Rejected
    assert repository.project(project.id).directory is None
    assert warnings == [
        ("Assign Project Directory Failed", "Changed by another process")
    ]
    dialog.close()


def test_explicit_directory_assignment_choice_survives_project_switches(
    application, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    without_directory = repository.create("Unset")
    with_directory = repository.create("Set", directory=tmp_path / "existing")
    dialog = ProfileSelectionDialog(
        project_repository=repository,
        active_project_id=without_directory.id,
        directory=str(tmp_path / "workspace"),
    )
    assert dialog.assign_directory_checkbox.isChecked()
    dialog.assign_directory_checkbox.click()
    assert not dialog.assign_directory_checkbox.isChecked()
    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(with_directory.id)
    )
    assert not dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()
    override = str(tmp_path / "override")
    dialog.directory_edit.setText(override)
    dialog._directory_edited(override)
    assert dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()
    dialog.assign_directory_checkbox.click()
    assert dialog.assign_directory_checkbox.isChecked()
    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(without_directory.id)
    )
    assert not dialog.assign_directory_checkbox.isChecked()
    dialog.project_selector.setCurrentIndex(
        dialog.project_selector.findData(with_directory.id)
    )
    assert dialog.assign_directory_checkbox.isChecked()
    dialog.close()


def test_assign_directory_disabled_when_same_as_project(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Existing", directory=tmp_path / "assigned")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=project.id,
        directory=str(tmp_path / "workspace"),
    )

    assert dialog.directory_name() == project.directory
    assert not dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()

    # Changes to the field must update availability immediately.
    alternate = str(tmp_path / "alternate")
    dialog.directory_edit.setText(alternate)
    assert dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()

    dialog.assign_directory_checkbox.click()
    assert dialog.assign_directory_checkbox.isChecked()

    # Equivalent paths must not allow a redundant project assignment.
    dialog.directory_edit.setText(project.directory + "/../assigned")
    assert dialog.directory_name() == project.directory
    assert not dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()

    # The previous user preference is restored if assignment becomes meaningful again.
    dialog.directory_edit.setText(alternate)
    assert dialog.assign_directory_checkbox.isEnabled()
    assert dialog.assign_directory_checkbox.isChecked()

    dialog.directory_edit.setText(project.directory)
    monkeypatch.setattr(
        repository, "save",
        lambda *_args, **_kwargs: pytest.fail("Redundant project save"),
    )
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.close()


def test_assignment_stays_unavailable_until_working_directory_is_set(
    application, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Empty")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=project.id,
        directory=None,
    )

    assert dialog.directory_name() is None
    assert not dialog.assign_directory_checkbox.isEnabled()
    dialog.directory_edit.setText(str(tmp_path / "run"))
    assert dialog.assign_directory_checkbox.isEnabled()
    assert dialog.assign_directory_checkbox.isChecked()
    dialog.close()


def test_editing_project_to_current_directory_disables_assignment(
    application, monkeypatch, tmp_path
):
    repository = ProjectRepository(tmp_path / "projects")
    project = repository.create("Existing", directory=tmp_path / "old")
    working = str(tmp_path / "run")
    dialog = ProfileSelectionDialog(
        project_repository=repository, active_project_id=project.id
    )
    dialog.directory_edit.setText(working)
    dialog._directory_edited(working)
    assert dialog.assign_directory_checkbox.isEnabled()

    def edit(project_dialog):
        project_dialog.directory_edit.setText(working)
        return project_dialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectEditDialog, "exec", edit)
    dialog.edit_project_button.click()
    assert repository.project(project.id).directory == working
    assert dialog.directory_name() == working
    assert not dialog.assign_directory_checkbox.isEnabled()
    assert not dialog.assign_directory_checkbox.isChecked()
    dialog.close()


def test_run_dialog_manages_profiles_without_opening_all_settings(
    application, monkeypatch, tmp_path
):
    from PyQt6.QtWidgets import QDialog

    repository = ProjectRepository(tmp_path / "projects")
    dialog = ProfileSelectionDialog(
        project_repository=repository, directory=str(tmp_path)
    )
    assert dialog.edit_profiles_button.text() == "Manage Profiles…"
    selected = dialog.profiles.currentData()
    events = []

    class ProfileEditor:
        def __init__(self, parent, *, store):
            assert parent is dialog
            assert store is dialog._store
            events.append("open")

        def exec(self):
            events.append("accept")
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(profiles_module, "ProfilesDialog", ProfileEditor)
    monkeypatch.setattr(
        dialog, "_reload_profiles",
        lambda name: events.append(("reload", name)),
    )
    dialog.edit_profiles_button.click()

    assert events == ["open", "accept", ("reload", selected)]
    dialog.close()


def test_cancelled_profile_management_does_not_reload_selection(
    application, monkeypatch, tmp_path
):
    from PyQt6.QtWidgets import QDialog

    repository = ProjectRepository(tmp_path / "projects")
    dialog = ProfileSelectionDialog(
        project_repository=repository, directory=str(tmp_path)
    )
    events = []

    class ProfileEditor:
        def __init__(self, parent, *, store):
            assert parent is dialog
            assert store is dialog._store

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(profiles_module, "ProfilesDialog", ProfileEditor)
    monkeypatch.setattr(dialog, "_reload_profiles", lambda *_: events.append("reload"))
    dialog.edit_profiles_button.click()

    assert events == []
    dialog.close()


def test_reopened_run_setup_preserves_profile_identifiers_and_explicit_directory(
    application, tmp_path
):
    from types import SimpleNamespace
    from guy4ase.gui.dialogs.profiles import RunIdentification

    repo = ProjectRepository(tmp_path / "projects")
    initial = repo.create("Initial", directory=tmp_path / "default")
    other = repo.create("Other", directory=tmp_path / "other")
    custom = str(tmp_path / "manually-chosen")
    identification = RunIdentification("Fe_retry", "calculation-B")

    class Option:
        def __init__(self, value):
            self.value = value

        def is_set(self):
            return True

        def __call__(self):
            return self.value

    parameters = SimpleNamespace(CONTROL=SimpleNamespace(
        DATASET=Option("original"),
        ADSI=Option("original-label"),
    ))
    store = SimpleNamespace(
        names=lambda: ["local-profile", "remote-profile"],
        resolved_name=lambda _name: "local-profile",
        describe=lambda _name: "Execution profile",
    )
    dialog = ProfileSelectionDialog(
        input_parameters=parameters,
        store=store,
        project_repository=repo,
        directory=custom,
        active_project_id=initial.id,
        selected_profile_name="remote-profile",
        initial_identification=identification,
        directory_is_explicit=True,
    )

    assert dialog.directory_name() == custom
    assert dialog.project_id() == initial.id
    assert dialog.profile_name() == "remote-profile"
    assert dialog.identification() == identification
    dialog.project_selector.setCurrentIndex(dialog.project_selector.findData(other.id))
    assert dialog.directory_name() == custom
    dialog.close()
