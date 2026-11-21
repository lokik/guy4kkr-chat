"""Modal workflow for editing an isolated copy of ``InputParameters``."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ase2sprkkr import InputParameters
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.window_geometry import manage_window_geometry
from ase2sprkkr_gui.gui.flows import presets as preset_flows
from ase2sprkkr_gui.gui.flows.input_parameters import (
    choose_and_load_input_parameters,
    choose_and_save_input_parameters,
    edit_input_parameters_file,
)
from ase2sprkkr_gui.gui.input_parameters.dataset import apply_default_dataset
from ase2sprkkr_gui.gui.input_parameters.session import (
    InputParametersSession,
    create_input_parameters_session,
)
from ase2sprkkr_gui.gui.input_parameters.specs.schema import TaskDialogSpec
from ase2sprkkr_gui.gui.input_parameters.specs.shared import file_source_page
from ase2sprkkr_gui.gui.input_parameters.validation import (
    InputParametersValidationError,
    validate_setup,
)
from ase2sprkkr_gui.gui.widgets.input_parameters.dataset import DatasetEditor
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree import ExpertInputTreeEditor
from ase2sprkkr_gui.gui.widgets.input_parameters.form import GuidedFormRenderer


class InputParametersDialog(QDialog):
    """Own the expert editor's draft and modal accept/cancel workflow."""

    def __init__(
        self,
        parameters: InputParameters | InputParametersSession,
        parent: QWidget | None = None,
        *,
        show_changed_only: bool = False,
        atoms: Any = None,
        calculation_mode: bool = False,
        calculation_unavailable_reason: Callable[[InputParameters], str | None] | None = None,
        file_source_directory=None,
        directory: str | Path | None = None,
        recent_files: RecentFiles | None = None,
    ) -> None:
        super().__init__(parent)
        self.recent_files = recent_files
        self.atoms = atoms
        self.directory = directory or file_source_directory
        self._calculation_mode = calculation_mode
        self._calculation_unavailable_reason = calculation_unavailable_reason
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

        self.file_source_form = None
        self.dataset_editor = None

        self.tree_editor = ExpertInputTreeEditor(
            self.session,
            atoms=atoms,
            show_changed_only=show_changed_only,
            parent=self,
        )
        if file_source_directory is None:
            self.dataset_editor = DatasetEditor(self.session, self)
            root.addWidget(self.dataset_editor)
            root.addWidget(self.tree_editor, 1)
        else:
            tabs = QTabWidget(self)
            pages = QStackedWidget(tabs)
            page = file_source_page(file_source_directory)
            self.file_source_form = GuidedFormRenderer(
                self.session, TaskDialogSpec(page.title, (page,)), pages,
                select_page=lambda _page_id: tabs.setCurrentWidget(pages),
            )
            self.file_source_form.statusChanged.connect(self._update_calculation_availability)
            tabs.addTab(pages, page.title)
            tabs.addTab(self.tree_editor, "Input parameters")
            root.addWidget(tabs, 1)

        self._validation_error = QLabel(self)
        self._validation_error.setWordWrap(True)
        self._validation_error.hide()
        root.addWidget(self._validation_error)
        self.tree_editor.validationChanged.connect(
            lambda _has_errors: self._validation_error.hide()
        )

        file_actions = QHBoxLayout()
        root.addLayout(file_actions)
        footer = QHBoxLayout()
        footer.addStretch(1)
        root.addLayout(footer)

        def add_button(text: str, slot: Any | None, *, finish: bool = False) -> QPushButton:
            button = QPushButton(text, self)
            if slot is not None:
                button.clicked.connect(slot)
            (footer if finish else file_actions).addWidget(button)
            return button

        self.load_btn = add_button('Load input…', self._load_input)
        self.save_btn = add_button('Save Input…', self._save_input)
        self.load_preset_btn = add_button('Replace by preset', None)
        self.merge_preset_btn = add_button('Load preset', None)
        self.replace_preset_menu = QMenu(self.load_preset_btn)
        self.merge_preset_menu = QMenu(self.merge_preset_btn)
        self.load_preset_btn.setMenu(self.replace_preset_menu)
        self.merge_preset_btn.setMenu(self.merge_preset_menu)
        self.replace_preset_menu.aboutToShow.connect(self._refresh_preset_menus)
        self.merge_preset_menu.aboutToShow.connect(self._refresh_preset_menus)
        self.save_preset_btn = add_button('Save as preset…', self._save_preset)
        self._refresh_preset_menus()
        self.edit_input_btn = add_button('Edit input file…', self._edit_input_file)
        file_actions.addStretch(1)
        self.cancel_btn = add_button('Cancel', self.reject, finish=True)
        self.ok_btn = add_button(
            'Calculate' if calculation_mode else 'OK', self._on_ok, finish=True
        )
        self.calculate_button = self.ok_btn if calculation_mode else None
        self.tree_editor.validationChanged.connect(
            lambda _invalid: self._update_calculation_availability()
        )
        self.session.valueChanged.connect(self._update_calculation_availability)
        self.session.parametersReplaced.connect(self._update_calculation_availability)
        self._update_calculation_availability()

    def _update_calculation_availability(self, *_args) -> None:
        if not self._calculation_mode:
            return
        parameters = self.session.working_parameters
        try:
            validate_setup(parameters)
            reason = (
                self._calculation_unavailable_reason(parameters)
                if self._calculation_unavailable_reason is not None else None
            )
        except (InputParametersValidationError, ValueError) as error:
            reason = str(error)
        if self.file_source_form is not None and self.file_source_form.errors:
            reason = "Correct the highlighted input values before calculating."
        self.ok_btn.setEnabled(not reason)
        self.ok_btn.setToolTip(
            reason or "Run a calculation with the current input parameters"
        )

    def _load_input(self) -> None:
        if choose_and_load_input_parameters(self.session, self):
            self.tree_editor.set_show_changed_only(True)

    def _edit_input_file(self) -> None:
        if self._commit_pending():
            edit_input_parameters_file(self.session, self)

    def _save_input(self) -> None:
        if self._commit_pending():
            choose_and_save_input_parameters(
                self.session.result(), self, atoms=self.atoms, directory=self.directory,
                recent_files=self.recent_files,
            )

    def _commit_pending(self) -> bool:
        if self.dataset_editor is not None:
            self.dataset_editor.commit()
        if self.file_source_form is not None:
            for view in self.file_source_form.field_views:
                view.editor.commit()
            if self.file_source_form.errors:
                return False
        return self.tree_editor.commit_pending()

    def _refresh_preset_menus(self) -> None:
        preset_flows.populate_preset_menus(
            self.replace_preset_menu,
            self.merge_preset_menu,
            self.session,
            self,
            on_select=self._apply_preset,
        )
        self.load_preset_btn.setEnabled(self.replace_preset_menu.isEnabled())
        self.merge_preset_btn.setEnabled(self.merge_preset_menu.isEnabled())

    def _apply_preset(self, name: str, clear_first: bool) -> None:
        if self._commit_pending() and preset_flows.load_preset(
            self.session, self, name=name, clear_first=clear_first,
        ):
            self._refresh_preset_menus()

    def _save_preset(self) -> None:
        if self._commit_pending() and preset_flows.save_preset(self.session, self):
            self._refresh_preset_menus()

    def _on_ok(self) -> None:
        self._validation_error.hide()
        if not self._commit_pending():
            return
        try:
            validate_setup(self.session.working_parameters)
        except InputParametersValidationError as error:
            self._validation_error.setText(str(error))
            self._validation_error.show()
            return
        self._update_calculation_availability()
        if self._calculation_mode and not self.ok_btn.isEnabled():
            self._validation_error.setText(self.ok_btn.toolTip())
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
    directory: str | Path | None = None,
    recent_files: RecentFiles | None = None,
) -> InputParameters | None:
    """Open the expert editor and return its accepted isolated draft."""
    session = create_input_parameters_session(params)
    accepted = edit_input_parameters_session(
        session,
        parent=parent,
        show_changed_only=show_changed_only,
        atoms=atoms,
        directory=directory,
        recent_files=recent_files,
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
    directory: str | Path | None = None,
    recent_files: RecentFiles | None = None,
) -> InputParametersSession | None:
    """Run Expert over an isolated fork and return the fork only on Accept."""
    dialog = InputParametersDialog(
        session,
        parent=parent,
        show_changed_only=show_changed_only,
        atoms=atoms,
        directory=directory,
        recent_files=recent_files,
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
    directory: str | Path | None = None,
) -> InputParameters | None:
    """Create fresh parameters for a task and open the expert editor."""
    from importlib import import_module

    task_module = import_module(
        f'ase2sprkkr.input_parameters.definitions.{task.lower()}'
    )
    params_def = task_module.input_parameters()
    params = params_def.create_object()
    apply_default_dataset(params, dataset_default_mode, atoms)
    return edit_input_parameters(params, parent=parent, atoms=atoms, directory=directory)
