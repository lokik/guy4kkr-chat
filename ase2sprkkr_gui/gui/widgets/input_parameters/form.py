"""Render guided task specifications into cohesive page, group and field views."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.specs.schema import (
    FieldPlacement,
    FieldRole,
    GroupSpec,
    PageSpec,
    PresentationContext,
    TaskDialogSpec,
)
from ase2sprkkr_gui.gui.style import SPACE_MD, SPACE_SM, group_panel_stylesheet
from ase2sprkkr_gui.gui.widgets.input_parameters.parameter import EDITOR_WIDTH, ParameterEditor

LABEL_WIDTH = 245


@dataclass(eq=False)
class FieldView:
    """One rendered field and all widgets and state belonging to it."""

    placement: FieldPlacement
    editor: ParameterEditor
    label: QLabel
    page: PageView
    display_widgets: tuple[QWidget, ...]
    auxiliary_widgets: tuple[QWidget, ...] = ()
    detail_toggle: QToolButton | None = None

    @property
    def page_id(self) -> str:
        return self.page.spec.id

    def set_visible(self, visible: bool) -> None:
        for widget in self.display_widgets:
            widget.setVisible(visible)

    def set_enabled(self, enabled: bool, reason: str | None = None) -> None:
        self.editor.set_parameter_enabled(enabled, reason)
        self.label.setEnabled(enabled)
        for widget in self.auxiliary_widgets:
            widget.setEnabled(enabled)

    def set_label(self, text: str) -> None:
        self.label.setText(text)
        self.editor.setAccessibleName(text.rstrip(":"))

    def set_changed(self, changed: bool) -> None:
        font = self.label.font()
        font.setBold(changed)
        self.label.setFont(font)

    def update_tooltip(self, primary_title: str | None = None) -> None:
        tooltip = self.editor.toolTip()
        if primary_title:
            tooltip += f"\n\nPrimary location: {primary_title}"
        self.label.setToolTip(tooltip)

    def reveal(self, path: InputParameterPath, index: int | None) -> None:
        if self.detail_toggle is not None:
            self.detail_toggle.setChecked(True)
        content = self.page.scroll.widget()
        if content is not None and content.layout() is not None:
            content.layout().activate()
        self.page.scroll.ensureWidgetVisible(self.editor, 20, 30)
        self.editor.focus_for_history(path, index)

    def reveal_error(self) -> None:
        if self.detail_toggle is not None:
            self.detail_toggle.setChecked(True)
        self.page.scroll.ensureWidgetVisible(self.editor, 20, 30)
        self.editor.control.setFocus(Qt.FocusReason.OtherFocusReason)


@dataclass(eq=False)
class GroupView:
    """Rendered group with its fields, optional toggle and dynamic note."""

    spec: GroupSpec
    widget: QGroupBox
    fields: list[FieldView] = field(default_factory=list)
    toggle: QToolButton | None = None
    note: QLabel | None = None

    def apply_presentation(self, context: PresentationContext) -> None:
        visible = self.spec.visible_when(context) if self.spec.visible_when else True
        self.widget.setVisible(bool(visible))
        title = self.spec.title_when(context) if self.spec.title_when else self.spec.title
        if self.toggle is None:
            self.widget.setTitle(title)
        else:
            self.toggle.setText(title)
        if self.note is not None:
            text = self.spec.note_when(context) if self.spec.note_when else self.spec.note or ""
            self.note.setText(text)


@dataclass(eq=False)
class PageView:
    """Rendered page and its groups."""

    spec: PageSpec
    scroll: QScrollArea
    groups: list[GroupView] = field(default_factory=list)


class GuidedFormRenderer(QObject):
    """Own the anatomy, presentation state and validation state of a form."""

    statusChanged = pyqtSignal()

    def __init__(
        self,
        session: InputParametersSession,
        spec: TaskDialogSpec,
        pages: QStackedWidget,
        *,
        atoms: Any = None,
        select_page: Callable[[str], None],
    ) -> None:
        super().__init__(pages)
        self.session = session
        self.spec = spec
        self.pages_widget = pages
        self.atoms = atoms
        self._select_page = select_page
        self.primary_pages = spec.primary_pages()
        self._page_titles = {page.id: page.title for page in spec.pages}
        self.page_views: list[PageView] = []
        self.field_views: list[FieldView] = []
        self._views_by_path: dict[InputParameterPath, list[FieldView]] = defaultdict(list)
        self._views_by_editor: dict[ParameterEditor, FieldView] = {}
        self._group_notes: dict[str, QLabel] = {}
        self._editor_errors: dict[FieldView, str] = {}
        self._rule_errors: dict[tuple[InputParameterPath, int | None], str] = {}
        self._errors: dict[InputParameterPath, str] = {}

        self._validate_paths()
        for page in spec.pages:
            self._add_page(page)
        self.session.parametersReplaced.connect(self.apply_presentation)
        self.apply_presentation(emit=False)

    @property
    def errors(self) -> dict[InputParameterPath, str]:
        return dict(self._errors)

    def editors_for(self, path: InputParameterPath) -> tuple[ParameterEditor, ...]:
        return tuple(view.editor for view in self._views_by_path.get(path, ()))

    def views_for(self, path: InputParameterPath) -> tuple[FieldView, ...]:
        return tuple(self._views_by_path.get(path, ()))

    def view_for_editor(self, editor: ParameterEditor) -> FieldView:
        return self._views_by_editor[editor]

    def group_note(self, group_id: str) -> QLabel:
        return self._group_notes[group_id]

    def _validate_paths(self) -> None:
        """Reject specifications referring to options absent from the task."""
        for path in self.spec.all_paths():
            try:
                self.session.option(path)
            except (AttributeError, KeyError) as exc:
                raise ValueError(
                    "The guided-dialog specification refers to missing parameter "
                    f"{'.'.join(path)}."
                ) from exc

    def _add_page(self, spec: PageSpec) -> None:
        scroll = QScrollArea(self.pages_widget)
        scroll.setWidgetResizable(True)
        page = PageView(spec, scroll)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        layout.setSpacing(SPACE_MD)
        for group_spec in spec.groups:
            group = self._add_group(page, group_spec, content)
            page.groups.append(group)
            layout.addWidget(group.widget)
        layout.addStretch(1)
        scroll.setWidget(content)
        self.pages_widget.addWidget(scroll)
        self.page_views.append(page)

    def _add_group(
        self,
        page: PageView,
        spec: GroupSpec,
        parent: QWidget,
    ) -> GroupView:
        group_widget = QGroupBox("" if spec.collapsed else spec.title, parent)
        if spec.id:
            group_widget.setObjectName(spec.id)
        group_widget.setStyleSheet(
            group_panel_stylesheet(
                self.pages_widget.palette(), QColor(page.spec.color)
            )
        )
        group_layout = QVBoxLayout(group_widget)
        fields = QWidget(group_widget)
        grid = QGridLayout(fields)
        grid.setContentsMargins(0, 0, 0, 0)
        toggle = self._create_toggle(spec, group_widget, fields)
        if toggle is not None:
            group_layout.addWidget(toggle)
        group_layout.addWidget(fields)

        paired = spec.layout == "paired"
        grid.setColumnMinimumWidth(0, EDITOR_WIDTH if paired else LABEL_WIDTH)
        grid.setColumnMinimumWidth(1, EDITOR_WIDTH)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)
        grid.setHorizontalSpacing(SPACE_MD)
        grid.setVerticalSpacing(SPACE_SM)

        group = GroupView(spec, group_widget, toggle=toggle)
        for row, placement in enumerate(spec.fields):
            view = self._add_field(
                page,
                group,
                fields,
                grid,
                2 * (row // 2) if paired else row,
                placement,
                column=row % 2 if paired else None,
            )
            group.fields.append(view)

        if spec.note or spec.note_when:
            note = QLabel(spec.note or "", fields)
            note.setWordWrap(True)
            grid.addWidget(note, len(spec.fields), 0, 1, 3)
            group.note = note
            if spec.id:
                self._group_notes[spec.id] = note
        return group

    @staticmethod
    def _create_toggle(
        spec: GroupSpec,
        parent: QWidget,
        fields: QWidget,
    ) -> QToolButton | None:
        if not spec.collapsed:
            return None
        toggle = QToolButton(parent)
        toggle.setText(spec.title)
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.ArrowType.RightArrow)
        toggle.setAutoRaise(True)
        toggle.toggled.connect(fields.setVisible)
        toggle.toggled.connect(
            lambda checked: toggle.setArrowType(
                Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
            )
        )
        fields.hide()
        return toggle

    def _add_field(
        self,
        page: PageView,
        group: GroupView,
        parent: QWidget,
        grid: QGridLayout,
        row: int,
        placement: FieldPlacement,
        *,
        column: int | None,
    ) -> FieldView:
        editor = ParameterEditor(
            self.session,
            placement,
            page.spec.id,
            atoms=self.atoms,
            parent=parent,
        )
        label = QLabel(placement.label, parent)
        label.setFixedWidth(LABEL_WIDTH)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setToolTip(editor.toolTip())
        display_widgets: list[QWidget]
        auxiliary: list[QWidget] = []
        block_layout: QVBoxLayout | None = None

        if column is not None:
            label.setFixedWidth(EDITOR_WIDTH)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(label, row, column)
            grid.addWidget(editor, row + 1, column, alignment=Qt.AlignmentFlag.AlignTop)
            display_widgets = [label, editor]
        elif editor.full_width:
            block = QWidget(parent)
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            block_layout.addWidget(label)
            block_layout.addWidget(editor)
            grid.addWidget(block, row, 0, 1, 3)
            display_widgets = [block]
        else:
            grid.addWidget(label, row, 0)
            grid.addWidget(editor, row, 1)
            display_widgets = [label, editor]

        if placement.role is FieldRole.MIRROR:
            primary_id = self.primary_pages[placement.path]
            primary_title = self._page_titles[primary_id]
            link_color = self.pages_widget.palette().highlight().color().name()
            details = QLabel(
                f'<a style="color: {link_color};" href="{primary_id}">{primary_title}</a>',
                parent,
            )
            details.setTextFormat(Qt.TextFormat.RichText)
            details.setWordWrap(True)
            details.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            details.setOpenExternalLinks(False)
            details.setToolTip(f"Open the primary {primary_title} setting")
            details.linkActivated.connect(self._select_page)
            if block_layout is not None:
                block_layout.addWidget(details)
            else:
                grid.addWidget(
                    details,
                    row,
                    2,
                    alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
            auxiliary.append(details)
            if block_layout is None:
                display_widgets.append(details)

        view = FieldView(
            placement,
            editor,
            label,
            page,
            tuple(display_widgets),
            tuple(auxiliary),
            group.toggle,
        )
        editor.validationChanged.connect(
            lambda _path, _page_id, message, source=view:
            self._editor_validation_changed(source, message)
        )
        self.field_views.append(view)
        self._views_by_editor[editor] = view
        for path in placement.paths:
            self._views_by_path[path].append(view)
        view.update_tooltip(
            self._page_titles[self.primary_pages[placement.path]]
            if placement.role is FieldRole.MIRROR
            else None
        )
        return view

    def _editor_validation_changed(self, view: FieldView, message: str) -> None:
        if message:
            self._editor_errors[view] = message
        else:
            self._editor_errors.pop(view, None)
        self.apply_presentation()

    @staticmethod
    def _missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        try:
            return len(value) == 0
        except TypeError:
            return False

    def _placement_value(
        self,
        placement: FieldPlacement,
        path: InputParameterPath,
    ) -> Any:
        value = self.session.value(path)
        index = placement.index if path == placement.path else None
        if index is None:
            return value
        try:
            return value[index]
        except (IndexError, TypeError):
            return None

    def apply_presentation(self, *, emit: bool = True) -> None:
        """Apply rules to views without mutating parameters or undo history."""
        context = PresentationContext(self.session.working_parameters, self.atoms)
        rule_errors: dict[tuple[InputParameterPath, int | None], str] = {}
        for page in self.page_views:
            for group in page.groups:
                group.apply_presentation(context)

        for view in self.field_views:
            placement = view.placement
            visible = placement.visible_when(context) if placement.visible_when else True
            view.set_visible(bool(visible))
            enabled = placement.enabled_when(context) if placement.enabled_when else True
            reason = (
                placement.disabled_reason_when(context)
                if not enabled and placement.disabled_reason_when
                else None
            )
            view.set_enabled(bool(enabled), reason)
            label = placement.label_when(context) if placement.label_when else placement.label
            view.set_label(label)
            help_text = placement.tooltip_when(context) if placement.tooltip_when else ""
            view.editor.set_presentation_help(help_text)
            view.update_tooltip(
                self._page_titles[self.primary_pages[placement.path]]
                if placement.role is FieldRole.MIRROR
                else None
            )
            if placement.required_when and placement.required_when(context):
                for path in placement.paths:
                    if not self._missing(self._placement_value(placement, path)):
                        continue
                    message = placement.required_message
                    if callable(message):
                        message = message(context)
                    rule_errors[(
                        path,
                        placement.index if path == placement.path else None,
                    )] = message or (
                        f"{'.'.join(path)} is required for the selected settings."
                    )

        self._rule_errors = rule_errors
        errors: dict[InputParameterPath, str] = {}
        for view, message in self._editor_errors.items():
            if message:
                errors.setdefault(view.editor.path, message)
        for (path, _index), message in rule_errors.items():
            errors.setdefault(path, message)
        self._errors = errors
        if emit:
            self.statusChanged.emit()

    def update_changed(self, changed: set[InputParameterPath]) -> None:
        for view in self.field_views:
            view.set_changed(any(path in changed for path in view.placement.paths))

    def history_view(
        self,
        paths,
        source_page: str | None,
        field_indices,
    ) -> tuple[FieldView, InputParameterPath, int | None] | None:
        for path in paths:
            views = self._views_by_path.get(path, ())
            if not views:
                continue
            index = field_indices.get(path)
            matching = [view for view in views if view.placement.index == index]
            candidates = matching or list(views)
            view = next(
                (item for item in candidates if item.page_id == source_page),
                None,
            )
            if view is None:
                primary = self.primary_pages[path]
                view = next(
                    (item for item in candidates if item.page_id == primary),
                    candidates[0],
                )
            return view, path, index
        return None

    def error_view(self, path: InputParameterPath) -> FieldView:
        views = self._views_by_path[path]
        primary = self.primary_pages[path]
        return next(
            (view for view in views if view.page_id == primary),
            views[-1],
        )
