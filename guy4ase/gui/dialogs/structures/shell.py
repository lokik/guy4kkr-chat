"""Interactive ASE console for building a detached atomic structure.

The console is intentionally opt-in: user-entered Python runs in the GUI
process with the user's permissions. Only use_structure() publishes a
candidate; closing the dialog otherwise leaves the workspace unchanged.
"""
from __future__ import annotations

from code import InteractiveConsole
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from ase import Atoms
from ase.build import bulk, surface
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class _ConsoleInput(QLineEdit):
    """Single-line input with ordinary Python-shell command history."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history: list[str] = []
        self._position = 0
        self._draft = ""

    def remember(self, command: str) -> None:
        if command.strip() and (not self._history or self._history[-1] != command):
            self._history.append(command)
        self._position = len(self._history)
        self._draft = ""

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Up and self._history:
            if self._position == len(self._history):
                self._draft = self.text()
            self._position = max(0, self._position - 1)
            self.setText(self._history[self._position])
            return
        if event.key() == Qt.Key.Key_Down and self._history:
            self._position = min(len(self._history), self._position + 1)
            self.setText(
                self._draft
                if self._position == len(self._history)
                else self._history[self._position]
            )
            return
        super().keyPressEvent(event)


class StructureShellDialog(QDialog):
    """Evaluate Python interactively and return an ASE Atoms only on explicit use."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Structure by Python Shell")
        self.resize(800, 500)
        self._candidate: Atoms | None = None
        self._continuation = False

        layout = QVBoxLayout(self)
        notice = QLabel(
            "Python code runs with your user permissions in the GUI process. "
            "Use only code you trust.",
            self,
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)

        self.output = QPlainTextEdit(self)
        self.output.setObjectName("structureShellOutput")
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)

        self.command = _ConsoleInput(self)
        self.command.setObjectName("structureShellInput")
        self.command.setPlaceholderText("Python command; Enter to execute, ↑/↓ for history")
        self.command.returnPressed.connect(self.execute_command)
        layout.addWidget(self.command)

        namespace = {
            "__name__": "__console__",
            "Atoms": Atoms,
            "bulk": bulk,
            "surface": surface,
            "use_structure": self.use_structure,
            "use": self.use_structure,
        }
        self.console = InteractiveConsole(locals=namespace)
        self.output.setPlainText(
            "Interactive ASE Python shell\n"
            "Create a structure, then call use_structure(atoms) or use(atoms).\n"
            "For example:\n"
            "    atoms = bulk('Fe', 'bcc', a=2.87, cubic=True)\n"
            "    use(atoms)\n"
            "You can also create Atoms directly: Atoms('H2', positions=[(0,0,0), (0,0,0.74)]).\n"
            "Close this window, or type exit() / quit(), to discard the session.\n"
            "Multiline blocks use ... prompts; press Enter on a blank line to finish."
        )
        self.command.setFocus()

    @property
    def candidate(self) -> Atoms | None:
        """The detached result, or None if the shell was dismissed."""
        return self._candidate

    def use_structure(self, atoms: Atoms) -> None:
        """Explicitly select an independent snapshot and close the shell."""
        if not isinstance(atoms, Atoms):
            raise TypeError("use_structure() expects an ase.Atoms object")
        self._candidate = atoms.copy()
        self.accept()

    def execute_command(self) -> None:
        line = self.command.text()
        self.command.remember(line)
        self.command.clear()
        self.output.appendPlainText(("... " if self._continuation else ">>> ") + line)

        output = StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(output):
                self._continuation = self.console.push(line)
        except SystemExit:
            # Standard Python-shell exit() and quit() discard the candidate.
            self.reject()
        finally:
            result = output.getvalue()
            if result:
                self.output.appendPlainText(result.rstrip("\n"))


def select_shell_structure(parent: QWidget | None = None) -> Atoms | None:
    """Open a disposable console and return a structure only after use()."""
    dialog = StructureShellDialog(parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.candidate
