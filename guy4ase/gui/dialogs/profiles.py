"""Execution-profile dialogs for SPR-KKR calculations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from ase2sprkkr.execution import ProjectRepository, ProjectRepositoryError

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.execution_profiles import (
    ExecutionProfileEditor,
    ExecutionProfileStore,
    draft_kind,
    kind_label,
)
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.input_parameters.dataset import dataset_value, filename_component
from guy4ase.gui.widgets.execution_profiles import ProfileForm


@dataclass(frozen=True)
class RunIdentification:
    """Output identifiers for a single calculation, independent of its profile."""

    dataset: str | None
    adsi: str


class ProfilesDialog(QDialog):
    """Edit persistent ASE2SPRKKR execution profiles."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        store: ExecutionProfileStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store or ExecutionProfileStore()
        self._editor = ExecutionProfileEditor(self._store)
        self._drafts = self._editor.drafts

        self.setWindowTitle("SPR-KKR Execution Profiles")
        self.setMinimumSize(1040, 680)
        manage_window_geometry(
            self,
            "execution-profiles",
            default_size=(1200, 800),
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(12)

        heading = QLabel("Execution profiles", self)
        heading_font = heading.font()
        heading_font.setPointSize(heading_font.pointSize() + 3)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        root.addWidget(heading)
        intro = QLabel(
            "Profiles define where SPR-KKR runs and how executables, MPI and remote workspaces are configured.",
            self,
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QWidget(splitter)
        left.setMinimumWidth(230)
        left.setMaximumWidth(330)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)
        list_heading = QLabel("Profiles", left)
        list_font = list_heading.font()
        list_font.setBold(True)
        list_heading.setFont(list_font)
        left_layout.addWidget(list_heading)
        self.list = QListWidget(left)
        self.list.setAlternatingRowColors(True)
        self.list.currentItemChanged.connect(self._selection_changed)
        left_layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.add_button = QPushButton("New…", left)
        self.delete_button = QPushButton("Delete", left)
        self.add_button.clicked.connect(self._add_profile)
        self.delete_button.clicked.connect(self._delete_profile)
        row.addWidget(self.add_button)
        row.addWidget(self.delete_button)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        self.form = ProfileForm(splitter)
        splitter.addWidget(self.form)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 700])

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._reload_list()

    def _store_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        draft = self._drafts[name]
        if not draft.read_only:
            draft.values = self.form.values()

    def _reload_list(self, select: str | None = None) -> None:
        current = select
        if current is None and self.list.currentItem() is not None:
            current = str(self.list.currentItem().data(Qt.ItemDataRole.UserRole))
        self.list.blockSignals(True)
        self.list.clear()
        for name in sorted(self._drafts):
            draft = self._drafts[name]
            kind = kind_label(draft_kind(draft.values))
            suffix = " · read-only" if draft.read_only else ""
            item = QListWidgetItem(f"{name}\n{kind}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == current:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._selection_changed(self.list.currentItem(), None)

    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if previous is not None:
            name = str(previous.data(Qt.ItemDataRole.UserRole))
            draft = self._drafts.get(name)
            if draft is not None and not draft.read_only:
                draft.values = self.form.values()
        if current is None:
            self.form.setEnabled(False)
            self.delete_button.setEnabled(False)
            return
        name = str(current.data(Qt.ItemDataRole.UserRole))
        draft = self._drafts[name]
        self.form.setEnabled(True)
        self.form.title.setText(name)
        self.form.load(draft)
        self.delete_button.setEnabled(not draft.read_only)

    def _add_profile(self) -> None:
        self._store_current()
        name, ok = QInputDialog.getText(self, "New Execution Profile", "Profile name:")
        if not ok:
            return
        try:
            draft = self._editor.add(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Profile Name", str(exc))
            return
        self._reload_list(draft.name)

    def _delete_profile(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        self._editor.delete(name)
        self._reload_list()

    def accept(self) -> None:  # type: ignore[override]
        self._store_current()
        try:
            self._editor.save()
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
    ) -> None:
        super().__init__(parent)
        self._require_directory = require_directory
        self._projects = project_repository if project_repository is not None else ProjectRepository()
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
            self.dataset_edit.setText(dataset_value(input_parameters) or "")
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
            adsi = input_parameters.CONTROL.ADSI()
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
        project_row.addWidget(self.project_selector, 1)
        self.new_project_button = QPushButton("New…", self.project_box)
        self.new_project_button.setToolTip(
            "Create a subproject of the selected project, or a top-level "
            "project when Unassigned is selected."
        )
        self.new_project_button.clicked.connect(self._create_project)
        project_row.addWidget(self.new_project_button)
        layout.addWidget(self.project_box)
        self.project_box.setVisible(require_directory)

        directory_box = QGroupBox("Working directory", self)
        directory_row = QHBoxLayout(directory_box)
        self.directory_edit = QLineEdit(directory_box)
        self.directory_edit.setText(directory or "")
        self.directory_edit.setPlaceholderText("Select the calculation directory")
        directory_row.addWidget(self.directory_edit, 1)
        browse = QPushButton("Browse…", directory_box)
        browse.clicked.connect(self._browse_directory)
        directory_row.addWidget(browse)
        layout.addWidget(directory_box)
        directory_box.setVisible(require_directory)
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._reload_profiles()

    def _load_projects(self, selected_project_id: str | None) -> None:
        """Reload project choices and select an ID rather than a display label."""
        try:
            projects = tuple(self._projects.projects())
        except (ProjectRepositoryError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Projects Unavailable", str(exc))
            return

        by_id = {project.id: project for project in projects}

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

    def project_id(self) -> str | None:
        """Return the project selected for this run, or None if unassigned."""
        return self.project_selector.currentData()

    def _create_project(self) -> None:
        """Create and immediately select a project without changing the workspace."""
        name, accepted = QInputDialog.getText(self, "New Project", "Project name:")
        if not accepted:
            return
        try:
            created = self._projects.create(
                name.strip(), parent_id=self.project_id()
            )
        except (ProjectRepositoryError, KeyError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Create Project Failed", str(exc))
            return
        self._load_projects(created.id)

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
