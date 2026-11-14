"""Editors bound to an :class:`InputParametersSession`."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath
from ase2sprkkr_gui.gui.input_parameters.field_binding import create_field_binding
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.specs.schema import FieldPlacement
from ase2sprkkr_gui.gui.input_parameters.tooltips import parameter_tooltip
from ase2sprkkr_gui.gui.widgets.input_parameters.registry import create_editor
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import ParameterValueEditor

EDITOR_WIDTH = 280


class ParameterEditor(QWidget):
    """A presentation widget that commits one path through the session."""

    validationChanged = pyqtSignal(object, str, str)

    def __init__(
        self,
        session: InputParametersSession,
        placement: FieldPlacement,
        page_id: str,
        *,
        atoms: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.placement = placement
        self.path: InputParameterPath = placement.path
        self.page_id = page_id
        self.atoms = atoms
        self._error = ""
        self._disabled_reason = ""
        self._presentation_help = ""
        self.binding = create_field_binding(session, placement, page_id)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.control = self._create_control()
        if not isinstance(self.control, ParameterValueEditor):
            raise TypeError("Parameter controls must implement ParameterValueEditor")
        self.full_width = self.control.full_width
        if not self.full_width:
            self.control.setFixedWidth(EDITOR_WIDTH)
        layout.addWidget(self.control, 1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if not self.full_width:
            self.setFixedWidth(EDITOR_WIDTH)

        option = self.session.option(self.path)
        self._base_tooltip = parameter_tooltip(
            option,
            self.path[0],
            self.path[-1],
            placement.label,
        )
        extra_help = self.control.help_text
        if extra_help:
            self._base_tooltip += f"\n{extra_help}"
        self.setToolTip(self._base_tooltip)
        self.control.setToolTip(self._base_tooltip)
        self.control.set_editor_tooltip(self._base_tooltip)
        self._connect_control()
        self.session.editApplied.connect(self._session_changed)
        self.refresh()

    def _session_changed(self, paths, reset):
        """Preserve unrelated drafts; replacements and history explicitly discard them."""
        dependencies = set(self.placement.paths)
        dependencies.update(self.control.dependencies)
        if reset or dependencies.intersection(paths):
            self.refresh()

    def _create_control(self) -> QWidget:
        return create_editor(
            self.binding,
            self.placement,
            atoms=self.atoms,
            parent=self,
        )

    def _connect_control(self) -> None:
        self.control.validationChanged.connect(self._set_error)

    def commit(self) -> bool:
        """Apply this draft through the session, reporting errors without raising.

        Return success, not whether a value changed. Indexed fields replace
        only their array component; registered widgets implement their own commit.
        """
        if not self.control.isEnabled():
            return True
        return self.control.commit()

    def refresh(self) -> None:
        """Replace the draft from session state without creating an edit.

        Implicit backend defaults are placeholders, never GUI-invented values.
        A deliberate refresh also clears local validation errors.
        """
        self.control.refresh()
        self._set_error("")

    def _set_error(self, message: str) -> None:
        if message == self._error:
            return
        self._error = message
        if message:
            self.control.setStyleSheet("border: 2px solid palette(highlight);")
        else:
            self.control.setStyleSheet("")
        self._update_tooltip()
        self.validationChanged.emit(self.path, self.page_id, message)

    def _update_tooltip(self) -> None:
        tooltip = self._base_tooltip
        if self._presentation_help:
            tooltip += f"\n\n{self._presentation_help}"
        if self._disabled_reason:
            tooltip += f"\n\nDisabled: {self._disabled_reason}"
        if self._error:
            tooltip += f"\n\nInvalid value: {self._error}"
        self.setToolTip(tooltip)
        self.control.setToolTip(tooltip)
        self.control.set_editor_tooltip(tooltip)

    def set_parameter_enabled(self, enabled: bool, reason: str | None = None) -> None:
        """Disable interaction with an explanation, retaining the underlying value."""
        self.control.setEnabled(enabled)
        self._disabled_reason = "" if enabled else reason or ""
        self._update_tooltip()

    def set_presentation_help(self, text: str | None) -> None:
        """Add rule-derived help without replacing validation or option help."""
        self._presentation_help = text or ""
        self._update_tooltip()

    def focus_for_history(self, path: InputParameterPath, index: int | None) -> None:
        """Focus the value restored by Undo/Redo without exposing editor internals."""
        self.control.focus_for_history(path, index)
