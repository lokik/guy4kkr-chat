"""Interactive ASE structure shell and workspace publication contracts."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ase import Atoms
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QPlainTextEdit

from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.dialogs.structures import shell
from guy4ase.gui.dialogs.structures import source as source_dialog
from guy4ase.gui.flows import structures
from guy4ase.gui.workflow.model import CreateStructure, CreateStructureKind, WorkflowSection
from guy4ase.gui.workflow.planner import WorkflowPlanner


def _app():
    return QApplication.instance() or QApplication([])


def _flush():
    # Qonsole runs user commands via a queued connection on the GUI thread.
    for _ in range(10):
        _app().processEvents()


def _enter(dialog, source):
    dialog.console.insert_input_text(source)
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Return)
    _flush()


def test_shell_uses_one_editable_console_with_instructions():
    _app()
    dialog = shell.StructureShellDialog()
    assert isinstance(dialog.console.edit, QPlainTextEdit)
    assert "use_structure(atoms)" in dialog.console.edit.toPlainText()
    assert "Shift+Enter" in dialog.console.edit.toPlainText()
    assert not hasattr(dialog.console, "input")
    # Qonsole renders the prompt in its separate gutter, not in the editor text.
    assert dialog.console.in_prompt().strip() == ">>>"
    dialog.reject()


def test_shell_accepts_explicit_use_and_shows_output():
    _app()
    dialog = shell.StructureShellDialog()
    _enter(dialog, "atoms = bulk('Fe', 'bcc', a=2.87, cubic=True)")
    assert dialog.candidate is None
    _enter(dialog, "print(atoms.get_chemical_formula())")
    assert "Fe2" in dialog.console.edit.toPlainText()
    _enter(dialog, "use(atoms)")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert isinstance(dialog.candidate, Atoms)
    assert dialog.candidate.get_chemical_symbols() == ["Fe", "Fe"]


def test_shell_pastes_and_executes_whole_python_block():
    _app()
    dialog = shell.StructureShellDialog()
    block = (
        "from ase.build import bulk\n"
        "atoms = bulk('Ni', 'fcc', a=3.52)\n"
        "atoms *= (2, 1, 1)\n"
        "use_structure(atoms)"
    )
    _app().clipboard().setText(block)
    QTest.keyClick(
        dialog.console.edit,
        Qt.Key.Key_V,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert dialog.console.input_buffer() == block
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Return)
    _flush()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.candidate.get_chemical_symbols() == ["Ni", "Ni"]


def test_shell_shift_enter_edits_multiline_before_execution():
    _app()
    dialog = shell.StructureShellDialog()
    dialog.console.insert_input_text("structure = Atoms('Ni')")
    QTest.keyClick(
        dialog.console.edit,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert dialog.console.input_buffer() == "structure = Atoms('Ni')\n"
    dialog.console.insert_input_text("use_structure(structure)")
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Return)
    _flush()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.candidate.get_chemical_symbols() == ["Ni"]
    # The accepted value is a copy of the console variable.
    dialog.console.interpreter.locals["structure"].set_chemical_symbols(["Cu"])
    assert dialog.candidate.get_chemical_symbols() == ["Ni"]


def test_shell_invalid_candidate_does_not_close_and_reports_error():
    _app()
    dialog = shell.StructureShellDialog()
    _enter(dialog, "use('Fe')")
    assert dialog.candidate is None
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "expects an ase.Atoms" in dialog.console.edit.toPlainText()
    _enter(dialog, "use(Atoms('Fe'))")
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_enter_in_visible_shell_never_triggers_cancel_button():
    _app()
    dialog = shell.StructureShellDialog()
    dialog.show()
    _flush()

    # Even with the dialog showing, the first plain Enter is a console input,
    # not a click on the dialog's sole Cancel button.
    _enter(dialog, "")
    assert dialog.isVisible()
    assert dialog.result() != QDialog.DialogCode.Rejected

    _enter(dialog, "x = 42")
    assert dialog.isVisible()
    assert dialog.console.interpreter.locals["x"] == 42

    _enter(dialog, "use(Atoms('Fe'))")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.candidate.get_chemical_symbols() == ["Fe"]


def test_shell_python_exceptions_keep_dialog_open_and_console_usable():
    _app()
    dialog = shell.StructureShellDialog()
    dialog.show()
    _flush()

    for statement, expected in (
        ("raise ValueError('bad structure')", "ValueError: bad structure"),
        ("undefined_structure_name", "NameError"),
        ("raise KeyboardInterrupt", "KeyboardInterrupt"),
        ("if True print('invalid')", "SyntaxError"),
    ):
        _enter(dialog, statement)
        assert dialog.isVisible(), statement
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert dialog.candidate is None
        assert expected in dialog.console.edit.toPlainText()

    # Errors must not poison the interpreter or select a structure.
    _enter(dialog, "atoms = Atoms('Fe')")
    _enter(dialog, "use(atoms)")
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.candidate.get_chemical_symbols() == ["Fe"]


def test_shell_close_exit_quit_and_sys_exit_discard_session():
    _app()
    for action in ("close", "exit()", "quit()", "import sys; sys.exit()"):
        dialog = shell.StructureShellDialog()
        _enter(dialog, "atoms = Atoms('Fe')")
        if action == "close":
            dialog.reject()
        else:
            _enter(dialog, action)
        assert dialog.candidate is None
        assert dialog.result() == QDialog.DialogCode.Rejected


def test_shell_history_is_part_of_console():
    _app()
    dialog = shell.StructureShellDialog()
    _enter(dialog, "x = 1")
    _enter(dialog, "x = 2")
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Up)
    assert dialog.console.input_buffer() == "x = 2"
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Up)
    assert dialog.console.input_buffer() == "x = 1"
    QTest.keyClick(dialog.console.edit, Qt.Key.Key_Down)
    assert dialog.console.input_buffer() == "x = 2"
    dialog.reject()


def test_shell_flow_only_publishes_when_selected(monkeypatch):
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
