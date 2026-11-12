"""Side-navigation guided editor for SPR-KKR input parameters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ase2sprkkr import InputParameters
from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
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

from guy4ase.gui.application.window_geometry import manage_window_geometry
from guy4ase.gui.dialogs.expert_input import edit_input_parameters_session
from guy4ase.gui.flows.input_parameters import (
    choose_and_load_input_parameters,
    edit_input_parameters_file,
)
from guy4ase.gui.input_parameters.bindings import InputParameterPath
from guy4ase.gui.input_parameters.session import create_input_parameters_session
from guy4ase.gui.input_parameters.specs.schema import (
    PageSpec,
    TaskDialogSpec,
)
from guy4ase.gui.input_parameters.tasks import guided_task_definition
from guy4ase.gui.input_parameters.validation import (
    InputParametersValidationError,
    validate_setup,
)
from guy4ase.gui.misc.resources import icon_path
from guy4ase.gui.style import (
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    button_stylesheet,
    heading_font,
    navigation_tile_stylesheet,
    secondary_text_stylesheet,
)
from guy4ase.gui.widgets.input_parameters.dataset import (
    DatasetEditor,
    apply_default_dataset,
)
from guy4ase.gui.widgets.input_parameters.form import GuidedFormRenderer
from guy4ase.gui.widgets.input_parameters.parameter import ParameterEditor
from guy4ase.physics.lattice import detect_structure_kind


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
    ) -> None:
        super().__init__(parent)
        self.task = task.lower()
        self.atoms = atoms
        definition = guided_task_definition(self.task)
        self._compatible_backend_tasks = definition.backend_tasks
        self.spec: TaskDialogSpec = definition.build_spec(
            is_2d=detect_structure_kind(atoms) == "2d",
        )
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

        self.setWindowTitle(self.spec.title)
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
        root.addWidget(title)
        intro = QLabel(self.spec.intro or (
            "Configure the most useful task parameters. Quick setup mirrors a small selection "
            "from the detailed categories; all remaining parameters are available in Expert settings."
        ))
        intro.setWordWrap(True)
        intro.setObjectName("guidedDialogSubtitle")
        intro.setStyleSheet(secondary_text_stylesheet(self.palette()))
        root.addWidget(intro)

        self.dataset_editor = DatasetEditor(self.session, self)
        root.addWidget(self.dataset_editor)

        body = QHBoxLayout()
        self.navigation = QListWidget(self)
        self.navigation.setObjectName("categoryNavigation")
        self.navigation.setMinimumWidth(220)
        self.navigation.setMaximumWidth(280)
        self.navigation.setSpacing(SPACE_SM)
        self.navigation.setStyleSheet(
            f"QListWidget {{ border: 0; padding: {SPACE_SM}px; background: palette(base); }}"
            "QListWidget::item { border: 0; }"
        )
        self.pages = QStackedWidget(self)
        body.addWidget(self.navigation)
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

        footer = QHBoxLayout()
        self.undo_button = QToolButton(self)
        self.undo_button.setText("Undo")
        self.undo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.undo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.undo_button.setStyleSheet(
            button_stylesheet(self.palette(), "QToolButton")
        )
        self.undo_button.clicked.connect(self.session.undo_stack.undo)
        footer.addWidget(self.undo_button)
        self.redo_button = QToolButton(self)
        self.redo_button.setText("Redo")
        self.redo_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.redo_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.redo_button.setStyleSheet(
            button_stylesheet(self.palette(), "QToolButton")
        )
        self.redo_button.clicked.connect(self.session.undo_stack.redo)
        footer.addWidget(self.redo_button)

        load = QPushButton("Load input…", self)
        load.setStyleSheet(button_stylesheet(self.palette()))
        load.clicked.connect(self._load_input)
        footer.addWidget(load)
        self.edit_input_button = QPushButton("Edit input file…", self)
        self.edit_input_button.setStyleSheet(button_stylesheet(self.palette()))
        self.edit_input_button.clicked.connect(self._edit_input_file)
        footer.addWidget(self.edit_input_button)
        expert = QPushButton("Expert settings…", self)
        expert.setStyleSheet(button_stylesheet(self.palette()))
        expert.clicked.connect(self._open_expert_settings)
        footer.addWidget(expert)
        footer.addStretch(1)

        self.previous_button = QPushButton("Previous", self)
        self.previous_button.setStyleSheet(button_stylesheet(self.palette()))
        self.previous_button.clicked.connect(lambda: self.navigation.setCurrentRow(self.navigation.currentRow() - 1))
        footer.addWidget(self.previous_button)
        self.next_button = QPushButton("Next", self)
        self.next_button.setStyleSheet(button_stylesheet(self.palette()))
        self.next_button.clicked.connect(lambda: self.navigation.setCurrentRow(self.navigation.currentRow() + 1))
        footer.addWidget(self.next_button)
        cancel = QPushButton("Cancel", self)
        cancel.setStyleSheet(button_stylesheet(self.palette()))
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        calculate = QPushButton("Calculate", self)
        calculate.setStyleSheet(button_stylesheet(self.palette(), primary=True))
        calculate.setDefault(True)
        calculate.setIcon(QIcon(str(icon_path("system-run.svg"))))
        calculate.clicked.connect(self._accept)
        footer.addWidget(calculate)
        root.addLayout(footer)

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
        self.dataset_editor.commit()
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
        if not self._commit_pending():
            QMessageBox.warning(self, "Invalid Settings", "Correct the highlighted value before calculating.")
            return
        try:
            validate_setup(self.session.working_parameters)
        except InputParametersValidationError as exc:
            self._show_model_error(exc)
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

    def parameters(self) -> InputParameters:
        """Return a detached copy of the currently edited parameters."""
        return self.session.result()


def select_guided_input_parameters(
    task: str,
    parent: QWidget | None = None,
    *,
    atoms: Any = None,
    dataset_default_mode: str,
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
    dialog = GuidedInputParametersDialog(
        task,
        parameters,
        parent=parent,
        atoms=atoms,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.parameters()