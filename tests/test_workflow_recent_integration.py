from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.workflow.model import ContinueRecent, WorkflowSection
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
    assert tuple(group.title for group in recent.menu) == ("Structures", "Outputs")
    assert recent.menu[0].items[0].command == recent.command
    assert recent.menu[1].items == ()

    window.close()
