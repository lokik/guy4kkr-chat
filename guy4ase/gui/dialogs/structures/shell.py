"""Embedded Python console for creating a detached ASE structure.

The console runs user-entered code in the GUI process. Only an explicit
use_structure(atoms) / use(atoms) call selects a structure; dismissing the
dialog otherwise leaves the workspace unchanged.
"""
from __future__ import annotations

from ase import Atoms
from ase.build import bulk, surface
from pyqtgraph.console import ConsoleWidget
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


_HINT = """Interactive ASE Python shell

Create an ASE Atoms object, then call use(atoms) or use_structure(atoms).
Example:
    atoms = bulk('Fe', 'bcc', a=2.87, cubic=True)
    use(atoms)

Atoms, bulk and surface are already imported.
Type exit() or quit(), or close the window, to discard the session.
"""


class StructureShellDialog(QDialog):
    """Use PyQtGraph's interactive console, committing only an explicit choice."""

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

        self.console = ConsoleWidget(
            parent=self,
            namespace={
                "Atoms": Atoms,
                "bulk": bulk,
                "surface": surface,
                "use_structure": self.use_structure,
                "use": self.use_structure,
                # PyQtGraph does not catch SystemExit. Override the built-in
                # helpers locally so exit()/quit() cannot terminate Guy4ASE.
                "exit": self.reject,
                "quit": self.reject,
            },
            text=_HINT,
            allowNonGuiExecution=False,
        )
        layout.addWidget(self.console, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.console.input.setFocus()

    @property
    def candidate(self) -> Atoms | None:
        """Detached accepted structure; None after normal console dismissal."""
        return self._candidate

    def use_structure(self, atoms: Atoms) -> None:
        """Select a snapshot and close; publication belongs to the caller."""
        if not isinstance(atoms, Atoms):
            raise TypeError("use_structure() expects an ase.Atoms object")
        self._candidate = atoms.copy()
        self.accept()


def select_shell_structure(parent: QWidget | None = None) -> Atoms | None:
    """Return an ASE structure only when the user explicitly calls use()."""
    dialog = StructureShellDialog(parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.candidate
