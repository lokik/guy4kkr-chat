from __future__ import annotations

from ase2sprkkr.sprkkr.projects import default_project_repository

import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget
from kkrunner.projects import ProjectRepository
from guy4ase.gui.application.persistent_jobs import project_run_manager

from guy4ase.gui.application.console_interrupt import ConsoleInterrupt
from guy4ase.gui.application.imported_project_results import assign
from guy4ase.gui.application.persistent_jobs import PersistentJobSource
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import (
    PotentialVersionChanged,
    load_result as interpret_result,
)
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    WorkspaceConflict,
    WorkspaceController,
)
from guy4ase.gui.controllers.persistent_jobs import PersistentJobsController
from guy4ase.gui.dialogs.main_window import MainWindow
from guy4ase.gui.dialogs.project_browser import ProjectBrowserDialog
from guy4ase.gui.dialogs.run_calculation import SprkkrRunWindow
from guy4ase.gui.dialogs.workflow_window import WorkflowWindow
from guy4ase.gui.misc.icons import application_icon
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.presenters.result_actions import ResultActionsPresenter


class GuiApplication(QObject):
    """Compose and own one shared GUI session and its top-level windows."""

    def __init__(
        self,
        *,
        workspace: WorkspaceState | None = None,
        recent_files_path: str | Path | None = None,
        settings_path: str | Path | None = None,
        persistent_jobs: PersistentJobSource | None = None,
        project_repository: ProjectRepository | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = WorkspaceController(
            workspace,
            parent=self,
            conflict_resolver=self._confirm_workspace_conflicts,
        )
        self.controller.activeProjectChanged.connect(self._active_project_changed)
        self.recent_files = RecentFiles(
            Path(recent_files_path) if recent_files_path is not None else None,
            parent=self,
        )
        self.recent_files.load()
        self.settings = ApplicationSettings(
            Path(settings_path) if settings_path is not None else None
        )
        self.settings.load()
        self.projects = (
            project_repository
            if project_repository is not None
            else default_project_repository()
        )
        self.execution_manager = project_run_manager(self.projects)
        self.persistent_jobs = (
            persistent_jobs
            if persistent_jobs is not None
            else PersistentJobSource(self.execution_manager, projects=self.projects)
        )
        self.persistent_jobs_controller = PersistentJobsController(
            self.persistent_jobs,
            result_adopter=self._adopt_persistent_result,
            parent=self,
        )
        self._workflow_window: WorkflowWindow | None = None
        self._main_window: MainWindow | None = None
        self._project_browser: ProjectBrowserDialog | None = None
        self.persistent_jobs_controller.resultOpened.connect(self._show_loaded_result)
        self._exit_in_progress = False
        self._exit_approved = False
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(application_icon())
            app.aboutToQuit.connect(self._close_project_browser)

    @property
    def active_project_id(self) -> str | None:
        return self.controller.active_project_id

    @staticmethod
    def _confirm_workspace_conflicts(
        conflicts: tuple[WorkspaceConflict, ...],
    ) -> bool:
        labels = ", ".join(conflict.component for conflict in conflicts)
        noun = "value has" if len(conflicts) == 1 else "values have"
        answer = QMessageBox.question(
            QApplication.activeWindow(),
            "Workspace Changed",
            (
                f"The following workspace {noun} changed while this operation "
                f"was in progress: {labels}.\n\n"
                "Apply your change anyway?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def create_workflow_window(self) -> WorkflowWindow:
        """Return the session's workflow view, creating it lazily."""
        if self._workflow_window is None:
            self._workflow_window = WorkflowWindow(
                self.controller,
                self.recent_files,
                open_expert=self.show_main_window,
                settings=self.settings,
                track_launch_monitor=self._track_launch_monitor,
                project_repository=self.projects,
            )
            self._wire_window(self._workflow_window)
        return self._workflow_window

    def create_main_window(self) -> MainWindow:
        """Return the session's expert view, creating it lazily."""
        if self._main_window is None:
            self._main_window = MainWindow(
                self.controller,
                self.recent_files,
                self.settings,
                track_launch_monitor=self._track_launch_monitor,
                project_repository=self.projects,
            )
            self._wire_window(self._main_window)
        return self._main_window

    def _wire_window(self, window: WorkflowWindow | MainWindow) -> None:
        """Connect application-owned actions exposed by a top-level window."""
        self._wire_result_actions(window)
        window.installEventFilter(self)
        if isinstance(window, WorkflowWindow):
            window.projectBrowserRequested.connect(self.show_project_browser)
        else:
            window.browser_panel.projectBrowserRequested.connect(
                self.show_project_browser
            )
            window.exitRequested.connect(self.request_exit)

    def _wire_result_actions(self, window: WorkflowWindow | MainWindow) -> None:
        """Compose result presentation and route its top-level mutation intents."""
        widget = window.result_actions_widget
        if widget is None:
            return

        presenter = ResultActionsPresenter(
            self.controller,
            widget,
            parent=window,
        )
        presenter.useStateRequested.connect(
            lambda result_id, expected_potential, owner=presenter: self._use_result_state(
                owner,
                result_id,
                expected_potential,
            )
        )
        presenter.recomputeRequested.connect(
            lambda result_id, target=window: calculation_flow.recompute_result(
                self.controller,
                self.recent_files,
                target,
                result_id,
                track_launch_monitor=self._track_launch_monitor,
                project_repository=self.projects,
            )
        )
        presenter.newCalculationRequested.connect(
            lambda source, target=window: calculation_flow.use_for_new_calculation(
                self.controller,
                target,
                result_id=source.result_id,
            )
        )
        widget.assignToProjectRequested.connect(
            lambda result_ids, target=window: self._assign_results_to_project(
                result_ids, target
            )
        )
        presenter.newCalculationUnavailable.connect(
            lambda target=window: calculation_flow.show_new_calculation_source_required(
                target
            )
        )

    def _assign_results_to_project(self, result_ids, parent: QWidget) -> None:
        from guy4ase.gui.dialogs.assign_results import assign_results_to_project
        if assign_results_to_project(
            self.projects, self.controller.result_store, result_ids, parent,
            run_source=self.persistent_jobs,
        ):
            self.persistent_jobs.reload()

    def _add_result_to_project(self, project_id: str) -> None:
        """Import an external output into one project without inventing a run."""
        browser = self._project_browser
        if browser is None:
            return
        filename, _ = QFileDialog.getOpenFileName(
            browser, "Add SPR-KKR result to project", "",
            "SPR-KKR Output Files (*.out *.log *.txt);;All Files (*)",
        )
        if not filename:
            return
        if not file_flows.load_output(
            self.controller, self.recent_files, filename, browser
        ):
            return
        record = self.controller.result_store.results[0]
        try:
            if assign(self.projects, (record,), project_id) != 1:
                raise ValueError("The imported output has no usable file reference.")
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(browser, "Cannot Add Result", str(exc))
            return
        self.persistent_jobs.reload()

    def _adopt_persistent_result(
        self,
        job_id: str,
        result: Any,
        select_result: bool,
    ) -> None:
        """Bridge persistent execution results into normal workspace history."""
        job = self.persistent_jobs.job(job_id)
        loaded = interpret_result(
            result,
            fallback_directory=None if job is None else job.directory,
            persistent_ref=job_id,
        )
        self.controller.adopt_external_result(
            loaded,
            select_result=select_result,
        )

    def _use_result_state(
        self,
        presenter: ResultActionsPresenter,
        result_id: int,
        expected_potential: PotentialFileVersion | None,
    ) -> None:
        """Route a presenter-validated restore intent to the workspace mutation."""
        try:
            self.controller.use_result_state(result_id, expected_potential)
        except PotentialVersionChanged:
            presenter.refresh()

    def set_active_project(self, project_id: str | None) -> None:
        """Select the project that receives subsequently created persistent runs."""
        self.controller.set_active_project(
            project_id,
            expected_active_project_generation=self.controller.active_project_generation,
        )

    def _active_project_changed(self, project_id: str | None) -> None:
        if self._project_browser is not None:
            self._project_browser.set_active_project(project_id)

    def _track_launch_monitor(self, monitor_window: SprkkrRunWindow) -> None:
        """Capture execution/project context before the monitor starts its worker."""
        monitor_window.set_execution_context(
            self.execution_manager,
            project_id=getattr(
                monitor_window, "launch_project_id", self.controller.active_project_id
            ),
        )
        self.persistent_jobs_controller.track_launch_window(monitor_window)

    def show_workflow_window(self) -> None:
        """Show and activate the workflow view."""
        self._show_window(self.create_workflow_window())

    def show_main_window(self) -> None:
        """Show and activate the expert view, creating it lazily."""
        self._show_window(self.create_main_window())

    def _show_loaded_result(self, _job_id: str) -> None:
        """Bring the selected result into the primary workspace view."""
        if self._main_window is not None and self._main_window.isVisible():
            self._show_window(self._main_window)
        else:
            self.show_workflow_window()

    def show_project_browser(self) -> None:
        """Show and activate the application-owned project browser."""
        if self._project_browser is None:
            dialog = ProjectBrowserDialog(
                self.projects,
                self.persistent_jobs_controller,
                active_project_id=self.controller.active_project_id,
            )
            dialog.activeProjectRequested.connect(self.set_active_project)
            dialog.addResultRequested.connect(self._add_result_to_project)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.destroyed.connect(self._project_browser_closed)
            self._project_browser = dialog
        self._show_window(self._project_browser)

    def _project_browser_closed(self, *_args) -> None:
        self._project_browser = None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Treat closing the primary window as an application exit request."""
        if (
            event.type() == QEvent.Type.Close
            and not self._exit_approved
            and isinstance(watched, QWidget)
            and watched.isVisible()
            and (
                watched is self._workflow_window
                or (
                    watched is self._main_window
                    and (
                        self._workflow_window is None
                        or not self._workflow_window.isVisible()
                    )
                )
            )
        ):
            # request_exit closes every window only after the user approves
            # saving or discarding changes. Consume the original close event.
            self.request_exit()
            return True
        return super().eventFilter(watched, event)

    def _close_project_browser(self) -> None:
        """Close the independent browser on every application shutdown path."""
        if self._project_browser is not None:
            self._project_browser.close()

    def request_exit(self) -> bool:
        """Quit only after the unsaved-work check, closing auxiliary windows."""
        if self._exit_in_progress:
            return False
        self._exit_in_progress = True
        try:
            if not self._confirm_unsaved_work():
                return False
            self._exit_approved = True
            self._close_project_browser()
            for window in (self._main_window, self._workflow_window):
                if window is not None:
                    window.close()
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return True
        finally:
            self._exit_in_progress = False

    def _confirm_unsaved_work(self) -> bool:
        structure = self.controller.has_unsaved_structure
        parameters = self.controller.has_unsaved_input_parameters
        if not structure and not parameters:
            return True

        names = []
        if structure:
            names.append("structure")
        if parameters:
            names.append("input parameters")
        answer = QMessageBox.question(
            QApplication.activeWindow(),
            "Unsaved Work",
            f"Save unsaved {' and '.join(names)} before quitting?",
            (
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            ),
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Discard:
            return True
        if answer != QMessageBox.StandardButton.Save:
            return False

        parent = QApplication.activeWindow() or self._workflow_window or self._main_window
        if structure and not file_flows.save_structure(
            self.controller, self.recent_files, parent
        ):
            return False
        if parameters and not file_flows.save_input_parameters(
            self.controller, self.recent_files, parent
        ):
            return False
        # Modal file dialogs can process further workspace edits; never
        # silently discard a revision newer than the saved one.
        return not (
            self.controller.has_unsaved_structure
            or self.controller.has_unsaved_input_parameters
        )

    @staticmethod
    def _show_window(window: QWidget) -> None:
        window.show()
        window.raise_()
        window.activateWindow()


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    gui = GuiApplication(parent=app)
    gui.show_workflow_window()
    interrupt = ConsoleInterrupt(gui.request_exit, parent=app)
    try:
        return app.exec()
    finally:
        interrupt.close()


if __name__ == "__main__":
    raise SystemExit(main())
