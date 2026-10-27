from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class _InputPreview(QPlainTextEdit):
    """Read-only preview that exposes editing intent without event monkey-patching."""

    editRequested = pyqtSignal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.editRequested.emit()
        event.accept()


class CalculationSetupPanel(QWidget):
    """Present expert input and calculation controls without application policy."""

    def __init__(
        self,
        *,
        edit_input: Callable[[], None],
        load_input: Callable[[], None],
        save_input: Callable[[], None],
        run_calculation_action: QAction,
        load_output: Callable[[], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._build_input_panel(
            layout,
            edit_input=edit_input,
            load_input=load_input,
            save_input=save_input,
        )
        self._build_calculation_panel(
            layout,
            run_calculation_action=run_calculation_action,
            load_output=load_output,
        )

    def set_input_preview(self, text: str | None, *, input_available: bool) -> None:
        """Render an already-formatted input preview."""
        self._create_input_btn.setText(
            "Edit SPRKKR Input File..."
            if input_available
            else "Create SPRKKR Input File..."
        )
        self._input_params_preview.setPlainText(text or "")

    def set_save_input_enabled(self, enabled: bool) -> None:
        self._save_input_btn.setEnabled(enabled)

    def set_potential_path(self, path: Optional[str]) -> None:
        value = path or "—"
        self._potential_path_label.setText(value)
        self._potential_path_label.setToolTip(path or "")

    @property
    def input_preview_text(self) -> str:
        return self._input_params_preview.toPlainText()

    @property
    def input_button_text(self) -> str:
        return self._create_input_btn.text()

    @property
    def save_input_enabled(self) -> bool:
        return self._save_input_btn.isEnabled()

    @property
    def potential_path_text(self) -> str:
        return self._potential_path_label.text()

    def _build_input_panel(
        self,
        layout: QVBoxLayout,
        *,
        edit_input: Callable[[], None],
        load_input: Callable[[], None],
        save_input: Callable[[], None],
    ) -> None:
        layout.addSpacing(5)
        label = QLabel("SPRKKR Tools:")
        label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(label)

        self._create_input_btn = QPushButton("Create SPRKKR Input File...")
        self._create_input_btn.clicked.connect(edit_input)
        layout.addWidget(self._create_input_btn)

        load_button = QPushButton("Load SPRKKR Input File...")
        load_button.clicked.connect(load_input)
        layout.addWidget(load_button)

        self._save_input_btn = QPushButton("Save SPRKKR Input File...")
        self._save_input_btn.setEnabled(False)
        self._save_input_btn.clicked.connect(save_input)
        layout.addWidget(self._save_input_btn)

        self._input_params_preview = _InputPreview()
        self._input_params_preview.setReadOnly(True)
        self._input_params_preview.setPlaceholderText(
            "SPRKKR input parameters preview"
        )
        self._input_params_preview.setMinimumHeight(120)
        self._input_params_preview.editRequested.connect(edit_input)
        layout.addWidget(self._input_params_preview)

    def _build_calculation_panel(
        self,
        layout: QVBoxLayout,
        *,
        run_calculation_action: QAction,
        load_output: Callable[[], None],
    ) -> None:
        potential_row = QWidget(self)
        potential_layout = QHBoxLayout(potential_row)
        potential_layout.setContentsMargins(0, 0, 0, 0)
        potential_layout.setSpacing(6)
        potential_layout.addWidget(QLabel("Potential:"))
        self._potential_path_label = QLabel("—")
        self._potential_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        potential_layout.addWidget(self._potential_path_label, 1)
        layout.addWidget(potential_row)

        run_button = QToolButton()
        run_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        run_button.setDefaultAction(run_calculation_action)
        layout.addWidget(run_button)

        load_output_button = QPushButton("Load SPRKKR Output File...")
        load_output_button.clicked.connect(load_output)
        layout.addWidget(load_output_button)
