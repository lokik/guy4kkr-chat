"""Composition-root and shared GUI-session regressions."""
import json
import os

from ase import Atoms
from ase2sprkkr.input_parameters.input_parameters import InputParameters

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/ase2sprkkr_gui-test-matplotlib')

from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.main import GuiApplication


def test_composition_root_owns_state_objects_and_loads_history(tmp_path):
    _application = QApplication.instance() or QApplication([])
    history = tmp_path / 'recent.json'
    history.write_text(json.dumps({
        'recent_files': {
            'structure': ['/tmp/Fe.cif'],
            'input': [],
            'output': [],
        },
        'last_recent_kind': 'structure',
    }))

    gui = GuiApplication(recent_files_path=history)

    assert gui.controller.parent() is gui
    assert gui.recent_files.parent() is gui
    assert gui.recent_files.paths('structure') == ('/tmp/Fe.cif',)


def test_composition_root_reuses_both_windows_and_shared_state(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / 'recent.json')
    workflow = gui.create_workflow_window()

    workflow._open_expert_mode()
    application.processEvents()
    expert = gui.create_main_window()

    assert gui.create_workflow_window() is workflow
    assert gui.create_main_window() is expert
    assert workflow.controller is expert.controller is gui.controller
    assert workflow.recent_history is expert.recent_history is gui.recent_files

    workflow.close()
    application.processEvents()
    assert expert.isVisible()
    expert.close()
    gui.show_main_window()
    application.processEvents()
    assert expert.isVisible()
    expert.close()


def test_expert_workspace_actions_share_availability_policy(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    expert = gui.create_main_window()

    structure_actions = (
        expert.save_structure_action,
        expert.edit_structure_action,
        expert.scale_structure_action,
        expert.repeat_structure_action,
        expert.rotate_structure_action,
        expert.build_2d_structure_action,
        expert.visualize_structure_action,
    )
    assert all(not action.isEnabled() for action in structure_actions)
    assert not expert.run_calculation_action.isEnabled()

    gui.controller.replace_structure(
        Atoms(
            "Fe",
            positions=[[0.0, 0.0, 0.0]],
            cell=[2.0, 2.0, 2.0],
            pbc=True,
        )
    )
    application.processEvents()
    assert all(action.isEnabled() for action in structure_actions)
    assert not expert.run_calculation_action.isEnabled()

    gui.controller.replace_input_parameters(InputParameters.create("scf"))
    gui.controller.change_directory(str(tmp_path))
    application.processEvents()
    assert expert.run_calculation_action.isEnabled()

    gui.controller.replace_structure(None)
    application.processEvents()
    assert all(not action.isEnabled() for action in structure_actions)
    assert not expert.run_calculation_action.isEnabled()
    expert.close()
