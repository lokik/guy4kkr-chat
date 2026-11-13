"""Structure shell behavior with the embedded PyQtGraph console."""
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
    """Use the console widget's real command-input path."""
    dialog.console.input.setText(line)
    dialog.console.input.execCmd()


def test_shell_hints_and_explicit_selection():
    _app()
    dialog = shell.StructureShellDialog()
    assert "use_structure(atoms)" in dialog.console.output.toPlainText()
    assert "exit()" in dialog.console.output.toPlainText()
    _enter(dialog, "atoms = bulk('Fe', 'bcc', a=2.87, cubic=True)")
    assert dialog.candidate is None
    _enter(dialog, "print(atoms.get_chemical_formula())")
    assert "Fe2" in dialog.console.output.toPlainText()
    _enter(dialog, "use(atoms)")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert isinstance(dialog.candidate, Atoms)
    assert dialog.candidate.get_chemical_symbols() == ["Fe", "Fe"]


def test_shell_multiline_and_accepted_structure_is_detached():
    _app()
    dialog = shell.StructureShellDialog()
    for line in ("for _ in range(2):", "    print('ok')", ""):
        _enter(dialog, line)
    assert dialog.console.output.toPlainText().count("ok") >= 2
    _enter(dialog, "structure = Atoms('Ni', positions=[(0, 0, 0)])")
    _enter(dialog, "use_structure(structure)")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.candidate.get_chemical_symbols() == ["Ni"]
    dialog.console.localNamespace["structure"].set_chemical_symbols(["Cu"])
    assert dialog.candidate.get_chemical_symbols() == ["Ni"]


def test_shell_invalid_candidate_does_not_accept():
    _app()
    dialog = shell.StructureShellDialog()
    _enter(dialog, "use('Fe')")
    assert dialog.candidate is None
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "expects an ase.Atoms" in dialog.console.output.toPlainText()
    _enter(dialog, "use(Atoms('Fe'))")
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_shell_close_exit_and_quit_discard_without_exiting_application():
    _app()
    for action in ("close", "exit()", "quit()"):
        dialog = shell.StructureShellDialog()
        _enter(dialog, "atoms = Atoms('Fe')")
        if action == "close":
            dialog.reject()
        else:
            _enter(dialog, action)
        assert dialog.candidate is None
        assert dialog.result() == QDialog.DialogCode.Rejected


def test_shell_command_history_is_managed_by_console():
    _app()
    dialog = shell.StructureShellDialog()
    _enter(dialog, "x = 1")
    _enter(dialog, "x = 2")
    assert dialog.console.input.history[1:3] == ["x = 2", "x = 1"]
    dialog.reject()


def test_shell_flow_only_publishes_selected_structure(monkeypatch):
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
