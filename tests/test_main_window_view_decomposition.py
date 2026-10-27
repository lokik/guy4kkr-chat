"""Presentation and integration checks for expert-window decomposition."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.settings import ApplicationSettings
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.main_window import MainWindow
from guy4ase.gui.widgets.browser_panel import BrowserPanel
from guy4ase.gui.widgets.calculation_setup import CalculationSetupPanel
from guy4ase.gui.widgets.expert_side_panel import ExpertSidePanel
from guy4ase.gui.widgets.result_actions import ResultActionsWidget
from guy4ase.gui.widgets.structure_overview import StructureOverviewWidget


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_structure_overview_renders_structure_snapshot():
    app = _app()
    save_action = QAction("Save")
    edit_action = QAction("Edit")
    noop = lambda: None
    widget = StructureOverviewWidget(
        save_action=save_action,
        edit_action=edit_action,
        create_structure=noop,
        create_from_database=noop,
        download_structure=noop,
        load_structure=noop,
        load_output=noop,
    )

    widget.set_structure(
        Atoms("Fe", cell=[2.0, 3.0, 4.0], pbc=True),
        scf_status="ITERATING",
    )
    app.processEvents()

    assert widget.lattice_labels["a"].text() == "2.0000 Å"
    assert widget.positions_table.rowCount() == 1
    assert "Formula: Fe" in widget.info_text
    assert widget.scf_status_text == "SCF Status: ITERATING"

    widget.clear_structure()
    assert widget.positions_table.rowCount() == 0
    widget.close()


def test_calculation_setup_panel_renders_supplied_presentation():
    _app()
    run_action = QAction("Run")
    noop = lambda: None
    panel = CalculationSetupPanel(
        edit_input=noop,
        load_input=noop,
        save_input=noop,
        run_calculation_action=run_action,
        load_output=noop,
    )

    panel.set_input_preview("TASK SCF", input_available=True)
    panel.set_save_input_enabled(True)
    panel.set_potential_path("/tmp/run/Fe.pot")

    assert panel.input_button_text == "Edit SPRKKR Input File..."
    assert panel.input_preview_text == "TASK SCF"
    assert panel.save_input_enabled
    assert panel.potential_path_text == "/tmp/run/Fe.pot"
    assert panel.findChild(BrowserPanel) is None
    assert panel.findChild(ResultActionsWidget) is None
    panel.close()


def test_expert_side_panel_composes_independent_views():
    _app()
    noop = lambda: None
    panel = ExpertSidePanel(
        edit_input=noop,
        load_input=noop,
        save_input=noop,
        choose_directory=noop,
        run_calculation_action=QAction("Run"),
        load_output=noop,
        value_action=lambda _value, _action: None,
    )

    assert panel.findChild(CalculationSetupPanel) is panel.calculation_setup
    assert panel.findChild(BrowserPanel) is panel.browser_panel
    assert panel.findChild(ResultActionsWidget) is panel.result_actions_widget
    panel.close()


def test_main_window_wires_controller_state_to_child_presentations(tmp_path):
    app = _app()
    controller = WorkspaceController()
    window = MainWindow(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        ApplicationSettings(tmp_path / "settings.json"),
        track_launch_monitor=lambda _window: None,
    )

    side_panel = window.findChild(ExpertSidePanel)
    overview = window.findChild(StructureOverviewWidget)
    setup = window.findChild(CalculationSetupPanel)
    assert side_panel is not None
    assert overview is not None
    assert setup is not None
    assert window.result_actions_widget is side_panel.result_actions_widget
    assert window.browser_panel is side_panel.browser_panel

    controller.replace_structure(Atoms("Fe", cell=[2.0, 2.0, 2.0], pbc=True))
    parameters = InputParameters.create("scf")
    controller.replace_input_parameters(parameters)
    controller.change_directory(str(tmp_path))
    app.processEvents()

    assert "Formula: Fe" in overview.info_text
    assert setup.input_preview_text == parameters.to_string(validate=False)
    assert setup.save_input_enabled
    window.close()


def test_main_window_reuses_recent_start_menu(tmp_path):
    app = _app()
    history = RecentFiles(tmp_path / "recent.json")
    window = MainWindow(
        WorkspaceController(),
        history,
        ApplicationSettings(tmp_path / "settings.json"),
        track_launch_monitor=lambda _window: None,
    )
    overview = window.findChild(StructureOverviewWidget)
    assert overview is not None

    history.remember("structure", tmp_path / "first.xyz")
    app.processEvents()
    menus_after_first = overview.findChildren(QMenu)
    history.remember("output", tmp_path / "second.out")
    app.processEvents()
    menus_after_second = overview.findChildren(QMenu)

    assert len(menus_after_second) == len(menus_after_first)
    window.close()


def test_main_window_has_no_working_directory_control(tmp_path):
    _app()
    window = MainWindow(
        WorkspaceController(), RecentFiles(tmp_path / "recent.json"),
        ApplicationSettings(tmp_path / "settings.json"),
        track_launch_monitor=lambda _window: None,
    )
    assert not hasattr(window._calculation_setup, "_directory_label")
    output_menu = next(menu for menu in window.menuBar().findChildren(QMenu)
                       if menu.title() == "&Output")
    assert any("Directory" in action.text() for action in output_menu.actions())
    window.close()
