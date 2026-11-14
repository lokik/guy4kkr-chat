"""Prominent editor for ``CONTROL.DATASET``."""
from __future__ import annotations

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from ase2sprkkr_gui.gui.input_parameters.dataset import (
    DATASET_PATH,
    apply_default_dataset,
    dataset_value,
    filename_component,
    generated_dataset,
)
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession


__all__ = [
    "DATASET_PATH",
    "DatasetEditor",
    "apply_default_dataset",
    "dataset_value",
    "filename_component",
    "generated_dataset",
]


class DatasetEditor(QWidget):
    """Keep a visible DATASET field synchronized with an input session."""

    def __init__(
        self,
        session: InputParametersSession,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Dataset:", self))
        self.edit = QLineEdit(self)
        self.edit.setClearButtonEnabled(True)
        self.edit.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"[A-Za-z0-9_.-]*"),
                self.edit,
            )
        )
        self.edit.setPlaceholderText("Leave empty for ASE2SPRKKR automatic naming")
        self.edit.setToolTip(
            "SPR-KKR uses CONTROL.DATASET as the base name for auxiliary result "
            "files. Allowed characters: letters, digits, '.', '_' and '-'. Use a "
            "different DATASET for parallel runs in one directory."
        )
        layout.addWidget(self.edit, 1)
        self.edit.editingFinished.connect(self.commit)
        self.session.parametersReplaced.connect(self._refresh)
        self.session.valueChanged.connect(self._value_changed)
        self._refresh()

    def _value_changed(self, path: object) -> None:
        if path == DATASET_PATH:
            self._refresh()

    def _refresh(self) -> None:
        option = self.session.option(DATASET_PATH)
        value = str(option()) if option.is_set() and option() is not None else ""
        if self.edit.text() != value:
            self.edit.setText(value)

    def commit(self) -> bool:
        """Synchronously apply the current DATASET draft if it changed."""
        value = self.edit.text().strip() or None
        option = self.session.option(DATASET_PATH)
        current = str(option()) if option.is_set() and option() is not None else None
        if value == current:
            return True
        self.session.set_value(
            DATASET_PATH,
            value,
            source_page="dataset",
            text="Change DATASET",
        )
        return True
