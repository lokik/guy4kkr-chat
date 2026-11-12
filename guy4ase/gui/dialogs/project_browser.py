"""Three-pane browser for projects, persistent runs, and results."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from ase2sprkkr.execution import (
    Project,
    ProjectConflictError,
    ProjectRepository,
    ProjectRepositoryError,
)

from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.dialogs.object_view import execute_value_action
from guy4ase.gui.widgets.persistent_jobs import PersistentJobsWidget

_PROJECT_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_UNASSIGNED = "__unassigned__"


class _RepositorySignals(QObject):
    changed = pyqtSignal(str)


class ProjectBrowserDialog(QDialog):
    """Browse projects and their immutable project-owned run history."""

    activeProjectRequested = pyqtSignal(object)

    def __init__(
        self,
        repository: ProjectRepository,
        persistent_jobs_controller: PersistentJobsController,
        parent: QWidget | None = None,
        *,
        active_project_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project Browser")
        manage_window_geometry(
            self,
            "project-browser",
            default_size=(1400, 760),
        )
        self._repository = repository
        self._persistent_jobs_controller = persistent_jobs_controller
        self._projects: tuple[Project, ...] = ()
        self._projects_by_id: dict[str, Project] = {}
        self._selected_project_id: str | None = None
        self._active_project_id = active_project_id

        self._repository_signals = _RepositorySignals(self)
        self._repository_signals.changed.connect(self._repository_changed)
        self._unsubscribe_projects = self._repository.subscribe(
            self._repository_signals.changed.emit
        )
        self.destroyed.connect(lambda *_args: self._unsubscribe_projects())

        root = QVBoxLayout(self)
        self.project_notice = QLabel(self)
        self.project_notice.setWordWrap(True)
        self.project_notice.hide()
        root.addWidget(self.project_notice)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        project_panel = QWidget(splitter)
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)

        self.active_project_label = QLabel(project_panel)
        project_layout.addWidget(self.active_project_label)
        active_buttons = QHBoxLayout()
        self.set_active_project_button = QPushButton("Set active", project_panel)
        self.set_active_project_button.clicked.connect(self._request_selected_active)
        active_buttons.addWidget(self.set_active_project_button)
        self.clear_active_project_button = QPushButton("Clear active", project_panel)
        self.clear_active_project_button.clicked.connect(
            lambda _checked=False: self.activeProjectRequested.emit(None)
        )
        active_buttons.addWidget(self.clear_active_project_button)
        project_layout.addLayout(active_buttons)

        project_buttons = QHBoxLayout()
        self.new_project_button = QPushButton("New", project_panel)
        self.new_project_button.clicked.connect(self._create_project)
        project_buttons.addWidget(self.new_project_button)
        self.rename_project_button = QPushButton("Rename", project_panel)
        self.rename_project_button.clicked.connect(self._rename_project)
        project_buttons.addWidget(self.rename_project_button)
        self.move_project_button = QPushButton("Move", project_panel)
        self.move_project_button.clicked.connect(self._move_project)
        project_buttons.addWidget(self.move_project_button)
        self.delete_project_button = QPushButton("Delete", project_panel)
        self.delete_project_button.clicked.connect(self._delete_project)
        project_buttons.addWidget(self.delete_project_button)
        project_layout.addLayout(project_buttons)

        self.project_tree = QTreeWidget(project_panel)
        self.project_tree.setColumnCount(2)
        self.project_tree.setHeaderLabels(("Project", "Runs"))
        self.project_tree.setRootIsDecorated(True)
        self.project_tree.setAlternatingRowColors(True)
        header = self.project_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.project_tree.currentItemChanged.connect(self._project_selection_changed)
        project_layout.addWidget(self.project_tree, 1)

        self.refresh_projects_button = QPushButton("Refresh projects", project_panel)
        self.refresh_projects_button.clicked.connect(self._refresh_projects)
        project_layout.addWidget(self.refresh_projects_button)

        self.jobs = PersistentJobsWidget(
            lambda value, action: execute_value_action(value, action, self),
            splitter,
        )
        self._persistent_jobs_controller.bind_view(self.jobs)
        self.jobs.jobsChanged.connect(self._refresh_project_projection)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 1100])

        self.reload_projects()

    @property
    def active_project_id(self) -> str | None:
        return self._active_project_id

    def set_active_project(self, project_id: str | None) -> None:
        """Render the application-owned active project selection."""
        if project_id is not None and project_id not in self._projects_by_id:
            project_id = None
        self._active_project_id = project_id
        project = self._projects_by_id.get(project_id) if project_id is not None else None
        self.active_project_label.setText(
            "Active project: (none)"
            if project is None
            else f"Active project: {project.name}"
        )
        self.active_project_label.setToolTip("" if project is None else project.id)
        self._refresh_action_availability()

    @pyqtSlot(str)
    def _repository_changed(self, _project_id: str) -> None:
        self.reload_projects()

    def _refresh_projects(self) -> None:
        try:
            self._repository.refresh()
        except (ProjectRepositoryError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "Project Refresh Failed", str(exc))
            return
        self.reload_projects()

    def reload_projects(self) -> None:
        """Reload project JSONs, preserving selection when possible."""
        try:
            projects = tuple(self._repository.projects())
        except (ProjectRepositoryError, OSError, ValueError) as exc:
            self._projects = ()
            self._projects_by_id = {}
            self.project_tree.clear()
            self.project_notice.setText(f"Project repository unavailable: {exc}")
            self.project_notice.show()
            self.jobs.set_visible_refs(())
            self.set_active_project(None)
            self._refresh_action_availability()
            return

        self._projects = projects
        self._projects_by_id = {project.id: project for project in projects}
        if (
            self._active_project_id is not None
            and self._active_project_id not in self._projects_by_id
        ):
            self._active_project_id = None
            self.activeProjectRequested.emit(None)
        self._refresh_project_projection()
        self.set_active_project(self._active_project_id)

    def _refresh_project_projection(self) -> None:
        self._populate_project_tree()
        self._apply_project_selection()
        self._refresh_action_availability()

    def _populate_project_tree(self) -> None:
        previous = self._selected_project_id
        available_refs = {job.id for job in self.jobs.all_jobs}
        children: dict[str | None, list[Project]] = defaultdict(list)
        for project in self._projects:
            children[project.parent_id].append(project)
        for siblings in children.values():
            siblings.sort(key=lambda project: project.name.casefold())

        unassigned_refs = {
            job.id for job in self.jobs.all_jobs
            if job.project_id not in self._projects_by_id
        }

        self.project_tree.blockSignals(True)
        try:
            self.project_tree.clear()
            selected_item: QTreeWidgetItem | None = None

            def add_project(project: Project, parent: QTreeWidgetItem | None) -> None:
                nonlocal selected_item
                total = sum(
                    job.project_id == project.id for job in self.jobs.all_jobs
                )
                item = QTreeWidgetItem([project.name, str(total)])
                item.setData(0, _PROJECT_ID_ROLE, project.id)
                item.setToolTip(0, project.id)
                if parent is None:
                    self.project_tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                if project.id == previous:
                    selected_item = item
                for child in children.get(project.id, ()):
                    add_project(child, item)

            for project in children.get(None, ()):
                add_project(project, None)

            if unassigned_refs:
                item = QTreeWidgetItem(["Unassigned", str(len(unassigned_refs))])
                item.setData(0, _PROJECT_ID_ROLE, _UNASSIGNED)
                self.project_tree.addTopLevelItem(item)
                if previous == _UNASSIGNED:
                    selected_item = item

            self.project_tree.expandAll()
            if selected_item is None and self.project_tree.topLevelItemCount():
                selected_item = self.project_tree.topLevelItem(0)
            if selected_item is None:
                self._selected_project_id = None
            else:
                self.project_tree.setCurrentItem(selected_item)
                self._selected_project_id = str(
                    selected_item.data(0, _PROJECT_ID_ROLE)
                )
        finally:
            self.project_tree.blockSignals(False)

    def _project_selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        value = None if current is None else current.data(0, _PROJECT_ID_ROLE)
        self._selected_project_id = None if value is None else str(value)
        self._apply_project_selection()
        self._refresh_action_availability()

    def _apply_project_selection(self) -> None:
        project_id = self._selected_project_id
        available_refs = {job.id for job in self.jobs.all_jobs}
        if project_id is None:
            self.jobs.set_visible_refs(())
            self.project_notice.hide()
            return

        if project_id == _UNASSIGNED:
            self.jobs.set_visible_refs(
                job.id for job in self.jobs.all_jobs
                if job.project_id not in self._projects_by_id
            )
            self.project_notice.hide()
            return

        project = self._projects_by_id.get(project_id)
        self.jobs.set_visible_refs(
            () if project is None else (
                job.id for job in self.jobs.all_jobs
                if job.project_id == project.id
            )
        )
        self.project_notice.hide()

    def _selected_project(self) -> Project | None:
        project_id = self._selected_project_id
        if project_id in (None, _UNASSIGNED):
            return None
        return self._projects_by_id.get(project_id)

    def _request_selected_active(self) -> None:
        project = self._selected_project()
        if project is not None:
            self.activeProjectRequested.emit(project.id)

    def _refresh_action_availability(self) -> None:
        project = self._selected_project()
        self.rename_project_button.setEnabled(project is not None)
        self.move_project_button.setEnabled(project is not None)
        self.delete_project_button.setEnabled(project is not None)
        self.set_active_project_button.setEnabled(
            project is not None and project.id != self._active_project_id
        )
        self.clear_active_project_button.setEnabled(self._active_project_id is not None)
    def _create_project(self) -> None:
        name, accepted = QInputDialog.getText(self, "New Project", "Project name:")
        if not accepted:
            return
        parent = self._selected_project()
        try:
            created = self._repository.create(
                name,
                parent_id=None if parent is None else parent.id,
            )
        except (ProjectRepositoryError, KeyError, ValueError) as exc:
            QMessageBox.warning(self, "Create Project Failed", str(exc))
            return
        self._selected_project_id = created.id
        self.reload_projects()

    def _rename_project(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Rename Project",
            "Project name:",
            text=project.name,
        )
        if not accepted:
            return
        self._save_project_change(
            project,
            lambda current: current.rename(name),
            "Rename Project",
        )

    def _move_project(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        candidates = [item for item in self._projects if item.id != project.id]
        labels = ["(root)"] + [
            f"{item.name} [{item.id[:8]}]" for item in candidates
        ]
        label, accepted = QInputDialog.getItem(
            self,
            "Move Project",
            "New parent:",
            labels,
            editable=False,
        )
        if not accepted:
            return
        parent_id = None
        if label != "(root)":
            parent_id = candidates[labels.index(label) - 1].id
        self._save_project_change(
            project,
            lambda current: current.move_to(parent_id),
            "Move Project",
        )

    def _delete_project(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Project?",
            f"Delete project {project.name!r}? Persistent calculation runs are not deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._repository.delete(
                project.id,
                expected_generation=project.generation,
            )
        except (ProjectRepositoryError, KeyError) as exc:
            QMessageBox.warning(self, "Delete Project Failed", str(exc))
            return
        if project.id == self._active_project_id:
            self.activeProjectRequested.emit(None)
        self._selected_project_id = project.parent_id
        self.reload_projects()

    def _save_project_change(
        self,
        original: Project,
        change: Callable[[Project], Project],
        title: str,
    ) -> Project | None:
        try:
            edited = change(original)
        except ValueError as exc:
            QMessageBox.warning(self, f"{title} Failed", str(exc))
            return None
        if edited == original:
            return original

        try:
            saved = self._repository.save(
                edited,
                expected_generation=original.generation,
            )
        except ProjectConflictError:
            answer = QMessageBox.question(
                self,
                "Project Changed",
                "This project was modified by another Guy4ASE instance. "
                "Apply your change to the newer version instead?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.reload_projects()
                return None
            try:
                current = self._repository.project(original.id)
                edited = change(current)
                if edited == current:
                    saved = current
                else:
                    saved = self._repository.save(
                        edited,
                        expected_generation=current.generation,
                    )
            except ProjectConflictError:
                QMessageBox.warning(
                    self,
                    f"{title} Failed",
                    "The project changed again while applying your edit. Please retry.",
                )
                self.reload_projects()
                return None
            except (ProjectRepositoryError, KeyError, ValueError) as exc:
                QMessageBox.warning(self, f"{title} Failed", str(exc))
                self.reload_projects()
                return None
        except (ProjectRepositoryError, KeyError, ValueError) as exc:
            QMessageBox.warning(self, f"{title} Failed", str(exc))
            return None

        self._selected_project_id = saved.id
        self.reload_projects()
        return saved
