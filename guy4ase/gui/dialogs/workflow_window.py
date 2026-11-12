from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.object_view import execute_value_action
from guy4ase.gui.dialogs.settings import edit_settings
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows import structures as structure_flows
from guy4ase.gui.flows import visualization as visualization_flow
from guy4ase.gui.recent_presentation import RecentLaunchKind
from guy4ase.gui.style import (
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    SPACE_XXL,
    button_stylesheet,
    group_panel_stylesheet,
    heading_font,
    secondary_text_stylesheet,
)
from guy4ase.gui.widgets.browser_panel import BrowserPanel
from guy4ase.gui.widgets.result_actions import ResultActionsWidget
from guy4ase.gui.widgets.workflow_actions import WorkflowActionsWidget
from guy4ase.gui.workflow.model import (
    Build2D,
    Build2DKind,
    ContinueRecent,
    CreateStructure,
    CreateStructureKind,
    Load,
    LoadKind,
    RunTask,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    VisualizeStructure,
    WorkflowCommand,
    WorkflowPlan,
)
from guy4ase.gui.workflow.planner import WorkflowPlanner


class WorkflowWindow(QMainWindow):
    """Task-oriented entry point that keeps the full UI available as expert mode."""

    def __init__(
        self,
        controller: WorkspaceController,
        recent_files: RecentFiles,
        *,
        open_expert: Callable[[], None],
        settings: ApplicationSettings,
        track_launch_monitor: calculation_flow.LaunchMonitorTracker,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Guy4ASE - Workflow")
        manage_window_geometry(self, "workflow", default_size=(1120, 700))
        self.controller = controller
        self.recent_history = recent_files
        self.settings = settings
        self._open_expert = open_expert
        self._track_launch_monitor = track_launch_monitor
        self._workflow_planner = WorkflowPlanner()
        self.controller.structureChanged.connect(self._on_structure_changed)
        self.controller.directoryChanged.connect(
            lambda _directory: self._refresh_working_directory()
        )
        self.controller.resultChanged.connect(lambda _result: self._refresh())
        self.recent_history.changed.connect(self._refresh)
        self._build_ui()
        self._refresh_working_directory()
        self._refresh()

    @property
    def result_actions_widget(self) -> ResultActionsWidget:
        """Return the result browser owned by this window."""
        return self._result_actions_widget

    @property
    def browser_panel(self) -> BrowserPanel:
        """Return the session-independent browser entry points."""
        return self._browser_panel

    @property
    def workflow_plan(self) -> WorkflowPlan:
        """Return the semantic action plan currently rendered by the window."""
        plan = self._actions.plan
        if plan is None:
            raise RuntimeError("Workflow plan has not been rendered yet.")
        return plan

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(SPACE_XXL, SPACE_XL, SPACE_XL, SPACE_XL)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        root.addWidget(splitter)

        content = QWidget(splitter)
        content.setMinimumWidth(480)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, SPACE_XL, 0)
        title = QLabel("What would you like to do?")
        title.setObjectName("workflowTitle")
        title.setFont(heading_font(title.font(), "window"))
        content_layout.addWidget(title)
        self._subtitle = QLabel()
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(secondary_text_stylesheet(self.palette()))
        content_layout.addWidget(self._subtitle)
        content_layout.addSpacing(SPACE_XL)

        self._actions = WorkflowActionsWidget(content)
        self._actions.commandRequested.connect(self.execute_workflow_command)
        content_layout.addWidget(self._actions)

        content_layout.addStretch(1)
        splitter.addWidget(content)

        side = QFrame(splitter)
        side.setFrameShape(QFrame.Shape.StyledPanel)
        side.setMinimumWidth(300)
        side.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(SPACE_SM)

        working_directory = QWidget(side)
        working_directory.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        working_directory_layout = QVBoxLayout(working_directory)
        working_directory_layout.setContentsMargins(0, 0, 0, 0)
        working_directory_layout.setSpacing(SPACE_XS)
        working_directory_title = QLabel("Working directory", working_directory)
        working_directory_title.setFont(
            heading_font(working_directory_title.font(), "section")
        )
        working_directory_layout.addWidget(working_directory_title)

        directory_row = QHBoxLayout()
        directory_row.setContentsMargins(0, 0, 0, 0)
        directory_row.setSpacing(SPACE_XS)
        self._working_directory_label = QLabel(working_directory)
        self._working_directory_label.setWordWrap(False)
        self._working_directory_label.setMinimumWidth(0)
        self._working_directory_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._working_directory_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        directory_row.addWidget(self._working_directory_label, 1)

        change_directory = QToolButton(working_directory)
        change_directory.setIcon(
            QIcon.fromTheme(
                "document-open",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            )
        )
        change_directory.setToolTip("Change working directory")
        change_directory.setAccessibleName("Change working directory")
        change_directory.clicked.connect(
            lambda _checked=False: calculation_flow.choose_working_directory(
                self.controller,
                self,
            )
        )
        directory_row.addWidget(change_directory)

        self._browse_working_directory_button = QToolButton(working_directory)
        self._browse_working_directory_button.setIcon(
            QIcon.fromTheme(
                "system-file-manager",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            )
        )
        self._browse_working_directory_button.setToolTip(
            "Open working directory in file manager"
        )
        self._browse_working_directory_button.setAccessibleName(
            "Open working directory in file manager"
        )
        self._browse_working_directory_button.clicked.connect(
            self._browse_working_directory
        )
        directory_row.addWidget(self._browse_working_directory_button)
        working_directory_layout.addLayout(directory_row)
        side_layout.addWidget(working_directory)
        self._browser_panel = BrowserPanel(side)
        self._browser_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        side_layout.addWidget(self._browser_panel)

        self._result_actions = QWidget(side)
        result_actions_layout = QVBoxLayout(self._result_actions)
        result_actions_layout.setContentsMargins(0, 0, 0, 0)
        result_actions_layout.setSpacing(SPACE_XS)
        result_actions_title = QLabel("Results...", self._result_actions)
        result_actions_title.setFont(
            heading_font(result_actions_title.font(), "section")
        )
        result_actions_layout.addWidget(result_actions_title)
        self._result_actions_widget = ResultActionsWidget(
            lambda value, action: execute_value_action(value, action, self),
            show_values_without_actions=False,
            show_history_button=False,
            parent=self._result_actions,
        )
        result_actions_layout.addWidget(self._result_actions_widget, 1)
        side_layout.addWidget(self._result_actions, 1)

        expert_box = QGroupBox("", side)
        expert_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        expert_layout = QVBoxLayout(expert_box)
        side_text = QLabel("Access the full expert interface.", expert_box)
        side_text.setWordWrap(True)
        side_text.setStyleSheet(secondary_text_stylesheet(self.palette()))
        expert_layout.addWidget(side_text)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(SPACE_XS)
        expert_btn = QPushButton("Open Expert Mode", expert_box)
        expert_btn.setMinimumHeight(40)
        expert_btn.setStyleSheet(button_stylesheet(self.palette()))
        expert_btn.clicked.connect(self._open_expert_mode)
        bottom_row.addWidget(expert_btn, 1)

        settings_btn = QToolButton(expert_box)
        settings_btn.setAutoRaise(True)
        settings_btn.setFixedSize(40, 40)
        settings_btn.setIcon(
            QIcon.fromTheme(
                "preferences-system",
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_FileDialogDetailedView
                ),
            )
        )
        settings_btn.setToolTip("Settings")
        settings_btn.setAccessibleName("Settings")
        settings_btn.clicked.connect(self._open_settings)
        bottom_row.addWidget(settings_btn)
        expert_layout.addLayout(bottom_row)
        expert_box.setStyleSheet(
            group_panel_stylesheet(
                self.palette(), self.palette().color(QPalette.ColorRole.Highlight)
            )
        )
        side_layout.addWidget(expert_box, alignment=Qt.AlignmentFlag.AlignBottom)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 360])

    def _refresh_working_directory(self) -> None:
        directory = self.controller.directory
        self._working_directory_label.setText(directory or "(not defined)")
        self._working_directory_label.setToolTip(directory or "")
        self._browse_working_directory_button.setEnabled(bool(directory))

    def _browse_working_directory(self) -> None:
        directory = self.controller.directory
        if not directory:
            return
        path = Path(directory).expanduser().resolve()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(
                self,
                "Cannot Open Directory",
                f"Could not open the working directory in the system file manager:\n{path}",
            )

    def _refresh(self) -> None:
        plan = self._workflow_planner.for_workspace(
            self.controller,
            recent=self.recent_history.read_snapshot(),
        )
        self._subtitle.setText(plan.subtitle)
        self._actions.set_plan(plan)

    def execute_workflow_command(self, command: WorkflowCommand) -> None:
        """Mechanically route one already-approved workflow command."""
        if isinstance(command, RunTask):
            self._prepare_task(command.backend_task)
            return
        if isinstance(command, UpdateEmptySpheres):
            self._update_empty_spheres()
            return
        if isinstance(command, CreateStructure):
            {
                CreateStructureKind.THREE_D: self._create_3d,
                CreateStructureKind.PROTOTYPE: self._create_from_database,
                CreateStructureKind.SURFACE: self._create_surface,
                CreateStructureKind.TWO_D: self._create_transition,
            }[command.kind]()
            return
        if isinstance(command, Build2D):
            surface_mode = {
                Build2DKind.SURFACE: True,
                Build2DKind.STRUCTURE: False,
            }[command.kind]
            self._build_2d(surface_mode=surface_mode)
            return
        if isinstance(command, Load):
            {
                LoadKind.ONLINE_STRUCTURE: self._download_structure,
                LoadKind.STRUCTURE: self._load_structure,
                LoadKind.OUTPUT: self._load_output,
            }[command.kind]()
            return
        if isinstance(command, ContinueRecent):
            self._continue_recent(command.kind, command.path)
            return
        if isinstance(command, VisualizeStructure):
            self._visualize_structure()
            return
        if isinstance(command, UseForNewCalculation):
            self._use_for_new_calculation()
            return
        if isinstance(command, StartOver):
            self._start_over()
            return
        raise TypeError(f"Unsupported workflow command {type(command).__name__}.")

    def _on_structure_changed(self, _atoms: Any) -> None:
        self._refresh()

    def _create_3d(self) -> None:
        structure_flows.create_structure(self.controller, self)

    def _create_from_database(self) -> None:
        structure_flows.create_structure_from_database(self.controller, self)

    def _download_structure(self) -> None:
        structure_flows.download_structure(self.controller, self)

    def _create_surface(self) -> None:
        structure_flows.create_2d_from_new_structure(
            self.controller, self.recent_history, self, surface_mode=True
        )

    def _create_transition(self) -> None:
        structure_flows.create_2d_from_new_structure(
            self.controller, self.recent_history, self, surface_mode=False
        )

    def _load_structure(self) -> None:
        file_flows.choose_and_load_structure(
            self.controller, self.recent_history, self
        )

    def _load_output(self) -> None:
        file_flows.choose_and_load_output(
            self.controller, self.recent_history, self
        )

    def _continue_recent(self, kind: RecentLaunchKind, file_path: str) -> None:
        file_flows.continue_recent(
            self.controller,
            self.recent_history,
            kind,
            file_path,
            self,
        )
        if self.controller.atoms is None:
            self._refresh()

    def _build_2d(self, _checked: bool = False, *, surface_mode: bool = False) -> None:
        structure_flows.build_2d_structure(
            self.controller,
            self.recent_history,
            self,
            surface_mode=surface_mode,
        )

    def _prepare_task(self, task: str) -> None:
        calculation_flow.configure_and_run_task(
            self.controller,
            self.recent_history,
            self,
            task,
            dataset_default_mode=self.settings.dataset_default_mode,
            track_launch_monitor=self._track_launch_monitor,
        )

    def _update_empty_spheres(self) -> None:
        structure_flows.update_empty_spheres(self.controller, self)

    def _use_for_new_calculation(self) -> None:
        calculation_flow.use_for_new_calculation(self.controller, self)

    def _start_over(self) -> None:
        answer = QMessageBox.question(
            self,
            "Start Over?",
            "Really start over? The current structure and calculation settings "
            "will be cleared. Existing calculation results will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.reset()

    def _visualize_structure(self) -> None:
        visualization_flow.visualize_structure(self.controller, self.settings, self)

    def _open_settings(self) -> None:
        edit_settings(self.settings, self)

    def _open_expert_mode(self) -> None:
        self._open_expert()
