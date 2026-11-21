from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.workflow.model import ContinueRecent, RepeatRecentInput, WorkflowSection
from ase2sprkkr_gui.main import GuiApplication


def test_recent_history_change_refreshes_guided_plan(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    window = gui.create_workflow_window()

    load = window.workflow_plan.group(WorkflowSection.LOAD)
    assert load is not None
    assert not any(isinstance(action.command, ContinueRecent) for action in load.actions)

    structure = tmp_path / "Fe.cif"
    structure.touch()
    gui.recent_files.remember("structure", structure)
    application.processEvents()

    load = window.workflow_plan.group(WorkflowSection.LOAD)
    assert load is not None
    recent = next(
        action for action in load.actions if isinstance(action.command, ContinueRecent)
    )
    expected_path = str(structure.resolve())
    assert recent.command == ContinueRecent("structure", expected_path)
    assert recent.tooltip == expected_path
    assert tuple(group.title for group in recent.menu) == ("Structures", "Results")
    assert recent.menu[0].items[0].command == recent.command
    assert recent.menu[1].items == ()

    window.close()

def test_recent_input_is_opened_with_standalone_editor(tmp_path, monkeypatch):
    from ase2sprkkr_gui.gui.flows import custom_calculation
    _app = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    window = gui.create_workflow_window()
    path = tmp_path / "original.inp"
    path.touch()
    gui.recent_files.remember("input", path)
    _app.processEvents()

    load = window.workflow_plan.group(WorkflowSection.LOAD)
    assert load is not None
    assert not any(isinstance(action.command, ContinueRecent) for action in load.actions)
    custom = window.workflow_plan.group(WorkflowSection.CUSTOM)
    assert custom is not None
    recent = next(action for action in custom.actions if isinstance(action.command, RepeatRecentInput))
    assert recent.command == RepeatRecentInput(str(path.resolve()))
    opened = []
    monkeypatch.setattr(
        custom_calculation, "load_custom_input",
        lambda controller, history, parent, file_path, **kwargs:
            opened.append((controller, history, parent, file_path)) or True,
    )
    window.execute_workflow_command(recent.command)
    assert opened == [
        (gui.controller, gui.recent_files, window, str(path.resolve()))
    ]
    assert gui.controller.input_parameters is None
    window.close()


def test_background_cleanup_replaces_initial_recent_menus_once(tmp_path):
    import time
    from ase2sprkkr_gui.gui.application.recent_files import RecentFiles

    app = QApplication.instance() or QApplication([])
    recent_path = tmp_path / "recent.json"
    history = RecentFiles(recent_path)
    missing = tmp_path / "deleted.cif"
    existing = tmp_path / "present.cif"
    existing.touch()
    history.remember("structure", missing)
    history.remember("structure", existing)

    gui = GuiApplication(recent_files_path=recent_path)
    window = gui.create_workflow_window()
    load = window.workflow_plan.group(WorkflowSection.LOAD)
    assert load is not None
    assert any(isinstance(a.command, ContinueRecent) for a in load.actions)

    deadline = time.monotonic() + 2
    while gui.recent_files.paths("structure") != (str(existing),) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert gui.recent_files.paths("structure") == (str(existing),)
    recent = next(
        a for a in window.workflow_plan.group(WorkflowSection.LOAD).actions
        if isinstance(a.command, ContinueRecent)
    )
    assert tuple(item.command.path for item in recent.menu[0].items) == (str(existing),)
    window.close()



def test_recent_inputs_refresh_repeat_calculation_with_structure_loaded(tmp_path):
    from ase import Atoms

    app = QApplication.instance() or QApplication([])
    gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
    window = gui.create_workflow_window()
    gui.controller.replace_structure(Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True))
    app.processEvents()

    custom = window.workflow_plan.group(WorkflowSection.CUSTOM)
    assert custom.actions[1].command == RepeatRecentInput(None)
    saved = tmp_path / "Fe_SCF.inp"
    saved.touch()
    gui.recent_files.remember("input", saved)
    app.processEvents()

    custom = window.workflow_plan.group(WorkflowSection.CUSTOM)
    assert custom.actions[1].command == RepeatRecentInput(str(saved.resolve()))
    assert custom.actions[1].menu[0].items[0].command.path == str(saved.resolve())
    window.close()
