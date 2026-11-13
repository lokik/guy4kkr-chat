"""Execution-profile dialogs for SPR-KKR calculations."""
from __future__ import annotations

from ase2sprkkr.sprkkr.projects import default_project_repository

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from kkrunner.projects import ProjectRepository, ProjectRepositoryError

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.execution_profiles import ExecutionProfileStore
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.dialogs.project_edit import ProjectEditDialog
from guy4ase.gui.input_parameters.dataset import dataset_value, filename_component
from guy4ase.gui.widgets.settings.run_configurations import RunConfigurationsPage


@dataclass(frozen=True)
class RunIdentification:
    """Output identifiers for a single calculation, independent of its profile."""

    dataset: str | None
    adsi: str


class ProfilesDialog(QDialog):
    """Standalone compatibility wrapper around the reusable settings page."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        store: ExecutionProfileStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("SPR-KKR Execution Profiles")
        self.setMinimumSize(1040, 680)
        manage_window_geometry(
            self, "execution-profiles", default_size=(1200, 800)
        )
        root = QVBoxLayout(self)
        self.page = RunConfigurationsPage(self, store=store)
        root.addWidget(self.page, 1)
        # Existing users may access the exposed widgets of this dialog.
        self.form = self.page.form
        self.delete_button = self.page.delete_button
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def accept(self) -> None:  # type: ignore[override]
        try:
            self.page.save()
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Cannot Save Profiles", str(exc))
            return
        super().accept()


class ProfileSelectionDialog(QDialog):
    """Choose the execution profile for one calculation."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        store: ExecutionProfileStore | None = None,
        input_parameters=None,
        directory: str | None = None,
        require_directory: bool = True,
        project_repository: ProjectRepository | None = None,
        active_project_id: str | None = None,
        selected_profile_name: str | None = None,
        initial_identification: RunIdentification | None = None,
        directory_is_explicit: bool = False,
    ) -> None:
        super().__init__(parent)
        self._require_directory = require_directory
        # The workspace directory is a fallback, not an explicit choice in
        # this dialog. Project directories take precedence until the user
        # types a directory or chooses one with Browse.
        self._fallback_directory = directory or ""
        self._explicit_directory: str | None = directory if directory_is_explicit else None
        self._projects_by_id = {}
        self._directory_assignment_overrides = {}
        self._projects = project_repository if project_repository is not None else default_project_repository()
        self._store = store or ExecutionProfileStore()
        self.setWindowTitle("Run SPR-KKR Calculation")
        self.resize(650, 480)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(14)

        heading = QLabel("Execution profile", self)
        heading_font = heading.font()
        heading_font.setPointSize(heading_font.pointSize() + 3)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        layout.addWidget(heading)
        intro = QLabel(
            "Choose where this calculation will run. The profile also controls MPI and executable selection.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.dataset_edit: QLineEdit | None = None
        self.adsi_edit: QLineEdit | None = None
        if input_parameters is not None and hasattr(input_parameters, "CONTROL"):
            identifiers = QGroupBox("Calculation identification", self)
            identifier_form = QFormLayout(identifiers)

            self.dataset_edit = QLineEdit(identifiers)
            self.dataset_edit.setText(
                (dataset_value(input_parameters) if initial_identification is None
                 else initial_identification.dataset) or ""
            )
            self.dataset_edit.setPlaceholderText("Automatic naming")
            self.dataset_edit.setValidator(
                QRegularExpressionValidator(
                    QRegularExpression(r"[A-Za-z0-9_.-]*"), self.dataset_edit
                )
            )
            self.dataset_edit.setToolTip(
                "SPR-KKR CONTROL.DATASET. Base name for output files. "
                "Use a different name for simultaneous runs in the same directory."
            )
            identifier_form.addRow("Output file prefix:", self.dataset_edit)
            dataset_hint = QLabel(
                "Used to name output files (CONTROL.DATASET); leave empty for "
                "automatic naming.", identifiers
            )
            dataset_hint.setWordWrap(True)
            identifier_form.addRow("", dataset_hint)

            self.adsi_edit = QLineEdit(identifiers)
            adsi = (
                input_parameters.CONTROL.ADSI() if initial_identification is None
                else initial_identification.adsi
            )
            self.adsi_edit.setText("" if adsi is None else str(adsi))
            self.adsi_edit.setToolTip(
                "SPR-KKR CONTROL.ADSI. An additional identifier for the calculation."
            )
            identifier_form.addRow("Calculation label:", self.adsi_edit)
            adsi_hint = QLabel(
                "Additional calculation identifier (CONTROL.ADSI).", identifiers
            )
            adsi_hint.setWordWrap(True)
            identifier_form.addRow("", adsi_hint)
            layout.addWidget(identifiers)

        profile_box = QGroupBox("Run configuration", self)
        profile_layout = QVBoxLayout(profile_box)
        select_row = QHBoxLayout()
        self.profiles = QComboBox(profile_box)
        self.profiles.setMinimumContentsLength(24)
        self.profiles.currentIndexChanged.connect(self._update_description)
        select_row.addWidget(self.profiles, 1)
        self.edit_profiles_button = QPushButton("Manage Profiles…", profile_box)
        self.edit_profiles_button.clicked.connect(self._edit_profiles)
        select_row.addWidget(self.edit_profiles_button)
        profile_layout.addLayout(select_row)
        self.description = QLabel(profile_box)
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        profile_layout.addWidget(self.description)
        layout.addWidget(profile_box)

        self.project_box = QGroupBox("Project", self)
        project_row = QHBoxLayout(self.project_box)
        self.project_selector = QComboBox(self.project_box)
        self._load_projects(active_project_id)
        self.project_selector.currentIndexChanged.connect(self._project_changed)
        project_row.addWidget(self.project_selector, 1)
        self.new_project_button = QPushButton("New…", self.project_box)
        self.new_project_button.setToolTip(
            "Create a subproject of the selected project, or a top-level "
            "project when Unassigned is selected."
        )
        self.new_project_button.clicked.connect(self._create_project)
        project_row.addWidget(self.new_project_button)
        self.edit_project_button = QPushButton("Edit…", self.project_box)
        self.edit_project_button.clicked.connect(self._edit_project)
        project_row.addWidget(self.edit_project_button)
        layout.addWidget(self.project_box)
        self.project_box.setVisible(require_directory)

        directory_box = QGroupBox("Working directory", self)
        directory_layout = QVBoxLayout(directory_box)
        directory_row = QHBoxLayout()
        self.directory_edit = QLineEdit(directory_box)
        self.directory_edit.setText(directory or "")
        self.directory_edit.textEdited.connect(self._directory_edited)
        self.directory_edit.setPlaceholderText("Select the calculation directory")
        directory_row.addWidget(self.directory_edit, 1)
        browse = QPushButton("Browse…", directory_box)
        browse.clicked.connect(self._browse_directory)
        directory_row.addWidget(browse)
        directory_layout.addLayout(directory_row)
        self.assign_directory_checkbox = QCheckBox(
            "Assign working directory to selected project", directory_box
        )
        self.assign_directory_checkbox.setToolTip(
            "Save the directory above as the project's default working directory "
            "when starting this calculation."
        )
        directory_layout.addWidget(self.assign_directory_checkbox)
        self.assign_directory_checkbox.clicked.connect(
            self._directory_assignment_changed
        )
        self.directory_edit.textChanged.connect(self._refresh_directory_assignment)
        layout.addWidget(directory_box)
        directory_box.setVisible(require_directory)
        self._project_changed()
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._reload_profiles(selected_profile_name)

    def _load_projects(self, selected_project_id: str | None) -> None:
        """Reload project choices and select an ID rather than a display label."""
        try:
            projects = tuple(self._projects.projects())
        except (ProjectRepositoryError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Projects Unavailable", str(exc))
            return

        by_id = {project.id: project for project in projects}
        self._projects_by_id = by_id

        def label(project):
            parts = [project.name]
            seen = {project.id}
            parent_id = project.parent_id
            while parent_id in by_id and parent_id not in seen:
                seen.add(parent_id)
                ancestor = by_id[parent_id]
                parts.insert(0, ancestor.name)
                parent_id = ancestor.parent_id
            return " / ".join(parts)

        self.project_selector.clear()
        self.project_selector.addItem("Unassigned (no project)", None)
        for project in sorted(projects, key=lambda item: label(item).casefold()):
            self.project_selector.addItem(label(project), project.id)
        selected = self.project_selector.findData(selected_project_id)
        self.project_selector.setCurrentIndex(max(selected, 0))

    def _directory_edited(self, text: str) -> None:
        # QLineEdit.textEdited is emitted only for user edits; setText() from
        # _project_changed does not turn a project default into an override.
        self._explicit_directory = text

    def _project_changed(self) -> None:
        project = self._projects_by_id.get(self.project_id())
        project_directory = None if project is None else project.directory
        desired = (
            self._explicit_directory
            if self._explicit_directory is not None
            else project_directory or self._fallback_directory
        )
        if hasattr(self, "directory_edit") and self.directory_edit.text() != desired:
            self.directory_edit.setText(desired)
        if hasattr(self, "edit_project_button"):
            self.edit_project_button.setEnabled(project is not None)
        if hasattr(self, "assign_directory_checkbox"):
            self._refresh_directory_assignment()

    def _refresh_directory_assignment(self, _text: str = "") -> None:
        """Only allow assigning a directory when it would change the project."""
        project = self._projects_by_id.get(self.project_id())
        directory = self.directory_name()
        differs = (
            project is not None
            and directory is not None
            and directory != project.directory
        )
        self.assign_directory_checkbox.setEnabled(differs)
        self.assign_directory_checkbox.setChecked(
            self._directory_assignment_overrides.get(
                project.id, project.directory is None
            ) if differs else False
        )

    def _directory_assignment_changed(self, checked: bool) -> None:
        project_id = self.project_id()
        if project_id is not None:
            self._directory_assignment_overrides[project_id] = checked

    def project_id(self) -> str | None:
        """Return the project selected for this run, or None if unassigned."""
        return self.project_selector.currentData()

    def _create_project(self) -> None:
        """Create and select a new project with its optional directory."""
        dialog = ProjectEditDialog(
            self, directory=self.directory_name(),
            title="New Project",
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            created = self._projects.create(
                dialog.project_name(), parent_id=self.project_id(),
                directory=dialog.project_directory(),
            )
        except (ProjectRepositoryError, KeyError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Create Project Failed", str(exc))
            return
        self._load_projects(created.id)
        self._project_changed()

    def _edit_project(self) -> None:
        """Edit the selected project without changing the current run setup."""
        project = self._projects_by_id.get(self.project_id())
        if project is None:
            return
        dialog = ProjectEditDialog(
            self, name=project.name, directory=project.directory,
            title="Edit Project",
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            updated = project.modify(
                name=dialog.project_name(),
                directory=dialog.project_directory(),
            )
            if updated == project:
                return
            self._projects.save(updated, expected_generation=project.generation)
        except (ProjectRepositoryError, KeyError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Edit Project Failed", str(exc))
            self._load_projects(project.id)
            return
        self._load_projects(project.id)
        self._project_changed()

    def _reload_profiles(self, selected: str | None = None) -> None:
        if selected is None and self.profiles.count():
            selected = self.profiles.currentData()
        self.profiles.clear()
        names = self._store.names()
        if not names:
            self.profiles.addItem("Automatic / built-in", None)
        else:
            for name in names:
                self.profiles.addItem(name, name)
        default = self._store.resolved_name(None)
        wanted = selected if selected in names else default
        index = self.profiles.findData(wanted)
        self.profiles.setCurrentIndex(max(index, 0))
        self._update_description()

    def _update_description(self) -> None:
        try:
            text = self._store.describe(self.profiles.currentData())
        except (KeyError, TypeError, ValueError) as exc:
            text = f"Profile cannot be resolved: {exc}"
        self.description.setText(text)

    def _edit_profiles(self) -> None:
        """Open only the reusable run-configuration editor, not all Settings."""
        selected = self.profiles.currentData()
        if ProfilesDialog(self, store=self._store).exec() == QDialog.DialogCode.Accepted:
            self._reload_profiles(selected)

    def directory_name(self) -> str | None:
        """Return the directory selected for this calculation."""
        value = self.directory_edit.text().strip()
        return str(Path(value).expanduser().resolve()) if value else None

    def _browse_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Calculation Directory",
            self.directory_name() or str(Path.home()),
        )
        if selected:
            self.directory_edit.setText(selected)
            self._directory_edited(selected)

    def accept(self) -> None:  # type: ignore[override]
        if self._require_directory and not self.directory_name():
            QMessageBox.warning(
                self,
                "Calculation Directory Required",
                "Choose a working directory before starting the calculation.",
            )
            self.directory_edit.setFocus()
            return
        if self.dataset_edit is not None and not self.dataset_edit.hasAcceptableInput():
            QMessageBox.warning(
                self, "Invalid output prefix",
                "Use only letters, digits, periods, underscores and hyphens.",
            )
            return
        if self.dataset_edit is not None:
            dataset = self.dataset_edit.text().strip()
            if dataset and filename_component(dataset) != dataset:
                QMessageBox.warning(
                    self, "Invalid output prefix",
                    "The output prefix must be a valid single filename component.",
                )
                return
        if self.adsi_edit is not None and not self.adsi_edit.text().strip():
            QMessageBox.warning(
                self, "Missing calculation label",
                "Enter a calculation label (SPR-KKR CONTROL.ADSI).",
            )
            return
        if (
            self._require_directory
            and self.assign_directory_checkbox.isEnabled()
            and self.assign_directory_checkbox.isChecked()
        ):
            project = self._projects_by_id.get(self.project_id())
            directory = self.directory_name()
            if project is not None and directory is not None:
                updated = project.modify(directory=directory)
                if updated != project:
                    try:
                        self._projects.save(
                            updated, expected_generation=project.generation
                        )
                    except (ProjectRepositoryError, KeyError, OSError, ValueError) as exc:
                        QMessageBox.warning(
                            self, "Assign Project Directory Failed", str(exc)
                        )
                        return
        super().accept()

    def identification(self) -> RunIdentification | None:
        """Return accepted run identifiers without changing input parameters."""
        if self.dataset_edit is None or self.adsi_edit is None:
            return None
        return RunIdentification(
            dataset=self.dataset_edit.text().strip() or None,
            adsi=self.adsi_edit.text().strip(),
        )

    def profile_name(self) -> str | None:
        value = self.profiles.currentData()
        return None if value is None else str(value)


def select_execution_profile(parent: QWidget | None = None) -> str | None:
    """Return the selected profile name, or ``None`` if cancelled/automatic."""
    dialog = ProfileSelectionDialog(parent, require_directory=False)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.profile_name()
