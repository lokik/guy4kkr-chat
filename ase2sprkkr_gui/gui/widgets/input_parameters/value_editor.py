"""Explicit lifecycle shared by all parameter value editors."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath


class ParameterValueEditor:
    """Mixin contract implemented by every guided parameter value control.

    Implementations remain concrete Qt widgets. The defaults describe optional
    capabilities so the surrounding session adapter never has to probe a
    control with ``getattr`` or dispatch on its Qt class.
    """

    validationChanged: Any
    dependencies: tuple[InputParameterPath, ...] = ()
    full_width = False
    help_text = ""

    @classmethod
    def from_binding(
        cls,
        binding: Any,
        placement: Any,
        *,
        atoms: Any = None,
        parent: QWidget | None = None,
    ) -> "ParameterValueEditor":
        """Construct an editor from the common model adapter."""
        return cls(binding, placement, atoms=atoms, parent=parent)

    def refresh(self) -> None:
        """Replace the displayed draft from the bound value source."""
        raise NotImplementedError

    def commit(self, *_args: Any) -> bool:
        """Commit the current draft, returning whether it is valid."""
        raise NotImplementedError

    def focus_for_history(
        self,
        _path: InputParameterPath,
        _index: int | None,
    ) -> None:
        """Focus the value selected by Undo/Redo navigation."""
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_editor_tooltip(self, text: str) -> None:
        """Apply a composed tooltip; editors with children may override."""
        self.setToolTip(text)


class ParameterValueEditorWidget(QWidget, ParameterValueEditor):
    """Convenience base for value editors composed from child widgets."""

    validationChanged = pyqtSignal(str)
