"""Modal workflow for editing an isolated copy of ``InputParameters``."""
from __future__ import annotations

from typing import Any

from ase2sprkkr import InputParameters
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.window_geometry import manage_window_geometry
from ase2sprkkr_gui.gui.flows.input_parameters import (
    choose_and_load_input_parameters,
    edit_input_parameters_file,
)
from ase2sprkkr_gui.gui.input_parameters.dataset import apply_default_dataset
from ase2sprkkr_gui.gui.input_parameters.session import (
    InputParametersSession,
    create_input_parameters_session,
)
from ase2sprkkr_gui.gui.input_parameters.validation import (
    InputParametersValidationError,
    validate_setup,
)
from ase2sprkkr_gui.gui.widgets.input_parameters.dataset import DatasetEditor
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree import ExpertInputTreeEditor


class InputParametersDialog(QDialog):
    """Own the expert editor's draft and modal accept/cancel workflow."""

    def __init__(
        self,
        parameters: InputParameters | InputParametersSession,
        parent: QWidget | None = None,
        *,
        show_changed_only: bool = False,
        atoms: Any = None,
    ) -> None:
        super().__init__(parent)
        if isinstance(parameters, InputParametersSession):
            self.session = parameters.fork(self)
        else:
            self.session = create_input_parameters_session(parameters, self)

        self.setWindowTitle('Edit Input Parameters')
        manage_window_geometry(
            self,
            "expert-input",
            default_size=(1200, 750),
            default_maximized=True,
        )
        root = QVBoxLayout(self)

        self.dataset_editor = DatasetEditor(self.session, self)
        root.addWidget(self.dataset_editor)

        self.tree_editor = ExpertInputTreeEditor(
            self.session,
            atoms=atoms,
            show_changed_only=show_changed_only,
            parent=self,
        )
        root.addWidget(self.tree_editor, 1)

        self._validation_error = QLabel(self)
        self._validation_error.setWordWrap(True)
        self._validation_error.hide()
        root.addWidget(self._validation_error)
        self.tree_editor.validationChanged.connect(
            lambda _has_errors: self._validation_error.hide()
        )

        footer = QHBoxLayout()
        footer.addStretch(1)
        root.addLayout(footer)

        def add_button(text: str, slot: Any) -> QPushButton:
            button = QPushButton(text, self)
            button.clicked.connect(slot)
            footer.addWidget(button)
            return button

        self.load_btn = add_button('Load input…', self._load_input)
        self.edit_input_btn = add_button('Edit input file…', self._edit_input_file)
        self.cancel_btn = add_button('Cancel', self.reject)
        self.ok_btn = add_button('OK', self._on_ok)

    def _load_input(self) -> None:
        if choose_and_load_input_parameters(self.session, self):
            self.tree_editor.set_show_changed_only(True)

    def _edit_input_file(self) -> None:
        if not self.tree_editor.commit_pending():
            return
        edit_input_parameters_file(self.session, self)

    def _on_ok(self) -> None:
        self._validation_error.hide()
        if not self.tree_editor.commit_pending():
            return
        try:
            validate_setup(self.session.working_parameters)
        except InputParametersValidationError as error:
            self._validation_error.setText(str(error))
            self._validation_error.show()
            return
        self.accept()

    def parameters(self) -> InputParameters:
        """Return a detached copy of the currently edited parameters."""
        return self.session.result()


def edit_input_parameters(
    params: InputParameters,
    parent: QWidget | None = None,
    *,
    show_changed_only: bool = False,
    atoms: Any = None,
) -> InputParameters | None:
    """Open the expert editor and return its accepted isolated draft."""
    session = create_input_parameters_session(params)
    accepted = edit_input_parameters_session(
        session,
        parent=parent,
        show_changed_only=show_changed_only,
        atoms=atoms,
    )
    if accepted is None:
        return None
    return accepted.result()


def edit_input_parameters_session(
    session: InputParametersSession,
    parent: QWidget | None = None,
    *,
    show_changed_only: bool = False,
    atoms: Any = None,
) -> InputParametersSession | None:
    """Run Expert over an isolated fork and return the fork only on Accept."""
    dialog = InputParametersDialog(
        session,
        parent=parent,
        show_changed_only=show_changed_only,
        atoms=atoms,
    )
    code = dialog.exec()
    if code == QDialog.DialogCode.Accepted:
        return dialog.session
    return None


def select_input_parameters(
    atoms: Any,
    parent: QWidget | None = None,
    task: str = 'scf',
    *,
    dataset_default_mode: str,
) -> InputParameters | None:
    """Create fresh parameters for a task and open the expert editor."""
    from importlib import import_module

    task_module = import_module(
        f'ase2sprkkr.input_parameters.definitions.{task.lower()}'
    )
    params_def = task_module.input_parameters()
    params = params_def.create_object()
    apply_default_dataset(params, dataset_default_mode, atoms)
    return edit_input_parameters(params, parent=parent, atoms=atoms)