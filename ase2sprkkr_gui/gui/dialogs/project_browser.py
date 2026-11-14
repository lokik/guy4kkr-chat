"""Three-pane browser for projects, persistent runs, and results."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon, QPaintEvent
from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSizePolicy,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from kkrunner.projects import Project, ProjectConflictError, ProjectDeleteError, ProjectRepository, ProjectRepositoryError

from ase2sprkkr_gui.gui.application.window_geometry import manage_window_geometry
from ase2sprkkr_gui.gui.controllers.persistent_jobs import PersistentJobsController
from ase2sprkkr_gui.gui.dialogs.assign_results import AssignResultsDialog
from ase2sprkkr_gui.gui.dialogs.object_view import execute_value_action
from ase2sprkkr_gui.gui.dialogs.project_edit import ProjectEditDialog
from ase2sprkkr_gui.gui.widgets.persistent_jobs import PersistentJobsWidget

_PROJECT_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_UNASSIGNED = "__unassigned__"


class _RepositorySignals(QObject):
    changed = pyqtSignal(str)
    initialLoaded = pyqtSignal(object)


class ProjectBrowserDialog(QWidget):
    """Non-modal window for projects and their immutable run history."""

    activeProjectRequested = pyqtSignal(object)
    addResultRequested = pyqtSignal(str)

    def __init__(
        self,
        repository: ProjectRepository,
        persistent_jobs_controller: PersistentJobsController,
        parent: QWidget | None = None,
        *,
        active_project_id: str | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowTitle("Project Browser")
        # Paint the native window with its palette rather than exposing an
        # uninitialized surface while the first project snapshot is loading.
        self.setAutoFillBackground(True)
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
        self._initial_load_complete = False
        self._initial_paint_seen = False
        self._initial_load_timer = QTimer(self)
        self._initial_load_timer.setSingleShot(True)
        # Allow the compositor to present the placeholder before doing any
        # potentially expensive initial tree projection on the GUI thread.
        self._initial_load_timer.setInterval(50)
        self._initial_load_timer.timeout.connect(self._start_initial_load)
        self._initial_load_pending = False
        self._initial_future: Future[tuple[Project, ...]] | None = None
        self._project_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ase2sprkkr_gui-project-browser"
        )
        self.destroyed.connect(
            lambda *_args, pool=self._project_executor: pool.shutdown(
                wait=False, cancel_futures=True
            )
        )

        self._repository_signals = _RepositorySignals(self)
        self._repository_signals.changed.connect(self._repository_changed)
        self._repository_signals.initialLoaded.connect(
            self._initial_projects_loaded, Qt.ConnectionType.QueuedConnection
        )
        self._unsubscribe_projects = self._repository.subscribe(
            self._repository_signals.changed.emit
        )
        self.destroyed.connect(lambda *_args: self._unsubscribe_projects())

        root = QVBoxLayout(self)
        self.project_notice = QLabel(self)
        self.project_notice.setWordWrap(True)
        self.project_notice.setText("Loading projects and saved calculations…")
        root.addWidget(self.project_notice)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        project_panel = QWidget(splitter)
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_heading = QLabel("Projects", project_panel)
        heading_font = project_heading.font()
        heading_font.setBold(True)
        project_heading.setFont(heading_font)
        project_layout.addWidget(project_heading)

        self.project_tree = QTreeWidget(project_panel)
        self.project_tree.setColumnCount(2)
        self.project_tree.setHeaderLabels(("Project", "Results"))
        self.project_tree.setRootIsDecorated(True)
        self.project_tree.setAlternatingRowColors(True)
        header = self.project_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.project_tree.currentItemChanged.connect(self._project_selection_changed)
        self.project_tree.addTopLevelItem(QTreeWidgetItem(["Loading projects…", ""]))
        self.project_tree.setEnabled(False)

        self.jobs = PersistentJobsWidget(
            lambda value, action: execute_value_action(value, action, self),
            splitter,
            auto_load_results=True,
            show_project_actions=True,
        )
        self.jobs.backend_notice.setText("Loading saved calculations…")
        self.jobs.backend_notice.show()
        self.jobs.tree.setEnabled(False)
        self.jobs.set_project_assignment_available(
            self._persistent_jobs_controller.supports_reassignment
        )
        self.jobs.moveRunsRequested.connect(self._move_selected_runs)
        self.jobs.addResultRequested.connect(self._request_add_result)
        self.jobs.jobsChanged.connect(self._refresh_project_projection)


        project_layout.addWidget(self.project_tree, 1)

        # Project management belongs directly below its tree.
        project_buttons = QGridLayout()
        project_buttons.setColumnStretch(0, 1)
        project_buttons.setColumnStretch(1, 1)
        self.new_project_button = QPushButton("New", project_panel)
        self.new_project_button.setIcon(QIcon.fromTheme(
            "document-new",
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder),
        ))
        self.new_project_button.setToolTip("Create a project under the selected project.")
        self.new_project_button.clicked.connect(self._create_project)
        project_buttons.addWidget(self.new_project_button, 0, 0)

        self.edit_project_button = QPushButton("Edit", project_panel)
        self.edit_project_button.setIcon(QIcon.fromTheme(
            "document-edit",
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
        ))
        self.edit_project_button.setToolTip("Edit the selected project's name and directory.")
        self.edit_project_button.clicked.connect(self._edit_project)
        project_buttons.addWidget(self.edit_project_button, 0, 1)

        self.move_project_button = QPushButton("Move", project_panel)
        self.move_project_button.setIcon(QIcon.fromTheme(
            "go-jump", self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight),
        ))
        self.move_project_button.setToolTip("Move the selected project under another parent.")
        self.move_project_button.clicked.connect(self._move_project)
        project_buttons.addWidget(self.move_project_button, 1, 0)

        self.delete_project_button = QPushButton("Delete", project_panel)
        self.delete_project_button.setIcon(QIcon.fromTheme(
            "edit-delete", self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon),
        ))
        self.delete_project_button.setToolTip("Delete the selected project and its completed run history.")
        self.delete_project_button.clicked.connect(self._delete_project)
        project_buttons.addWidget(self.delete_project_button, 1, 1)

        self.refresh_projects_button = QPushButton("Refresh projects", project_panel)
        self.refresh_projects_button.setIcon(QIcon.fromTheme(
            "view-refresh", self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
        ))
        self.refresh_projects_button.setToolTip("Reload the project repository.")
        self.refresh_projects_button.clicked.connect(self._refresh_projects)
        project_buttons.addWidget(self.refresh_projects_button, 2, 0)
        for button in (
            self.new_project_button,
            self.edit_project_button,
            self.move_project_button,
            self.delete_project_button,
            self.refresh_projects_button,
        ):
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
        project_layout.addLayout(project_buttons)

        active_group = QGroupBox("Active project", project_panel)
        active_layout = QVBoxLayout(active_group)
        self.active_project_label = QLabel(active_group)
        self.active_project_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        active_layout.addWidget(self.active_project_label)
        active_buttons = QGridLayout()
        active_buttons.setColumnStretch(0, 1)
        active_buttons.setColumnStretch(1, 1)
        self.set_active_project_button = QPushButton("Set active", active_group)
        self.set_active_project_button.setToolTip(
            "Use the selected project for new calculations."
        )
        self.set_active_project_button.clicked.connect(self._request_selected_active)
        active_buttons.addWidget(self.set_active_project_button, 0, 0)
        self.clear_active_project_button = QPushButton("Clear active", active_group)
        self.clear_active_project_button.setToolTip(
            "Clear the project used by new calculations."
        )
        self.clear_active_project_button.clicked.connect(
            lambda _checked=False: self.activeProjectRequested.emit(None)
        )
        active_buttons.addWidget(self.clear_active_project_button, 0, 1)
        for button in (self.set_active_project_button, self.clear_active_project_button):
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
        active_layout.addLayout(active_buttons)
        project_layout.addWidget(active_group)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 980])

        self._refresh_action_availability()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Start initialization only after Qt has painted the loading placeholder."""
        super().paintEvent(event)
        if not self._initial_paint_seen and not self._initial_load_complete:
            self._initial_paint_seen = True
            self._initial_load_timer.start()

    @property
    def active_project_id(self) -> str | None:
        return self._active_project_id

    def set_active_project(self, project_id: str | None) -> None:
        """Render the application-owned active project selection."""
        if (
            self._initial_load_complete
            and project_id is not None
            and project_id not in self._projects_by_id
        ):
            project_id = None
        self._active_project_id = project_id
        project = self._projects_by_id.get(project_id) if project_id is not None else None
        self.active_project_label.setText(
            "Loading…" if not self._initial_load_complete
            else "(none)" if project is None else project.name
        )
        self.active_project_label.setToolTip("" if project is None else project.id)
        self._refresh_action_availability()

    def _start_initial_load(self) -> None:
        """Read the project repository off-thread; Qt widgets stay on the GUI thread."""
        if self._initial_load_complete or self._initial_future is not None:
            return
        if not self.isVisible():
            # The browser may have been closed before its first load began.
            # A subsequent show/paint will restart the timer.
            self._initial_paint_seen = False
            return
        future = self._project_executor.submit(self._repository.projects)
        self._initial_future = future
        signals = self._repository_signals

        def notify(completed: Future[tuple[Project, ...]]) -> None:
            try:
                signals.initialLoaded.emit(completed)
            except RuntimeError:
                # The window can be deleted while its filesystem read is running.
                pass

        future.add_done_callback(notify)

    @pyqtSlot(object)
    def _initial_projects_loaded(self, future: Future[tuple[Project, ...]]) -> None:
        if future is not self._initial_future:
            return
        self._initial_future = None
        if self._initial_load_pending:
            # A project changed during the read: take a fresh snapshot instead.
            self._initial_load_pending = False
            self._start_initial_load()
            return

        self._initial_load_complete = True
        self.project_tree.setEnabled(True)
        self.jobs.tree.setEnabled(True)
        try:
            projects = tuple(future.result())
        except (ProjectRepositoryError, OSError, ValueError) as exc:
            error = str(exc)
            self._projects = ()
            self._projects_by_id = {}
        else:
            error = None
            self._remember_projects(projects)

        # Binding projects the cached jobs into Qt widgets and triggers the
        # initial tree projection. Result parsing is already asynchronous.
        self._persistent_jobs_controller.bind_view(self.jobs)
        if error is not None:
            self.project_notice.setText(f"Project repository unavailable: {error}")
            self.project_notice.show()
        else:
            self.project_notice.hide()
        self.set_active_project(self._active_project_id)
        self._refresh_action_availability()

    @pyqtSlot(str)
    def _repository_changed(self, _project_id: str) -> None:
        if not self._initial_load_complete:
            self._initial_load_pending = True
            return
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
        if not self._initial_load_complete:
            self._initial_load_pending = True
            return
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

        self._remember_projects(projects)
        self._refresh_project_projection()
        self.set_active_project(self._active_project_id)

    def _remember_projects(self, projects: tuple[Project, ...]) -> None:
        self._projects = projects
        self._projects_by_id = {project.id: project for project in projects}
        if (
            self._active_project_id is not None
            and self._active_project_id not in self._projects_by_id
        ):
            self._active_project_id = None
            self.activeProjectRequested.emit(None)

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
        if project_id is None:
            refs = ()
        elif project_id == _UNASSIGNED:
            refs = tuple(
                job.id for job in self.jobs.all_jobs
                if job.project_id not in self._projects_by_id
            )
        else:
            project = self._projects_by_id.get(project_id)
            refs = tuple(
                job.id for job in self.jobs.all_jobs
                if project is not None and job.project_id == project.id
            )
        self.jobs.set_visible_refs(refs)
        self._persistent_jobs_controller.preload_results(
            job.id for job in self.jobs.visible_jobs
        )
        self.project_notice.hide()

    def _selected_project(self) -> Project | None:
        project_id = self._selected_project_id
        if project_id in (None, _UNASSIGNED):
            return None
        return self._projects_by_id.get(project_id)

    def _move_selected_runs(self, job_ids: tuple[str, ...]) -> None:
        selected = {job.id: job for job in self.jobs.visible_jobs if job.id in job_ids}
        if not selected:
            return
        dialog = AssignResultsDialog(
            self._repository, len(selected), self,
            item_description="calculation record(s)", allow_unassigned=True,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        destination = dialog.project.currentData()
        expected = {job_id: job.project_id for job_id, job in selected.items()}
        try:
            self._persistent_jobs_controller.reassign_runs(
                self._repository, tuple(selected), destination,
                expected_project_ids=expected,
            )
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Cannot Move Calculation Records", str(exc))
            self._persistent_jobs_controller.refresh_views()
            return
        self._selected_project_id = _UNASSIGNED if destination is None else destination
        self.reload_projects()

    def _request_add_result(self) -> None:
        project = self._selected_project()
        if project is not None:
            self.addResultRequested.emit(project.id)

    def _request_selected_active(self) -> None:
        project = self._selected_project()
        if project is not None:
            self.activeProjectRequested.emit(project.id)

    def _refresh_action_availability(self) -> None:
        ready = self._initial_load_complete
        project = self._selected_project() if ready else None
        self.new_project_button.setEnabled(ready)
        self.refresh_projects_button.setEnabled(ready)
        self.edit_project_button.setEnabled(project is not None)
        self.move_project_button.setEnabled(project is not None)
        self.jobs.set_add_result_available(project is not None)
        self.delete_project_button.setEnabled(project is not None and project.parent_id is not None)
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

    def _edit_project(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        dialog = ProjectEditDialog(
            self, name=project.name, directory=project.directory,
            title="Edit Project",
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._save_project_change(
            project,
            lambda current: current.modify(
                name=dialog.project_name(),
                directory=dialog.project_directory(),
            ),
            "Edit Project",
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
            lambda current: current.modify(parent_id=parent_id),
            "Move Project",
        )

    def _delete_project(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Project?",
            f"Delete project {project.name!r} and its completed run history? "
            "Root projects and projects with active runs cannot be deleted.",
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
        except (ProjectRepositoryError, ProjectDeleteError, KeyError) as exc:
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
                "This project was modified by another Ase2sprkkr instance. "
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
