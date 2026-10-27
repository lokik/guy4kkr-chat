from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import (
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

from guy4ase.gui.application.result_action_policy import ResultActionAvailability
from guy4ase.gui.application.result_presentation import (
    ResultPresentation,
    ResultTreeModel,
    ResultTreeNode,
    ResultValuePresentation,
    present_result,
)
from guy4ase.gui.misc.resources import icon_path

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

    def __init__(
        self,
        action_handler: Callable[[Any, str], None],
        *,
        show_values_without_actions: bool,
        empty_text: str = "No result loaded.",
        show_history_button: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._action_handler = action_handler
        self._show_values_without_actions = show_values_without_actions
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
        layout.addWidget(self._selector)
        assignment_row = QHBoxLayout()
        self.select_all_button = QPushButton("Select all", self)
        self.select_all_button.clicked.connect(self._select_all_results)
        assignment_row.addWidget(self.select_all_button)
        self.assign_project_button = QPushButton("Assign to project…", self)
        self.assign_project_button.clicked.connect(self._request_project_assignment)
        assignment_row.addWidget(self.assign_project_button)
        assignment_row.addStretch(1)
        layout.addLayout(assignment_row)
        self._assignment_controls = (self.select_all_button, self.assign_project_button)
        self._update_assignment_controls()

        self._record_actions = QWidget(self)
        record_actions_layout = QHBoxLayout(self._record_actions)
        record_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._use_state_button = QPushButton("Use this potential", self._record_actions)
        self._use_state_button.clicked.connect(self._use_selected_state)
        record_actions_layout.addWidget(self._use_state_button)
        self._recompute_button = QPushButton("Recompute", self._record_actions)
        self._recompute_button.clicked.connect(self._recompute_selected)
        record_actions_layout.addWidget(self._recompute_button)
        record_actions_layout.addStretch(1)
        self._record_actions.hide()
        layout.addWidget(self._record_actions)

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
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(2, 1)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

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
        self._update_assignment_controls()
        self.set_result(model.selected)

    def set_result(self, presentation: ResultPresentation | Any | None) -> None:
        """Render one presentation; raw live results are delegated to the presenter."""
        if presentation is not None and not isinstance(presentation, ResultPresentation):
            presentation = present_result(presentation)

        self._clear()
        self._result_file_warning.hide()
        if presentation is None:
            self._record_actions.hide()
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
        self._use_state_button.setVisible(use_state is not None)
        if use_state is not None:
            self._use_state_button.setText(use_state.label)
        self._recompute_button.setVisible(recompute is not None)
        if recompute is not None:
            self._recompute_button.setText(recompute.label)
        self._record_actions.setVisible(use_state is not None or recompute is not None)

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
        self._scroll.hide()

    def _clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._row_count = 0
