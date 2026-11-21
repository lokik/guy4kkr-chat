from __future__ import annotations

from ase2sprkkr.sprkkr.projects import default_project_repository

import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QApplication, QCheckBox, QFileDialog, QMessageBox, QWidget
from kkrunner.projects import ProjectRepository
from ase2sprkkr_gui.gui.application.persistent_jobs import project_run_manager

from ase2sprkkr_gui.gui.application.console_interrupt import ConsoleInterrupt
from ase2sprkkr_gui.gui.application.imported_project_results import assign
from ase2sprkkr_gui.gui.application.persistent_jobs import PersistentJobSource
from ase2sprkkr_gui.gui.application.potential_version import PotentialFileVersion
from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.result_loading import (
    PotentialVersionChanged,
    load_result as interpret_result,
)
from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import (
    WorkspaceConflict,
    WorkspaceController,
)
from ase2sprkkr_gui.gui.controllers.persistent_jobs import PersistentJobsController
from ase2sprkkr_gui.gui.dialogs.project_browser import ProjectBrowserDialog
from ase2sprkkr_gui.gui.dialogs.run_calculation import SprkkrRunWindow
from ase2sprkkr_gui.gui.dialogs.workflow_window import WorkflowWindow
from ase2sprkkr_gui.gui.misc.icons import application_icon
from ase2sprkkr_gui.gui.flows import calculation as calculation_flow
from ase2sprkkr_gui.gui.flows import custom_calculation as custom_flow
from ase2sprkkr_gui.gui.flows import files as file_flows
from ase2sprkkr_gui.gui.presenters.result_actions import ResultActionsPresenter


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
        self._project_browser: ProjectBrowserDialog | None = None
        self.persistent_jobs_controller.resultOpened.connect(self._show_loaded_result)
        self._exit_in_progress = False
        self._exit_approved = False
        app = QApplication.instance()
        if app is not None:
            app.setApplicationName("Ase2sprkkr")
            app.setApplicationDisplayName("Ase2sprkkr")
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
                settings=self.settings,
                track_launch_monitor=self._track_launch_monitor,
                project_repository=self.projects,
            )
            self._wire_window(self._workflow_window)
        return self._workflow_window

    def _wire_window(self, window: WorkflowWindow) -> None:
        """Connect application-owned actions exposed by a top-level window."""
        self._wire_result_actions(window)
        window.installEventFilter(self)
        window.projectBrowserRequested.connect(self.show_project_browser)

    def _wire_result_actions(self, window: WorkflowWindow) -> None:
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
        widget.loadResultRequested.connect(
            lambda target=window: file_flows.choose_and_load_output(
                self.controller, self.recent_files, target
            )
        )
        widget.importDirectoryRequested.connect(
            lambda target=window: file_flows.choose_and_load_output_directory(
                self.controller, self.recent_files, target
            )
        )
        presenter.newCalculationUnavailable.connect(
            lambda target=window: calculation_flow.show_new_calculation_source_required(
                target
            )
        )

    def _assign_results_to_project(self, result_ids, parent: QWidget) -> None:
        from ase2sprkkr_gui.gui.dialogs.assign_results import assign_results_to_project
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

    def open_startup_selection(
        self, kind: str | None, file_path: str | None
    ) -> bool:
        """Open a CLI-selected document using the regular GUI file workflows."""
        if kind is None:
            return True
        parent = self.create_workflow_window()
        if kind == "job":
            if not file_path:
                return False
            return self.persistent_jobs_controller.open_job(file_path, parent)

        if kind == "last":
            # Last structure is independent of the most recently used output.
            # Prune deleted entries so a stale first entry does not hide a valid one.
            self.recent_files.remove_missing(("structure",))
            structures = self.recent_files.paths("structure")
            if not structures:
                QMessageBox.warning(
                    parent, "No Recent Structure",
                    "There is no recently opened structure available.",
                )
                return False
            kind, file_path = "structure", structures[0]

        if file_path is None:
            return False
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            QMessageBox.warning(
                parent, "Cannot Open File", f"File not found:\n{path}",
            )
            return False

        if kind == "auto":
            if path.is_dir() or path.suffix.lower() in {".out", ".log"}:
                kind = "output"
            elif path.suffix.lower() in {".inp", ".in"}:
                kind = "input"
            else:
                kind = "structure"

        if kind == "output" and path.is_dir():
            return bool(file_flows.load_output_directory(
                self.controller, self.recent_files, path, parent
            ))
        if not path.is_file():
            QMessageBox.warning(
                parent, "Cannot Open File", f"Expected a file:\n{path}",
            )
            return False

        if kind == "input":
            return custom_flow.load_custom_input(
                self.controller, self.recent_files, parent, path,
                track_launch_monitor=self._track_launch_monitor,
                project_repository=self.projects,
            )
        loaders = {
            "structure": file_flows.load_structure,
            "output": file_flows.load_output,
        }
        return loaders[kind](self.controller, self.recent_files, path, parent)

    def show_workflow_window(self) -> None:
        """Show and activate the workflow view."""
        window = self.create_workflow_window()
        self._show_window(window)
        self._offer_new_supported_tasks(window)

    def _offer_new_supported_tasks(self, window: WorkflowWindow) -> None:
        """Prompt once per newly supported task generation, only for saved overrides."""
        new = self.settings.newly_supported_tasks()
        if not new:
            return

        names = ", ".join(new)
        singular = len(new) == 1
        message = QMessageBox(window)
        message.setWindowTitle(
            "New Supported Task" if singular else "New Supported Tasks"
        )
        message.setIcon(QMessageBox.Icon.Information)
        message.setText(
            f"A new task {names} is supported. Add it to your preferred tasks?"
            if singular else
            f"New tasks {names} are supported. Add them to your preferred tasks?"
        )
        message.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message.setDefaultButton(QMessageBox.StandardButton.Yes)
        open_preferred = QCheckBox("Open Preferred tasks", message)
        open_preferred.setChecked(False)
        message.setCheckBox(open_preferred)
        answer = message.exec()
        if answer not in (
            QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No,
        ):
            return

        previous = (
            self.settings.preferred_tasks,
            self.settings.preferred_supported_snapshot,
        )
        self.settings.acknowledge_supported_tasks(
            add=answer == QMessageBox.StandardButton.Yes,
        )
        if not self.settings.save():
            (self.settings.preferred_tasks,
             self.settings.preferred_supported_snapshot) = previous
            QMessageBox.warning(
                window, "Cannot Save Settings",
                "Could not save your preferred-task choice. You will be "
                "asked again the next time settings are loaded.",
            )
            return
        window._refresh()
        if open_preferred.isChecked():
            window._open_settings(preferred_tasks=True)

    def _show_loaded_result(self, _job_id: str) -> None:
        """Bring the selected result into the primary workspace view."""
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
            and watched is self._workflow_window
        ):
            # Reject the original close only when shutdown is cancelled.
            # On approval, let Qt finish this close event: QWidget.close()
            # does not reliably re-enter a close operation already in progress.
            if not self.request_exit():
                event.ignore()
                return True
            return False
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
            if self._workflow_window is not None:
                self._workflow_window.close()
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

        parent = QApplication.activeWindow() or self._workflow_window
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


