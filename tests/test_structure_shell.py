"""Interactive ASE structure shell and workspace publication contracts."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtWidgets import QApplication, QDialog

from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.structures import shell
from guy4ase.gui.dialogs.structures import source as source_dialog
from guy4ase.gui.flows import structures
from guy4ase.gui.workflow.model import CreateStructure, CreateStructureKind, WorkflowSection
from guy4ase.gui.workflow.planner import WorkflowPlanner


def _app():
    return QApplication.instance() or QApplication([])


def _enter(dialog, line):
    dialog.command.setText(line)
    dialog.execute_command()


def test_shell_prints_instructions_and_accepts_explicit_use():
    _app()
    dialog = shell.StructureShellDialog()
    assert "use_structure(atoms)" in dialog.output.toPlainText()
    assert "exit()" in dialog.output.toPlainText()
    _enter(dialog, "atoms = bulk('Fe', 'bcc', a=2.87, cubic=True)")
    assert dialog.candidate is None
    _enter(dialog, "print(atoms.get_chemical_formula())")
    assert "Fe2" in dialog.output.toPlainText()
    _enter(dialog, "use(atoms)")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert isinstance(dialog.candidate, Atoms)
    assert dialog.candidate.get_chemical_symbols() == ["Fe", "Fe"]


def test_shell_multiline_and_use_structure_preserve_snapshot():
    _app()
    dialog = shell.StructureShellDialog()
    for line in ("for _ in range(2):", "    print('ok')", ""):
        _enter(dialog, line)
    assert dialog.output.toPlainText().count("ok") >= 2
    _enter(dialog, "structure = Atoms('Ni', positions=[(0, 0, 0)])")
    _enter(dialog, "use_structure(structure)")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.candidate.get_chemical_symbols() == ["Ni"]
    # The accepted value is a copy, not the mutable console variable.
    dialog.console.locals["structure"].set_chemical_symbols(["Cu"])
    assert dialog.candidate.get_chemical_symbols() == ["Ni"]


def test_shell_invalid_candidate_does_not_close_and_reports_error():
    _app()
    dialog = shell.StructureShellDialog()
    _enter(dialog, "use('Fe')")
    assert dialog.candidate is None
    assert "expects an ase.Atoms" in dialog.output.toPlainText()
    _enter(dialog, "use(Atoms('Fe'))")
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_shell_close_and_exit_discard_session():
    _app()
    dialog = shell.StructureShellDialog()
    _enter(dialog, "atoms = Atoms('Fe')")
    dialog.reject()
    assert dialog.candidate is None
    assert dialog.result() == QDialog.DialogCode.Rejected

    other = shell.StructureShellDialog()
    _enter(other, "exit()")
    assert other.result() == QDialog.DialogCode.Rejected
    assert other.candidate is None


def test_shell_history():
    _app()
    dialog = shell.StructureShellDialog()
    _enter(dialog, "x = 1")
    _enter(dialog, "x = 2")
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent

    def key(code):
        return QKeyEvent(QKeyEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier)

    dialog.command.keyPressEvent(key(Qt.Key.Key_Up))
    assert dialog.command.text() == "x = 2"
    dialog.command.keyPressEvent(key(Qt.Key.Key_Up))
    assert dialog.command.text() == "x = 1"
    dialog.command.keyPressEvent(key(Qt.Key.Key_Down))
    assert dialog.command.text() == "x = 2"
    dialog.reject()


def test_shell_workflow_only_publishes_when_selected(monkeypatch):
    _app()
    controller = WorkspaceController()
    generation = controller.structure_generation
    monkeypatch.setattr(shell, "select_shell_structure", lambda parent: None)
    assert structures.create_structure_by_shell(controller, None) is None
    assert controller.atoms is None
    assert controller.structure_generation == generation

    atoms = Atoms("Fe", cell=[2.9, 2.9, 2.9], pbc=True)
    monkeypatch.setattr(shell, "select_shell_structure", lambda parent: atoms)
    assert structures.create_structure_by_shell(controller, None) is atoms
    assert controller.atoms is atoms
    assert controller.structure_generation == generation.next()


def test_source_dialog_uses_shell_result_as_detached_candidate(monkeypatch, tmp_path):
    from guy4ase.gui.application.recent_files import RecentFiles

    _app()
    dialog = source_dialog.StructureSourceDialog(
        recent_files=RecentFiles(tmp_path / "recent.json")
    )
    monkeypatch.setattr(shell, "select_shell_structure", lambda parent: None)
    dialog._create_from_shell()
    assert dialog.candidate() is None
    atoms = Atoms("Ni")
    monkeypatch.setattr(shell, "select_shell_structure", lambda parent: atoms)
    dialog._create_from_shell()
    assert dialog.candidate().atoms is atoms
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_guided_initial_plan_exposes_shell_only_without_structure():
    plan = WorkflowPlanner().initial_plan()
    create = plan.group(WorkflowSection.CREATE)
    assert create is not None
    assert CreateStructure(CreateStructureKind.SHELL) in tuple(
        action.command for action in create.actions
    )
    from guy4ase.gui.application.workspace import WorkspaceState

    controller = WorkspaceController(WorkspaceState(atoms=Atoms("Fe")))
    active = WorkflowPlanner().for_workspace(controller)
    assert all(
        action.command != CreateStructure(CreateStructureKind.SHELL)
        for group in active.groups for action in group.actions
    )
