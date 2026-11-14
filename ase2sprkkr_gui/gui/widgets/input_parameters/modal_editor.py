"""Modal presentation of a registered expert field editor."""
from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath
from ase2sprkkr_gui.gui.input_parameters.expert_fields import ExpertFieldSpec
from ase2sprkkr_gui.gui.input_parameters.field_binding import SessionFieldBinding
from ase2sprkkr_gui.gui.input_parameters.session import create_input_parameters_session
from ase2sprkkr_gui.gui.widgets.input_parameters.registry import create_editor


class ExpertFieldEditorDialog(QDialog):
    """Edit one field on an isolated parameter copy and publish it on OK."""

    def __init__(
        self,
        parameters: Any,
        path: InputParameterPath,
        spec: ExpertFieldSpec,
        *,
        atoms: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = create_input_parameters_session(parameters, self)
        self._path = path
        option = self.session.option(path)

        self.setWindowTitle(f"Edit {'.'.join(path)}")
        self.setModal(True)
        self.resize(max(spec.minimum_width or 0, 420), 360)
        layout = QVBoxLayout(self)

        placement = spec.placement(path, option.name)
        binding = SessionFieldBinding(
            self.session,
            placement,
            "expert-modal",
        )
        self.editor = create_editor(
            binding,
            placement,
            atoms=atoms,
            parent=self,
        )
        self.editor.refresh()
        layout.addWidget(self.editor, 1)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.editor.validationChanged.connect(self._show_error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def value(self) -> Any:
        return self.session.value(self._path)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def _accept_if_valid(self) -> None:
        if self.editor.commit():
            self.accept()
