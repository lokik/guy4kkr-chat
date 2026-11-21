from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QAbstractItemView,
    QSizePolicy,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.result_action_policy import ResultActionAvailability
from ase2sprkkr_gui.gui.application.result_presentation import (
    ResultPresentation,
    ResultTreeModel,
    ResultTreeNode,
    ResultValuePresentation,
    present_result,
)
from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.widgets.centered_icon_buttons import CenteredIconPushButton

_PLOT_ICON = icon_path("labplot-xy-interpolation-curve.svg")
_STANDARD_ICONS = {
    "save": QStyle.StandardPixmap.SP_DialogSaveButton,
    "open": QStyle.StandardPixmap.SP_FileDialogContentsView,
    "open_directory": QStyle.StandardPixmap.SP_DirOpenIcon,
    "edit": QStyle.StandardPixmap.SP_FileDialogDetailedView,
    "data": QStyle.StandardPixmap.SP_FileDialogDetailedView,
}
_ACTION_LABELS = {
    "data": "View data",
    "open_directory": "Open containing directory",
}
_RESULT_ID_ROLE = int(Qt.ItemDataRole.UserRole)
_STRUCTURE_ID_ROLE = _RESULT_ID_ROLE + 1


def result_action_icon(style: QStyle, action: str) -> QIcon:
    if action == "plot":
        return QIcon(str(_PLOT_ICON))
    return style.standardIcon(
        _STANDARD_ICONS.get(action, QStyle.StandardPixmap.SP_FileIcon)
    )


def result_action_tooltip(value, action: str) -> str:
    return _action_tooltip(action, getattr(value, "info", ""))


def _action_tooltip(action: str, info: str) -> str:
    label = _ACTION_LABELS.get(action, action.replace("_", " ").capitalize())
    return f"{label} — {info}" if info else label


class ElidedValueLabel(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = text
        self.setToolTip(text)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self._update_text()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_text()

    def _update_text(self) -> None:
        width = max(0, self.contentsRect().width())
        self.setText(
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                width,
            )
        )


class _ResultTreeWidget(QTreeWidget):
    """Tree whose non-selectable structure headers still accept double-clicks."""

    structureDoubleClicked = pyqtSignal(int)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            structure_id = item.data(0, _STRUCTURE_ID_ROLE)
            if structure_id is not None:
                self.structureDoubleClicked.emit(int(structure_id))
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


