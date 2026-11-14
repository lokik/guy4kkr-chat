"""Embedded, multiline ASE Python shell for detached structure creation.

User code runs in the GUI process. An explicit use(atoms) / use_structure(atoms)
selects a snapshot; closing the dialog or exiting the interpreter leaves the
workspace unchanged.
"""
from __future__ import annotations

import logging

from ase import Atoms
from ase.build import bulk, surface
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qonsole import PythonConsole

from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.application.shell_history import PythonReplHistory, ShellHistory

logger = logging.getLogger(__name__)


_HINT = """Interactive ASE Python shell

Create an ASE Atoms object, then call use(atoms) or use_structure(atoms).
For example:

    atoms = bulk('Fe', 'bcc', a=2.87, cubic=True)
    use(atoms)

Atoms, bulk and surface are already imported.
Paste complete Python blocks, or use Shift+Enter to insert another line.
Press Enter to execute. Type exit(), quit() or sys.exit() to discard the session.
"""


class _StructurePythonConsole(PythonConsole):
    """Persist own commands, optionally exchanging them with the Python REPL."""

    def __init__(
        self, *args,
        history: ShellHistory,
        python_history: PythonReplHistory | None = None,
        **kwargs,
    ):
        self._history_store = history
        self._python_history = python_history
        self._saved_commands = history.load()
        super().__init__(*args, **kwargs)

        external = python_history.load() if python_history is not None else []
        external_commands = set(external)
        for command in self._saved_commands:
            if command not in external_commands:
                self.command_history.add(command)
        for command in external:
            self.command_history.add(command)

    def process_input(self, source: str) -> None:
        before = len(self.command_history._cmd_history)
        try:
            super().process_input(source)
        finally:
            # Only persist actual newly executed commands, not commands
            # imported from Python's history or an incomplete input block.
            commands = self.command_history._cmd_history[before:]
            if commands:
                self._saved_commands.extend(commands)
                try:
                    self._history_store.save(self._saved_commands)
                except OSError:
                    logger.exception(
                        "Cannot save Python shell history to %s",
                        self._history_store.path,
                    )
                if self._python_history is not None:
                    try:
                        self._python_history.append(commands)
                    except OSError:
                        logger.exception(
                            "Cannot append to Python REPL history %s",
                            self._python_history.path,
                        )


class StructureShellDialog(QDialog):
    """Present a real editable console; publish only an explicit ASE candidate."""

    def __init__(
        self, parent: QWidget | None = None, *,
        settings: ApplicationSettings | None = None,
        history: ShellHistory | None = None,
        python_history: PythonReplHistory | None = None,
    ) -> None:
        super().__init__(parent)
        if settings is None:
            settings = ApplicationSettings()
            settings.load()
        history_store = history if history is not None else ShellHistory()
        shared_history = (
            python_history if python_history is not None else PythonReplHistory()
        ) if settings.share_python_shell_history else None
        self.setWindowTitle("Create Structure by Python Shell")
        self.resize(800, 500)
        self._candidate: Atoms | None = None

        layout = QVBoxLayout(self)
        notice = QLabel(
            "Python commands run inside Ase2sprkkr with your user permissions. "
            "Only run code you trust.",
            self,
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        self.console = _StructurePythonConsole(
            history=history_store,
            python_history=shared_history,
            parent=self,
            locals={
                "Atoms": Atoms,
                "bulk": bulk,
                "surface": surface,
                "use_structure": self.use_structure,
                "use": self.use_structure,
            },
            inprompt=">>>",
            welcome_message=_HINT,
        )
        # Execute on the GUI thread: use_structure() calls QDialog.accept().
        # Qonsole handles SystemExit from exit(), quit() and sys.exit() itself.
        self.console.eval_queued()
        self.console.interpreter.exit_signal.connect(self.reject)
        layout.addWidget(self.console, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        # QDialog makes auto-default buttons react to Enter. The console owns
        # Enter (including empty lines); it must never activate Cancel.
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.console.edit.setFocus()

    @property
    def candidate(self) -> Atoms | None:
        """Detached accepted structure, or None after ordinary dismissal."""
        return self._candidate

    def use_structure(self, atoms: Atoms) -> None:
        """Select a defensive copy; publication belongs to the calling flow."""
        if not isinstance(atoms, Atoms):
            raise TypeError("use_structure() expects an ase.Atoms object")
        self._candidate = atoms.copy()
        self.accept()


def select_shell_structure(
    parent: QWidget | None = None, *,
    settings: ApplicationSettings | None = None,
    history: ShellHistory | None = None,
    python_history: PythonReplHistory | None = None,
) -> Atoms | None:
    """Return a structure only if the user explicitly selected it in Python."""
    dialog = StructureShellDialog(
        parent, settings=settings, history=history,
        python_history=python_history,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.candidate
