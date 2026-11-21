"""Side-navigation guided editor for SPR-KKR input parameters."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ase2sprkkr import InputParameters
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.window_geometry import manage_window_geometry
from ase2sprkkr_gui.gui.dialogs.expert_input import edit_input_parameters_session
from ase2sprkkr_gui.gui.flows import presets as preset_flows
from ase2sprkkr_gui.gui.flows.input_parameters import (
    choose_and_load_input_parameters,
    choose_and_save_input_parameters,
    edit_input_parameters_file,
)
from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath
from ase2sprkkr_gui.gui.input_parameters.session import create_input_parameters_session
from ase2sprkkr_gui.gui.input_parameters.specs.schema import (
    PageSpec,
    TaskDialogSpec,
)
from ase2sprkkr_gui.gui.input_parameters.specs.shared import with_file_source_page
from ase2sprkkr_gui.gui.input_parameters.tasks import guided_task_definition
from ase2sprkkr_gui.gui.input_parameters.validation import (
    InputParametersValidationError,
    validate_setup,
)
from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.presentation import structure_kind_label
from ase2sprkkr_gui.gui.style import (
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    button_stylesheet,
    heading_font,
    navigation_tile_stylesheet,
    secondary_text_stylesheet,
)
from ase2sprkkr_gui.gui.widgets.input_parameters.dataset import apply_default_dataset
from ase2sprkkr_gui.gui.widgets.input_parameters.form import GuidedFormRenderer
from ase2sprkkr_gui.gui.widgets.input_parameters.parameter import ParameterEditor
from ase2sprkkr_gui.physics.lattice import detect_structure_kind


@dataclass(frozen=True)
class NavigationView:
    """Widgets and color belonging to one page in the dialog navigation."""

    item: QListWidgetItem
    label: QLabel
    accent: QColor


class GuidedTaskUnavailable(RuntimeError):
    """The selected backend task could not be materialized for Guided editing."""


class GuidedInputParametersDialog(QDialog):
    """A single guided dialog whose contents are supplied by a task spec."""

    def __init__(
        self,
        task: str,
        parameters: InputParameters,
        parent: QWidget | None = None,
        *,
        atoms: Any = None,
        calculation_unavailable_reason: Callable[[InputParameters], str | None] | None = None,
        file_source_directory=None,
        directory: str | Path | None = None,
        recent_files: RecentFiles | None = None,
        preset_save: Callable[[InputParameters], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.recent_files = recent_files
        self._preset_save = preset_save
        self._calculation_unavailable_reason = calculation_unavailable_reason
        self.task = task.lower()
        self.atoms = atoms
        self.directory = directory or file_source_directory
        definition = guided_task_definition(self.task)
        self._compatible_backend_tasks = definition.backend_tasks
        self.spec: TaskDialogSpec = definition.build_spec(
            is_2d=detect_structure_kind(atoms) == "2d",
        )
        if file_source_directory is not None:
            self.spec = with_file_source_page(self.spec, file_source_directory)
        expected_task = InputParameters.is_task_name(
            definition.backend_task
        )
        actual_task = InputParameters.is_task_name(
            parameters.task_name
        )
        if (
            not expected_task
            or not actual_task
            or not definition.accepts_backend_task(actual_task)
        ):
            expected = "/".join(task.upper() for task in definition.backend_tasks)
            raise ValueError(
                f"Expected {expected} input parameters, got "
                f"{actual_task or str(parameters.task_name).upper()}."
            )
        self.session = create_input_parameters_session(parameters, self)
        self._page_indexes = {page.id: index for index, page in enumerate(self.spec.pages)}
        self._navigation: dict[str, NavigationView] = {}
        self._pending_history_navigation = None
        self._history_navigation_timer = QTimer(self)
        self._history_navigation_timer.setSingleShot(True)
        self._history_navigation_timer.timeout.connect(
            self._apply_pending_history_navigation
        )

        self.setWindowTitle(
            f"Save preset · {self.spec.title}" if preset_save is not None
            else self.spec.title
        )
        manage_window_geometry(
            self, "guided-input", default_size=(1180, 740)
        )
        self._build_ui()
        self._connect_session()
        self._update_all_statuses()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_MD)
        root.setSpacing(SPACE_MD)
        title = QLabel(self.spec.title, self)
        title.setObjectName("guidedDialogTitle")
        title.setFont(heading_font(title.font(), "dialog"))
        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addStretch(1)

        # Editing history is a global dialog action, not a page-navigation
        # action. Keep it at the top right, away from file/run controls.
        self.undo_button = QToolButton(self)
        self.undo_button.setText("Undo")
        self.undo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.undo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.undo_button.setStyleSheet(
            button_stylesheet(self.palette(), "QToolButton")
        )
        self.undo_button.clicked.connect(self.session.undo_stack.undo)
        title_row.addWidget(self.undo_button)
        self.redo_button = QToolButton(self)
        self.redo_button.setText("Redo")
        self.redo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.redo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.redo_button.setStyleSheet(
            button_stylesheet(self.palette(), "QToolButton")
        )
        self.redo_button.clicked.connect(self.session.undo_stack.redo)
        title_row.addWidget(self.redo_button)
        root.addLayout(title_row)
        kind_label = structure_kind_label(detect_structure_kind(self.atoms))
        if kind_label is not None:
            self.structure_type_label = QLabel(f"Structure type: {kind_label}", self)
            self.structure_type_label.setObjectName("guidedStructureType")
            self.structure_type_label.setStyleSheet(
                secondary_text_stylesheet(self.palette())
            )
            root.addWidget(self.structure_type_label)
        else:
            self.structure_type_label = None
        intro = QLabel(self.spec.intro or (
            "Configure the most useful task parameters. Quick setup mirrors a small selection "
            "from the detailed categories; all remaining parameters are available in Expert settings."
        ))
        intro.setWordWrap(True)
        intro.setObjectName("guidedDialogSubtitle")
        intro.setStyleSheet(secondary_text_stylesheet(self.palette()))
        root.addWidget(intro)

        body = QHBoxLayout()
        self.navigation = QListWidget(self)
        self.navigation.setObjectName("categoryNavigation")
        self.navigation.setMinimumWidth(220)
        self.navigation.setMaximumWidth(280)
        self.navigation.setSpacing(SPACE_SM)
        self.navigation.setStyleSheet(
            # The page QLabel already draws the selected 3px accent border.
            # Suppress only the list view's own focus outline and the native
            # row highlight, which otherwise protrude beyond the tile.
            f"QListWidget {{ border: 0; outline: 0; padding: {SPACE_SM}px; background: palette(base); }}"
            "QListWidget::item { border: 0; }"
            "QListWidget::item:selected, QListWidget::item:hover { background: transparent; }"
        )
        self.pages = QStackedWidget(self)

        # Page navigation belongs to the Pages column, not to global actions.
        navigation_column = QVBoxLayout()
        navigation_column.setContentsMargins(0, 0, 0, 0)
        navigation_column.setSpacing(SPACE_SM)
        navigation_column.addWidget(self.navigation, 1)
        page_buttons = QHBoxLayout()
        self.previous_button = QPushButton("Previous", self)
        self.previous_button.setObjectName("guidedPreviousPage")
        self.previous_button.setStyleSheet(button_stylesheet(self.palette()))
        self.previous_button.setIcon(QIcon.fromTheme(
            "go-previous", self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack)
        ))
        self.previous_button.clicked.connect(
            lambda: self.navigation.setCurrentRow(self.navigation.currentRow() - 1)
        )
        page_buttons.addWidget(self.previous_button, 1)
        self.next_button = QPushButton("Next", self)
        self.next_button.setObjectName("guidedNextPage")
        self.next_button.setStyleSheet(button_stylesheet(self.palette()))
        self.next_button.setIcon(QIcon.fromTheme(
            "go-next", self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward)
        ))
        self.next_button.clicked.connect(
            lambda: self.navigation.setCurrentRow(self.navigation.currentRow() + 1)
        )
        page_buttons.addWidget(self.next_button, 1)
        navigation_column.addLayout(page_buttons)
        body.addLayout(navigation_column)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        self.form = GuidedFormRenderer(
            self.session,
            self.spec,
            self.pages,
            atoms=self.atoms,
            select_page=self.select_page,
        )
        for page in self.spec.pages:
            self._add_navigation_page(page)
        self.form.statusChanged.connect(self._update_all_statuses)
        self.navigation.currentRowChanged.connect(self._select_page_index)

        file_actions = QHBoxLayout()
        load = QPushButton("Load input…", self)
        load.setObjectName("guidedLoadInput")
        load.setIcon(QIcon.fromTheme(
            "document-open", self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        ))
        load.setStyleSheet(button_stylesheet(self.palette()))
        load.clicked.connect(self._load_input)
        file_actions.addWidget(load)
        self.save_input_button = QPushButton("Save Input…", self)
        self.save_input_button.setObjectName("guidedSaveInput")
        self.save_input_button.setIcon(QIcon.fromTheme(
            "document-save", self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        ))
        self.save_input_button.setStyleSheet(button_stylesheet(self.palette()))
        self.save_input_button.setToolTip("Save the edited SPR-KKR input file without starting a calculation")
        self.save_input_button.clicked.connect(self._save_input)
        file_actions.addWidget(self.save_input_button)
        self.presets_btn = QPushButton("Presets…", self)
        self.presets_btn.setIcon(QIcon.fromTheme(
            "document-properties", self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        ))
        self.presets_btn.setStyleSheet(button_stylesheet(self.palette()))
        self.presets_menu = QMenu(self.presets_btn)
        self.replace_preset_menu = self.presets_menu.addMenu("Replace by preset")
        self.merge_preset_menu = self.presets_menu.addMenu("Load preset")
        save_preset_action = self.presets_menu.addAction("Save as preset…", self._save_preset)
        save_preset_action.setVisible(self._preset_save is None)
        self.presets_menu.aboutToShow.connect(self._refresh_preset_menus)
        self.presets_btn.setMenu(self.presets_menu)
        self._refresh_preset_menus()
        file_actions.addWidget(self.presets_btn)
        self.edit_input_button = QPushButton("Edit input file…", self)
        self.edit_input_button.setIcon(QIcon.fromTheme(
            "document-edit", self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        ))
        self.edit_input_button.setStyleSheet(button_stylesheet(self.palette()))
        self.edit_input_button.clicked.connect(self._edit_input_file)
        file_actions.addWidget(self.edit_input_button)
        expert = QPushButton("Expert settings…", self)
        expert.setObjectName("guidedExpertSettings")
        expert.setIcon(QIcon.fromTheme(
            "preferences-system", self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        ))
        expert.setStyleSheet(button_stylesheet(self.palette()))
        expert.clicked.connect(self._open_expert_settings)
        file_actions.addWidget(expert)
        file_actions.addStretch(1)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName("guidedCancel")
        self.cancel_button.setIcon(QIcon.fromTheme(
            "dialog-cancel", self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
        ))
        self.cancel_button.setStyleSheet(button_stylesheet(self.palette()))
        self.cancel_button.clicked.connect(self.reject)
        file_actions.addWidget(self.cancel_button)
        self.calculate_button = QPushButton(
            "Save" if self._preset_save is not None else "Calculate", self
        )
        self.calculate_button.setObjectName(
            "guidedSavePreset" if self._preset_save is not None else "guidedCalculate"
        )
        self.calculate_button.setStyleSheet(button_stylesheet(self.palette(), primary=True))
        self.calculate_button.setDefault(True)
        self.calculate_button.setIcon(
            QIcon.fromTheme("document-save", self.style().standardIcon(
                QStyle.StandardPixmap.SP_DialogSaveButton
            )) if self._preset_save is not None
            else QIcon(str(icon_path("system-run.svg")))
        )
        self.calculate_button.clicked.connect(self._accept)
        file_actions.addWidget(self.calculate_button)
        root.addLayout(file_actions)

        self.navigation.setCurrentRow(0)

    def _add_navigation_page(self, page: PageSpec) -> None:
        item = QListWidgetItem(page.title)
        item.setData(Qt.ItemDataRole.UserRole, page.id)
        item.setSizeHint(QSize(0, 46))
        accent = QColor(page.color)
        label = QLabel(page.title, self.navigation)
        label.setContentsMargins(SPACE_MD, 0, SPACE_SM, 0)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        font = label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        label.setFont(font)
        self.navigation.addItem(item)
        self.navigation.setItemWidget(item, label)
        self._navigation[page.id] = NavigationView(item, label, accent)

    def _connect_session(self) -> None:
        stack = self.session.undo_stack
        stack.canUndoChanged.connect(self._update_history_buttons)
        stack.canRedoChanged.connect(self._update_history_buttons)
        stack.undoTextChanged.connect(self._update_history_buttons)
        stack.redoTextChanged.connect(self._update_history_buttons)
        stack.indexChanged.connect(self._update_history_buttons)
        self.session.historyApplied.connect(self._history_applied)
        self.session.valueChanged.connect(self._update_calculation_availability)
        self.session.parametersReplaced.connect(self._update_calculation_availability)

    def _history_applied(self, paths, source_page, field_indices) -> None:
        """Defer history navigation until restoring the undo command has finished."""
        # A dialog-owned timer is essential here. Static QTimer.singleShot keeps
        # its Python callback alive after the dialog's C++ object is destroyed;
        # the next event-loop iteration can then invoke a stale wrapper.
        self._pending_history_navigation = (
            tuple(paths),
            source_page,
            dict(field_indices),
        )
        self._history_navigation_timer.start(0)

    def _apply_pending_history_navigation(self) -> None:
        pending = self._pending_history_navigation
        self._pending_history_navigation = None
        if pending is not None:
            self._reveal_history_field(*pending)

    def _reveal_history_field(self, paths, source_page, field_indices) -> None:
        """Reveal the source-page editor if available, otherwise its primary placement."""
        result = self.form.history_view(paths, source_page, field_indices)
        if result is None:
            return
        view, path, index = result
        self.select_page(view.page_id)
        view.reveal(path, index)

    def _update_history_buttons(self, *_args: Any) -> None:
        stack = self.session.undo_stack
        self.undo_button.setEnabled(stack.canUndo())
        self.redo_button.setEnabled(stack.canRedo())
        self.undo_button.setToolTip(self.session.history_description(undo=True))
        self.redo_button.setToolTip(self.session.history_description(undo=False))

    def _update_all_statuses(self) -> None:
        changed = self.session.changed_paths(self.spec.all_paths())
        self.form.update_changed(changed)
        errors = self.form.errors

        for page in self.spec.pages:
            if page.quick:
                suffix = f"  ({len(changed)} changed)" if changed else ""
                if errors:
                    suffix += f"  ⚠ {len(errors)}"
            else:
                page_changed = any(
                    path in changed and self.form.primary_pages.get(path) == page.id
                    for path in self.form.primary_pages
                )
                page_errors = sum(
                    1 for path in errors if self.form.primary_pages.get(path) == page.id
                )
                suffix = "  •" if page_changed else ""
                if page_errors:
                    suffix += f"  ⚠ {page_errors}"
            text = page.title + suffix
            navigation = self._navigation[page.id]
            navigation.item.setText(text)
            navigation.label.setText(text)
        self._update_history_buttons()
        self._update_calculation_availability()

    def _update_calculation_availability(self, *_args: Any) -> None:
        """Explain why the edited input cannot currently be submitted.

        A standalone input-file entry point can supply additional constraints
        (e.g. executable/task compatibility or missing required calculation state)
        without teaching this editor about the workspace or run controller.
        """
        parameters = self.session.working_parameters
        actual_task = InputParameters.is_task_name(parameters.task_name)
        definition = guided_task_definition(self.task)
        if not actual_task or not definition.accepts_backend_task(actual_task):
            expected = "/".join(name.upper() for name in self._compatible_backend_tasks)
            reason = (
                f"This editor accepts {expected} input, not "
                f"{parameters.task_name or 'an unknown task'}."
            )
        elif self.form.errors:
            reason = (
                "Correct the highlighted input values before saving."
                if self._preset_save is not None else
                "Correct the highlighted input values before calculating."
            )
        elif self._preset_save is not None:
            # A reusable preset needs valid fields, not an executable calculation.
            reason = None
        else:
            try:
                validate_setup(parameters)
            except InputParametersValidationError as error:
                reason = f"Invalid calculation input: {error}"
            else:
                reason = (
                    self._calculation_unavailable_reason(parameters)
                    if self._calculation_unavailable_reason is not None
                    else None
                )
        self.calculate_button.setEnabled(not reason)
        self.calculate_button.setToolTip(
            reason or (
                "Save these input parameters as a new preset"
                if self._preset_save is not None
                else "Run a calculation with the edited SPR-KKR input"
            )
        )

    def group_note(self, group_id: str) -> QLabel:
        """Return a group's note widget for UI tests and accessibility checks."""
        return self.form.group_note(group_id)

    def _select_page_index(self, index: int) -> None:
        if 0 <= index < self.pages.count():
            self.pages.setCurrentIndex(index)
        self._update_navigation_styles()
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(0 <= index < self.pages.count() - 1)

    def select_page(self, page_id: str) -> None:
        self.navigation.setCurrentRow(self._page_indexes[page_id])

    def _update_navigation_styles(self) -> None:
        selected = self.navigation.currentRow()
        for page_id, navigation in self._navigation.items():
            active = self._page_indexes[page_id] == selected
            navigation.label.setStyleSheet(
                navigation_tile_stylesheet(
                    self.palette(), navigation.accent, selected=active
                )
            )

    def editors_for(self, path: InputParameterPath) -> tuple[ParameterEditor, ...]:
        return self.form.editors_for(path)

    def _commit_pending(self) -> bool:
        """Synchronously commit editor drafts and reveal tracked errors."""
        for view in self.form.field_views:
            view.editor.commit()

        errors = self.form.errors
        if errors:
            path = next(iter(errors))
            view = self.form.error_view(path)
            self.select_page(view.page_id)
            view.reveal_error()
            return False
        return True

    def _accept(self) -> None:
        if self._preset_save is not None:
            if not self._commit_pending():
                QMessageBox.warning(
                    self, "Invalid Settings", "Correct the highlighted value before saving."
                )
                return
            self._update_calculation_availability()
            if not self.calculate_button.isEnabled():
                QMessageBox.information(
                    self, "Cannot Save Preset", self.calculate_button.toolTip()
                )
                return
            if self._preset_save(self.parameters()):
                self.accept()
            return
        if not self._commit_pending():
            QMessageBox.warning(self, "Invalid Settings", "Correct the highlighted value before calculating.")
            return
        try:
            validate_setup(self.session.working_parameters)
        except InputParametersValidationError as exc:
            self._show_model_error(exc)
            return
        self._update_calculation_availability()
        if not self.calculate_button.isEnabled():
            QMessageBox.information(
                self, "Cannot Calculate", self.calculate_button.toolTip()
            )
            return
        self.accept()

    def _show_model_error(self, exception: InputParametersValidationError) -> None:
        if exception.path is not None:
            page_id = self.form.primary_pages.get(exception.path)
            if page_id is not None:
                self.select_page(page_id)
        QMessageBox.critical(self, "Invalid Settings", str(exception))

    def _open_expert_settings(self) -> None:
        """Edit an isolated Expert draft and import it as one undoable change."""
        if not self._commit_pending():
            return
        accepted = edit_input_parameters_session(
            self.session,
            parent=self,
            show_changed_only=False,
            atoms=self.atoms,
            directory=self.directory,
            recent_files=self.recent_files,
            allow_incomplete=self._preset_save is not None,
        )
        if accepted is None:
            return
        self.session.replace_from_session(
            accepted,
            text="Apply expert settings",
            source_page="expert",
        )

    def _load_input(self) -> None:
        choose_and_load_input_parameters(
            self.session,
            self,
            compatible_tasks=self._compatible_backend_tasks,
        )

    def _edit_input_file(self) -> None:
        if not self._commit_pending():
            return
        edit_input_parameters_file(self.session, self)

    def _refresh_preset_menus(self) -> None:
        preset_flows.populate_preset_menus(
            self.replace_preset_menu,
            self.merge_preset_menu,
            self.session,
            self,
            on_select=self._apply_preset,
            compatible_tasks=self._compatible_backend_tasks,
        )

    def _apply_preset(self, name: str, clear_first: bool) -> None:
        if self._commit_pending() and preset_flows.load_preset(
            self.session, self, name=name, clear_first=clear_first,
            compatible_tasks=self._compatible_backend_tasks,
        ):
            self._refresh_preset_menus()

    def _save_preset(self) -> None:
        if self._commit_pending() and preset_flows.save_preset(self.session, self):
            self._refresh_preset_menus()

    def _save_input(self) -> None:
        """Save the current isolated draft without accepting the calculation."""
        if not self._commit_pending():
            QMessageBox.warning(
                self, "Cannot Save Input", "Correct the highlighted input value before saving."
            )
            return
        choose_and_save_input_parameters(
            self.session.result(), self, atoms=self.atoms, directory=self.directory,
            recent_files=self.recent_files,
        )

    def parameters(self) -> InputParameters:
        """Return a detached copy of the currently edited parameters."""
        return self.session.result()