def _warn_unreadable_user_yaml() -> None:
    """Report a corrupted user configuration after Qt has started.

    The library already warned and skipped the malformed YAML on import.
    Rechecking the document here avoids a launcher-specific import path and
    ensures that users starting the GUI without a terminal see the problem.
    """
    from ruamel.yaml.error import YAMLError
    from ase2sprkkr.configuration import user_preferences_file
    from ase2sprkkr.configuration_yaml import load_yaml_document

    path = Path(user_preferences_file())
    if not path.is_file():
        return
    try:
        load_yaml_document(path)
    except (YAMLError, ValueError) as exc:
        QMessageBox.warning(
            None,
            "Invalid ASE2SPRKKR Configuration",
            f"Cannot parse the user configuration file:\n{path}\n\n{exc}\n\n"
            "The file was not changed. ASE2SPRKKR will use its defaults "
            "(and any loaded legacy Python settings) until the YAML is fixed. "
            "Please correct the file before saving execution profiles or "
            "ASE2SPRKKR settings.",
        )


def main(argv: list[str] | None = None) -> int:
    import argparse
    from ase2sprkkr_gui.cli.gui import parser as configure_gui_parser, startup_selection

    cli = argparse.ArgumentParser(description="Ase2sprkkr graphical interface")
    configure_gui_parser(cli)
    args = cli.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        kind, file_path = startup_selection(args)
    except ValueError as exc:
        cli.error(str(exc))

    # Only pass Qt's program name; startup files are handled by the GUI itself.
    app = QApplication([sys.argv[0]])
    _warn_unreadable_user_yaml()
    gui = GuiApplication(parent=app)
    gui.show_workflow_window()
    gui.open_startup_selection(kind, file_path)
    def shutdown_from_console() -> None:
        if (gui.controller.has_unsaved_structure
                or gui.controller.has_unsaved_input_parameters):
            ConsoleInterrupt._console_notice(
                b"GUI: awaiting response to save/discard prompt.\n"
            )
        else:
            ConsoleInterrupt._console_notice(b"GUI: closing.\n")
        if not gui.request_exit():
            ConsoleInterrupt._console_notice(
                b"GUI remains open (shutdown cancelled or save failed).\n"
            )

    interrupt = ConsoleInterrupt(shutdown_from_console, parent=app)
    try:
        return app.exec()
    finally:
        interrupt.close()


if __name__ == "__main__":
    raise SystemExit(main())
