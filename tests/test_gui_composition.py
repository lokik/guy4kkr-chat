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


def test_composition_root_reuses_one_guided_window_and_shared_state(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    workflow = gui.create_workflow_window()
    assert gui.create_workflow_window() is workflow
    assert not hasattr(gui, "create_main_window")
    assert workflow.controller is gui.controller
    assert workflow.recent_history is gui.recent_files

    from ase2sprkkr_gui.gui.workflow.model import CustomTask, WorkflowSection
    assert CustomTask() in (
        action.command for action in workflow.workflow_plan.group(WorkflowSection.CUSTOM).actions
    )
    gui.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    application.processEvents()
    assert workflow.controller.atoms is gui.controller.atoms
    assert workflow._load_input_button.text() == "Load Input File"
    assert "Custom calculation" in [
        action.title for action in workflow.workflow_plan.group(WorkflowSection.CUSTOM).actions
    ]
    workflow.close()
