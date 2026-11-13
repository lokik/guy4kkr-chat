"""Embedded, multiline ASE Python shell for detached structure creation.

User code runs in the GUI process. An explicit use(atoms) / use_structure(atoms)
selects a snapshot; closing the dialog or exiting the interpreter leaves the
workspace unchanged.
"""
from __future__ import annotations

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


_HINT = """Interactive ASE Python shell

Create an ASE Atoms object, then call use(atoms) or use_structure(atoms).
For example:

    atoms = bulk('Fe', 'bcc', a=2.87, cubic=True)
    use(atoms)

Atoms, bulk and surface are already imported.
Paste complete Python blocks, or use Shift+Enter to insert another line.
Press Enter to execute. Type exit(), quit() or sys.exit() to discard the session.
"""


class StructureShellDialog(QDialog):
    """Present a real editable console; publish only an explicit ASE candidate."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Structure by Python Shell")
        self.resize(800, 500)
        self._candidate: Atoms | None = None

        layout = QVBoxLayout(self)
        notice = QLabel(
            "Python commands run inside Guy4ASE with your user permissions. "
            "Only run code you trust.",
            self,
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        self.console = PythonConsole(
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


def select_shell_structure(parent: QWidget | None = None) -> Atoms | None:
    """Return a structure only if the user explicitly selected it in Python."""
    dialog = StructureShellDialog(parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.candidate
