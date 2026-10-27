from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QWidget,
)

from guy4ase.gui.application.recent_files import (
    RecentFiles,
    RecentFilesSnapshot,
    RecentKind,
)
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.object_view import execute_value_action
from guy4ase.gui.dialogs.settings import edit_settings
from guy4ase.gui.dialogs.structures.transforms import (
    repeat_atoms,
    rotate_atoms,
    scale_atoms,
)
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows import input_editing as input_editing_flow
from guy4ase.gui.flows import structures as structure_flows
from guy4ase.gui.flows import visualization as visualization_flow
from guy4ase.gui.presentation import empty_spheres_action_title
from guy4ase.gui.recent_presentation import (
    RecentLaunch,
    recent_launch_presentation,
)
from guy4ase.gui.widgets.browser_panel import BrowserPanel
from guy4ase.gui.widgets.expert_side_panel import ExpertSidePanel
from guy4ase.gui.widgets.recent_launcher import (
    build_recent_launch_menu,
    populate_recent_menu,
)
from guy4ase.gui.widgets.result_actions import ResultActionsWidget
from guy4ase.gui.widgets.structure_overview import StructureOverviewWidget
from guy4ase.gui.workspace_semantics import EmptySpheresAction


class MainWindow(QMainWindow):
    """Expert-mode shell composing menus and focused presentation widgets."""

    def __init__(
        self,
        controller: WorkspaceController,
        recent_files: RecentFiles,
        settings: ApplicationSettings,
        *,
        track_launch_monitor: calculation_flow.LaunchMonitorTracker,
        project_repository=None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Guy4ASE - Structure Manager")
        manage_window_geometry(
            self,
            "structure-manager",
            default_size=(1400, 800),
            default_maximized=True,
        )

        self.controller = controller
        self.recent_history = recent_files
        self.settings = settings
        self._track_launch_monitor = track_launch_monitor
        self.project_repository = project_repository
        self._recent_menus: Dict[str, Optional[QMenu]] = {
            "structure": None,
            "input": None,
            "output": None,
        }
        self._recent_start_menu: QMenu | None = None
        self._recent_start_launch: RecentLaunch | None = None

        self._build_ui()
        self._connect_workspace()
        self.recent_history.changed.connect(self._refresh_recent_menus)
        self._refresh_recent_menus()
        self._workspace_structure_changed(self.controller.atoms)
        self._workspace_input_parameters_changed(self.controller.input_parameters)
        self._workspace_directory_changed()

    @property
    def result_actions_widget(self) -> ResultActionsWidget:
        """Return the result view exposed to the application composition root."""
        return self._expert_side_panel.result_actions_widget

    @property
    def browser_panel(self) -> BrowserPanel:
        """Return the session-independent browser exposed to the composition root."""
        return self._expert_side_panel.browser_panel

    def _connect_workspace(self) -> None:
        self.controller.structureChanged.connect(self._workspace_structure_changed)
        self.controller.inputParametersChanged.connect(
            self._workspace_input_parameters_changed
        )
        self.controller.directoryChanged.connect(
            lambda _directory: self._workspace_directory_changed()
        )

    def _workspace_structure_changed(self, atoms: Any) -> None:
        self._calculation_setup.set_potential_path(self.controller.potential_path)
        self._structure_overview.set_structure(
            atoms,
            scf_status=self.controller.scf_status(),
            scf_converged=self.controller.is_scf_converged(),
        )
        self._refresh_action_availability()

    def _workspace_input_parameters_changed(self, parameters: Any) -> None:
        self._present_input_parameters(parameters)
        self._refresh_action_availability()

    def _present_input_parameters(self, parameters: Any) -> None:
        preview = None if parameters is None else parameters.to_string(validate=False)
        self._calculation_setup.set_input_preview(
            preview,
            input_available=parameters is not None,
        )

    def _workspace_directory_changed(self) -> None:
        self._calculation_setup.set_directory(self.controller.directory)
        self._refresh_action_availability()

    def _refresh_action_availability(self) -> None:
        has_structure = self.controller.atoms is not None
        for action in (
            self.save_structure_action,
            self.edit_structure_action,
            self.scale_structure_action,
            self.repeat_structure_action,
            self.rotate_structure_action,
            self.visualize_structure_action,
        ):
            action.setEnabled(has_structure)
        self.build_2d_structure_action.setEnabled(self.controller.can_build_2d())

        has_input = self.controller.input_parameters is not None
        self.save_input_action.setEnabled(has_input)
        self._calculation_setup.set_save_input_enabled(has_input)
        self.run_calculation_action.setEnabled(self.controller.can_calculate())

        empty_spheres = self.controller.empty_spheres_action()
        self.empty_spheres_action.setVisible(empty_spheres is not None)
        if empty_spheres is not None:
            self.empty_spheres_action.setText(empty_spheres_action_title(empty_spheres))

    def _refresh_recent_menu(
        self,
        what: RecentKind,
        snapshot: RecentFilesSnapshot,
    ) -> None:
        menu = self._recent_menus[what]
        if menu is None:
            return
        populate_recent_menu(
            menu,
            snapshot,
            what,
            lambda path, item_kind=what: self.open_recent_file(item_kind, path),
        )

    def _refresh_recent_menus(self) -> None:
        snapshot = self.recent_history.read_snapshot()
        for what in ("structure", "input", "output"):
            self._refresh_recent_menu(what, snapshot)
        self._refresh_recent_start(snapshot)

    def open_recent_file(self, kind: RecentKind, file_path: str) -> None:
        file_flows.open_recent(
            self.controller,
            self.recent_history,
            kind,
            file_path,
            self,
        )

    def continue_recent_file(self, kind: RecentKind, file_path: str) -> None:
        file_flows.continue_recent(
            self.controller,
            self.recent_history,
            kind,
            file_path,
            self,
        )

    def _refresh_recent_start(self, snapshot: RecentFilesSnapshot) -> None:
        presentation = recent_launch_presentation(snapshot)
        self._recent_start_launch = presentation.primary
        launch = self._recent_start_launch
        if launch is None:
            self._structure_overview.set_recent_start(title=None)
            return

        self._recent_start_menu = build_recent_launch_menu(
            self._structure_overview,
            presentation,
            self.continue_recent_file,
            menu=self._recent_start_menu,
        )
        self._structure_overview.set_recent_start(
            title=launch.title,
            tooltip=launch.path,
            menu=self._recent_start_menu,
        )

    def _continue_recent_start(self) -> None:
        launch = self._recent_start_launch
        if launch is not None:
            self.continue_recent_file(launch.kind, launch.path)

    def _build_ui(self) -> None:
        self._build_menu_bar()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        self._structure_overview = StructureOverviewWidget(
            save_action=self.save_structure_action,
            edit_action=self.edit_structure_action,
            create_structure=self.create_structure,
            create_from_database=self.create_structure_from_database,
            download_structure=self.download_structure,
            load_structure=self.load_structure,
            load_output=self.load_sprkkr_output,
            parent=splitter,
        )
        self._structure_overview.recentStartRequested.connect(
            self._continue_recent_start
        )

        self._expert_side_panel = ExpertSidePanel(
            edit_input=self._on_edit_sprkkr_input,
            load_input=self._on_load_sprkkr_input,
            save_input=self._on_save_sprkkr_input,
            choose_directory=self._choose_working_directory,
            run_calculation_action=self.run_calculation_action,
            load_output=self.load_sprkkr_output,
            value_action=lambda value, action: execute_value_action(value, action, self),
            parent=splitter,
        )
        self._calculation_setup = self._expert_side_panel.calculation_setup

        splitter.addWidget(self._structure_overview)
        splitter.addWidget(self._expert_side_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1000, 350])

    def _build_menu_bar(self) -> None:
        menubar = self.menuBar()
        structure_menu = menubar.addMenu("&Structure")

        create_action = QAction("&Create New...", self)
        create_action.setShortcut("Ctrl+N")
        create_action.triggered.connect(self.create_structure)
        structure_menu.addAction(create_action)
        create_database_action = QAction("Create from &Prototype Database...", self)
        create_database_action.triggered.connect(self.create_structure_from_database)
        structure_menu.addAction(create_database_action)

        download_action = QAction("&Download from Online Database...", self)
        download_action.triggered.connect(self.download_structure)
        structure_menu.addAction(download_action)

        load_action = QAction("&Load from File...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self.load_structure)
        structure_menu.addAction(load_action)

        self.save_structure_action = QAction("&Save Structure...", self)
        self.save_structure_action.triggered.connect(self._on_save_structure)
        structure_menu.addAction(self.save_structure_action)
        self._recent_menus["structure"] = structure_menu.addMenu("Open &Recent")

        input_menu = menubar.addMenu("&Input")
        load_input_action = QAction("&Load Input File...", self)
        load_input_action.triggered.connect(self._on_load_sprkkr_input)
        input_menu.addAction(load_input_action)
        self.save_input_action = QAction("&Save Input File...", self)
        self.save_input_action.triggered.connect(self._on_save_sprkkr_input)
        input_menu.addAction(self.save_input_action)
        self._recent_menus["input"] = input_menu.addMenu("Open &Recent")

        output_menu = menubar.addMenu("&Output")
        load_output_action = QAction("&Load Output File...", self)
        load_output_action.triggered.connect(self.load_sprkkr_output)
        output_menu.addAction(load_output_action)
        self._recent_menus["output"] = output_menu.addMenu("Open &Recent")

        run_menu = menubar.addMenu("&Run")
        self.empty_spheres_action = QAction(
            empty_spheres_action_title(EmptySpheresAction.ADD), self
        )
        self.empty_spheres_action.triggered.connect(
            lambda: structure_flows.update_empty_spheres(self.controller, self)
        )
        run_menu.addAction(self.empty_spheres_action)
        run_menu.addSeparator()
        self.run_calculation_action = QAction("Run SPRKKR Calculation...", self)
        self.run_calculation_action.triggered.connect(self._on_run_sprkkr_calculation)
        run_menu.addAction(self.run_calculation_action)

        view_menu = menubar.addMenu("&View")
        self.visualize_structure_action = QAction("&Visualize Structure", self)
        self.visualize_structure_action.triggered.connect(self._visualize_structure)
        view_menu.addAction(self.visualize_structure_action)

        tools_menu = menubar.addMenu("&Tools")
        settings_action = QAction("&Settings...", self)
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.triggered.connect(self._open_settings)
        tools_menu.addAction(settings_action)

        self.edit_structure_action = QAction("&Edit the structure...", self)
        self.edit_structure_action.setShortcut("Ctrl+E")
        self.edit_structure_action.triggered.connect(self._on_assign_elements)
        structure_menu.addAction(self.edit_structure_action)
        structure_menu.addSeparator()

        self.scale_structure_action = QAction("&Scale...", self)
        self.scale_structure_action.triggered.connect(self._on_scale_structure)
        structure_menu.addAction(self.scale_structure_action)

        self.repeat_structure_action = QAction("&Repeat...", self)
        self.repeat_structure_action.triggered.connect(self._on_repeat_structure)
        structure_menu.addAction(self.repeat_structure_action)

        self.rotate_structure_action = QAction("R&otate...", self)
        self.rotate_structure_action.triggered.connect(self._on_rotate_structure)
        structure_menu.addAction(self.rotate_structure_action)

        self.build_2d_structure_action = QAction("Build &2D Structure...", self)
        self.build_2d_structure_action.triggered.connect(self.build_2d_structure)
        structure_menu.addAction(self.build_2d_structure_action)
        structure_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        structure_menu.addAction(exit_action)

        help_menu = menubar.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _visualize_structure(self) -> None:
        visualization_flow.visualize_structure(self.controller, self.settings, self)

    def _open_settings(self) -> None:
        edit_settings(self.settings, self)

    def create_structure(self) -> None:
        structure_flows.create_structure(self.controller, self)

    def create_structure_from_database(self) -> None:
        structure_flows.create_structure_from_database(self.controller, self)

    def load_structure(self) -> None:
        file_flows.choose_and_load_structure(
            self.controller, self.recent_history, self
        )

    def download_structure(self) -> None:
        structure_flows.download_structure(self.controller, self)

    def _on_save_structure(self) -> None:
        file_flows.save_structure(self.controller, self.recent_history, self)

    def _on_create_sprkkr_input(self, task: str = "scf") -> None:
        if not isinstance(task, str):
            task = "scf"
        input_editing_flow.create_input_parameters(
            self.controller,
            self,
            task=task,
            dataset_default_mode=self.settings.dataset_default_mode,
        )

    def _on_edit_sprkkr_input(self, _checked: bool = False) -> None:
        input_editing_flow.edit_current_input_parameters(
            self.controller,
            self,
            dataset_default_mode=self.settings.dataset_default_mode,
        )

    def _on_load_sprkkr_input(self) -> None:
        input_editing_flow.load_and_edit_input_parameters(
            self.controller,
            self.recent_history,
            self,
        )

    def load_sprkkr_output(self) -> None:
        file_flows.choose_and_load_output(
            self.controller, self.recent_history, self
        )

    def _on_save_sprkkr_input(self) -> None:
        file_flows.save_input_parameters(self.controller, self.recent_history, self)

    def _choose_working_directory(self) -> None:
        calculation_flow.choose_working_directory(
            self.controller,
            self,
            title="Select Directory",
        )

    def _on_run_sprkkr_calculation(self) -> None:
        calculation_flow.run_calculation(
            self.controller,
            self.recent_history,
            self,
            track_launch_monitor=self._track_launch_monitor,
            project_repository=self.project_repository,
        )

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Guy4ASE",
            "Guy4ASE - Structure Manager\n\n"
            "A tool for creating, loading, and manipulating atomic structures\n"
            "with integration for SPRKKR calculations.\n\n"
            "Built with ASE and PyQt6.",
        )

    def _on_assign_elements(self) -> None:
        structure_flows.edit_site_elements(self.controller, self)

    def _on_scale_structure(self) -> None:
        structure_flows.edit_current_structure(
            self.controller,
            self,
            scale_atoms,
            error_title="Scale Error",
        )

    def _on_repeat_structure(self) -> None:
        structure_flows.edit_current_structure(
            self.controller,
            self,
            repeat_atoms,
            error_title="Repeat Error",
        )

    def _on_rotate_structure(self) -> None:
        structure_flows.edit_current_structure(
            self.controller,
            self,
            rotate_atoms,
            error_title="Rotate Error",
        )

    def build_2d_structure(
        self,
        _checked: bool = False,
        *,
        surface_mode: bool = False,
    ) -> None:
        structure_flows.build_2d_structure(
            self.controller,
            self.recent_history,
            self,
            surface_mode=surface_mode,
        )