class ResultActionsWidget(QWidget):
    """Render result presentation models and emit user intent."""

    useStateRequested = pyqtSignal(int)
    recomputeRequested = pyqtSignal(int)
    selectionRequested = pyqtSignal(int)
    newCalculationRequested = pyqtSignal(int)
    historyRequested = pyqtSignal()
    assignToProjectRequested = pyqtSignal(object)
    loadResultRequested = pyqtSignal()
    importDirectoryRequested = pyqtSignal()

    def __init__(
        self,
        action_handler: Callable[[Any, str], None],
        *,
        show_values_without_actions: bool,
        empty_text: str = "No result loaded.",
        show_history_button: bool = True,
        show_assignment_controls: bool = True,
        single_result: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._action_handler = action_handler
        self._show_values_without_actions = show_values_without_actions
        self._single_result = single_result
        self._current_presentation: ResultPresentation | None = None
        self._empty_text = empty_text
        self._row_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if show_history_button:
            self._history_button = QPushButton("Browse calculation jobs…", self)
            self._history_button.clicked.connect(
                lambda _checked=False: self.historyRequested.emit()
            )
            layout.addWidget(self._history_button)
        else:
            self._history_button = None

        self._selector = _ResultTreeWidget(self)
        self._selector.setHeaderHidden(True)
        self._selector.setToolTip("Select results (Ctrl/Shift for multiple selection)")
        self._selector.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._selector.currentItemChanged.connect(self._select_result)
        self._selector.structureDoubleClicked.connect(self.newCalculationRequested)
        self._selector.itemSelectionChanged.connect(self._update_assignment_controls)
        self._selector.hide()
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self._import_controls_layout = top_row
        self.select_all_button = QPushButton("Select All", self)
        self.select_all_button.setIcon(
            QIcon.fromTheme(
                "edit-select-all",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
            )
        )
        self.select_all_button.clicked.connect(self._select_all_results)
        self.assign_project_button = QPushButton("Assign to Project", self)
        self.assign_project_button.setToolTip("Assign selected results to a project")
        self.assign_project_button.setIcon(
            QIcon.fromTheme(
                "folder-move",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            )
        )
        self.assign_project_button.clicked.connect(self._request_project_assignment)
        self.load_result_button = CenteredIconPushButton("Load Result", self)
        self.load_result_button.setObjectName("resultsLoadButton")
        self.load_result_button.setToolTip(
            "Load one SPR-KKR output file into Results (Ctrl+Shift+O)"
        )
        self.load_result_button.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.load_result_button.setIcon(
            QIcon.fromTheme(
                "document-open",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            )
        )
        self.load_result_button.clicked.connect(
            lambda _checked=False: self.loadResultRequested.emit()
        )
        self.import_directory_button = CenteredIconPushButton("Import Directory…", self)
        self.import_directory_button.setObjectName("resultsImportDirectoryButton")
        self.import_directory_button.setIcon(
            QIcon.fromTheme(
                "folder-open",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            )
        )
        self.import_directory_button.setToolTip(
            "Import recognized SPR-KKR outputs from a directory (Ctrl+Shift+I)"
        )
        self.import_directory_button.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.import_directory_button.clicked.connect(
            lambda _checked=False: self.importDirectoryRequested.emit()
        )
        # Import controls can be moved to the WorkflowWindow header. In
        # stand-alone result browsers they remain here, above the tree.
        for button in (
            self.load_result_button, self.import_directory_button,
        ):
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            top_row.addWidget(button, 1)
        layout.addLayout(top_row)
        if single_result:
            self.load_result_button.hide()
            self.import_directory_button.hide()

        self.show_all_values_checkbox = QCheckBox("Show all values", self)
        self.show_all_values_checkbox.setObjectName("resultsShowAllValues")
        self.show_all_values_checkbox.setToolTip(
            "Also display output values with no available action"
        )
        self.show_all_values_checkbox.setChecked(show_values_without_actions)
        self.show_all_values_checkbox.toggled.connect(self._toggle_all_values)
        layout.addWidget(self._selector)
        self._assignment_controls = (self.select_all_button, self.assign_project_button)
        if not show_assignment_controls:
            for control in self._assignment_controls:
                control.hide()
        self._update_assignment_controls()

        self._record_actions = QWidget(self)
        record_actions_layout = QHBoxLayout(self._record_actions)
        record_actions_layout.setContentsMargins(0, 0, 0, 0)
        record_actions_layout.setSpacing(top_row.spacing())
        self._recompute_button = QPushButton("Recompute", self._record_actions)
        self._recompute_button.setIcon(
            QIcon.fromTheme(
                "view-refresh",
                self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
            )
        )
        self._recompute_button.clicked.connect(self._recompute_selected)
        self._recompute_button.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        record_actions_layout.addWidget(self._recompute_button, 1)
        # The middle slot mirrors Assign to Project in the selection row.
        record_actions_layout.addWidget(QWidget(self._record_actions), 1)
        values_slot = QWidget(self._record_actions)
        values_slot_layout = QHBoxLayout(values_slot)
        values_slot_layout.setContentsMargins(0, 0, 0, 0)
        values_slot_layout.addStretch(1)
        values_slot_layout.addWidget(
            self.show_all_values_checkbox,
            alignment=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )
        values_slot.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        record_actions_layout.addWidget(values_slot, 1)
        # Show all values is independent of whether Recompute is applicable,
        # but neither control is useful until a result is selected.
        self._recompute_button.setEnabled(False)
        self._record_actions.hide()

        self._result_file_warning = QLabel("", self)
        self._result_file_warning.setWordWrap(True)
        self._result_file_warning.hide()
        layout.addWidget(self._result_file_warning)

        self._empty_label = QLabel(empty_text, self)
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._container = QWidget(self._scroll)
        value_layout = QVBoxLayout(self._container)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(4)
        self._grid = QGridLayout()
        value_layout.addLayout(self._grid)
        self._record_actions.setParent(self._container)
        value_layout.addWidget(self._record_actions)
        value_layout.addStretch(1)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(2, 1)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        # Three equally wide selection controls immediately below the tree.
        self._bottom_controls = QWidget(self)
        bottom_row = QHBoxLayout(self._bottom_controls)
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(top_row.spacing())
        self._use_state_button = QPushButton("Use this structure", self)
        self._use_state_button.setIcon(
            QIcon.fromTheme(
                "dialog-ok-apply",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
            )
        )
        self._use_state_button.clicked.connect(self._use_selected_state)
        self._use_state_button.setEnabled(False)
        for button in (
            self._use_state_button, self.assign_project_button,
            self.select_all_button,
        ):
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            bottom_row.addWidget(button, 1)
        # Keep state/assignment controls directly below the result tree,
        # never below the selected result's potentially long values list.
        layout.insertWidget(layout.indexOf(self._selector) + 1, self._bottom_controls)
        self._bottom_controls.hide()

    def move_import_controls_to(self, target_layout: QHBoxLayout) -> None:
        """Move the existing import actions to a persistent header toolbar.

        Preserves signals, shortcuts, icons and tooltips instead of creating
        duplicate actions that could get out of sync.
        """
        for button in (self.load_result_button, self.import_directory_button):
            self._import_controls_layout.removeWidget(button)
            button.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            button.setFixedHeight(40)
            target_layout.addWidget(button)

    @property
    def has_rows(self) -> bool:
        return self._row_count > 0

    @property
    def selected_result_id(self) -> int | None:
        """Return the selected provenance result, if any."""
        item = self._selector.currentItem()
        if item is None:
            return None
        value = item.data(0, _RESULT_ID_ROLE)
        return int(value) if value is not None else None

    @property
    def selected_result_ids(self) -> tuple[int, ...]:
        """Selected results only, excluding grouping headers."""
        return tuple(sorted({int(value) for item in self._selector.selectedItems()
                            if (value := item.data(0, _RESULT_ID_ROLE)) is not None}))

    def _select_all_results(self) -> None:
        self._selector.selectAll()
        self._update_assignment_controls()

    def _request_project_assignment(self) -> None:
        selected = self.selected_result_ids
        if selected:
            self.assignToProjectRequested.emit(selected)

    def _update_assignment_controls(self) -> None:
        has_results = bool(self._selector.topLevelItemCount())
        self.select_all_button.setEnabled(has_results)
        self.assign_project_button.setEnabled(bool(self.selected_result_ids))

    def select_result(self, result_id: int) -> bool:
        """Select a result by provenance id if it is present in this projection."""
        item = self._find_result_item(result_id)
        if item is None:
            return False
        self._selector.setCurrentItem(item)
        self._update_assignment_controls()
        return True

    def set_model(self, model: ResultTreeModel) -> None:
        """Render a complete application-provided result selector model."""
        selected_ids = set(self.selected_result_ids)
        self._selector.blockSignals(True)
        try:
            self._selector.clear()
            for node in model.roots:
                self._selector.addTopLevelItem(self._tree_item(node))
            self._selector.expandAll()
            target = self._find_result_item(model.selected_result_id)
            if target is not None:
                self._selector.setCurrentItem(target)
            for result_id in selected_ids:
                item = self._find_result_item(result_id)
                if item is not None:
                    item.setSelected(True)
        finally:
            self._selector.blockSignals(False)

        self._selector.setVisible(bool(model.roots))
        self._bottom_controls.setVisible(bool(model.roots))
        self._update_assignment_controls()
        self.set_result(model.selected)

    def set_status(self, message: str) -> None:
        """Display non-blocking loading or error state instead of a result."""
        self.set_result(None)
        self._show_empty(message)

    def _toggle_all_values(self, checked: bool) -> None:
        """Re-render the selected result without changing selection or state."""
        self._show_values_without_actions = checked
        if self._current_presentation is not None:
            self.set_result(self._current_presentation)

    def set_result(self, presentation: ResultPresentation | Any | None) -> None:
        """Render one presentation; raw live results are delegated to the presenter."""
        if presentation is not None and not isinstance(presentation, ResultPresentation):
            presentation = present_result(presentation)
        self._current_presentation = presentation

        self._clear()
        self._result_file_warning.hide()
        if presentation is None:
            self._refresh_record_actions(ResultActionAvailability())
            self._show_empty(self._empty_text)
            return

        self._refresh_record_actions(presentation.actions)
        if presentation.file_warning:
            self._result_file_warning.setText(presentation.file_warning)
            self._result_file_warning.show()

        for value in presentation.values:
            if (
                not value.actions
                and not self._show_values_without_actions
                and not value.show_in_summary
                and not value.always_visible
            ):
                continue
            self._add_value(value)

        if self._row_count:
            self._empty_label.hide()
            self._scroll.show()
        else:
            self._show_empty("No actions available.")

    def _tree_item(self, node: ResultTreeNode) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node.label])
        if node.result_id is None:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        else:
            item.setData(0, _RESULT_ID_ROLE, node.result_id)
        if node.structure_id is not None:
            item.setData(0, _STRUCTURE_ID_ROLE, node.structure_id)
        for child in node.children:
            item.addChild(self._tree_item(child))
        return item

    def _find_result_item(self, result_id: int | None) -> QTreeWidgetItem | None:
        if result_id is None:
            return None
        root = self._selector.invisibleRootItem()
        stack = [root.child(i) for i in range(root.childCount())]
        while stack:
            item = stack.pop()
            if item.data(0, _RESULT_ID_ROLE) == result_id:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return None

    def _select_result(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        value = current.data(0, _RESULT_ID_ROLE)
        if value is not None:
            self.selectionRequested.emit(int(value))

    def _refresh_record_actions(self, actions: ResultActionAvailability) -> None:
        use_state = actions.use_state
        recompute = actions.recompute
        self._use_state_button.setEnabled(use_state is not None)
        self._use_state_button.setText(
            "Use current potential" if use_state and len(use_state.label) > 27
            else use_state.label if use_state else "Use this structure"
        )
        self._use_state_button.setToolTip(use_state.label if use_state else "")
        self._recompute_button.setEnabled(recompute is not None)
        self._recompute_button.setText("Recompute")
        self._recompute_button.setToolTip(recompute.label if recompute else "")
        self._record_actions.setVisible(
            self._current_presentation is not None and not self._single_result
        )

    def _use_selected_state(self) -> None:
        result_id = self.selected_result_id
        if result_id is not None:
            self.useStateRequested.emit(result_id)

    def _recompute_selected(self) -> None:
        result_id = self.selected_result_id
        if result_id is not None:
            self.recomputeRequested.emit(result_id)

    def _add_value(self, presentation: ResultValuePresentation) -> None:
        self._add_row(
            presentation.value,
            presentation.actions,
            name=presentation.name,
            info=presentation.info,
            summary=presentation.summary,
            warning=presentation.warning,
        )

    def _add_row(
        self,
        value: Any | None,
        actions: tuple[str, ...],
        *,
        name: str,
        info: str,
        summary: str,
        warning: str | None = None,
    ) -> None:
        row = self._row_count
        name_label = QLabel(name, self._container)
        name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        name_label.setWordWrap(True)
        tooltip = "\n\n".join(part for part in (info, warning) if part)
        if tooltip:
            name_label.setToolTip(tooltip)
        self._grid.addWidget(name_label, row, 0)

        buttons = QWidget(self._container)
        button_layout = QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(4)
        for action in actions:
            assert value is not None
            button = QToolButton(buttons)
            button.setAutoRaise(True)
            button.setIcon(result_action_icon(self.style(), action))
            action_tooltip = _action_tooltip(action, info)
            if warning:
                action_tooltip = "\n\n".join((action_tooltip, warning))
            button.setToolTip(action_tooltip)
            button.clicked.connect(
                lambda _checked=False, v=value, a=action: self._action_handler(v, a)
            )
            button_layout.addWidget(button)
        button_layout.addStretch(1)
        self._grid.addWidget(buttons, row, 1)

        summary_text = f"{summary} ⚠" if warning else summary
        summary_label = ElidedValueLabel(summary_text, self._container)
        if warning:
            summary_label.setToolTip(
                "\n\n".join(part for part in (summary, warning) if part)
            )
        self._grid.addWidget(summary_label, row, 2)
        self._row_count += 1

    def _show_empty(self, text: str) -> None:
        self._empty_label.setText(text)
        self._empty_label.show()
        # Keep the empty results viewport occupying its space so the
        # persistent selection controls stay at the bottom of the column.
        self._scroll.show()

    def _clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._row_count = 0