def select_guided_input_parameters(
    task: str,
    parent: QWidget | None = None,
    *,
    atoms: Any = None,
    dataset_default_mode: str,
    dataset_prefix: str | None = None,
    calculation_unavailable_reason: Callable[[InputParameters], str | None] | None = None,
    directory: str | Path | None = None,
    recent_files: RecentFiles | None = None,
) -> InputParameters | None:
    definition = guided_task_definition(task)
    if not InputParameters.is_task_name(definition.backend_task):
        raise GuidedTaskUnavailable(
            f"The {task.upper()} backend task is not available."
        )
    try:
        parameters = InputParameters.create(definition.backend_task)
    except ImportError as exc:
        raise GuidedTaskUnavailable(
            f"The {task.upper()} backend task could not be loaded: {exc}"
        ) from exc
    apply_default_dataset(parameters, dataset_default_mode, atoms)
    # Prefix only the suggested default, before the dialog. User edits in
    # the dialog must be respected verbatim.
    if dataset_prefix:
        value = parameters.CONTROL.DATASET()
        if value and not str(value).startswith(dataset_prefix):
            parameters.CONTROL.DATASET.set(f"{dataset_prefix}{value}")
    dialog = GuidedInputParametersDialog(
        task,
        parameters,
        parent=parent,
        atoms=atoms,
        calculation_unavailable_reason=calculation_unavailable_reason,
        directory=directory,
        recent_files=recent_files,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.parameters()
