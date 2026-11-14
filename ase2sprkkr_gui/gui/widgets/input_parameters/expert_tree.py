"""Searchable Expert input-parameter tree widget."""
from __future__ import annotations

from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath, resolve_option
from ase2sprkkr_gui.gui.input_parameters.expert_fields import applicable_expert_fields
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_renderer import (
    ExpertTreeRenderer,
    ExpertTreeRole,
)
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_runtime import ExpertTreeRuntime
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import ParameterValueEditor


class ExpertInputTreeEditor(QWidget):
    """Coordinate the Expert tree presentation around a shared parameter session."""

    validationChanged = pyqtSignal(bool)

    def __init__(
        self,
        session: InputParametersSession,
        *,
        atoms: Any = None,
        show_changed_only: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel("Search:"))
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter by name…")
        header.addWidget(self.filter_edit, 1)
        clear_button = QPushButton("Clear", self)
        header.addWidget(clear_button)
        self.changed_only_checkbox = QCheckBox("Show changed only", self)
        header.addWidget(self.changed_only_checkbox)
        header.addStretch(1)
        expand_button = QPushButton("Expand all", self)
        collapse_button = QPushButton("Collapse all", self)
        header.addWidget(expand_button)
        header.addWidget(collapse_button)
        layout.addLayout(header)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Name", "Type", "Value", "", "Comment"])
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setColumnWidth(0, 300)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tree, 1)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self._runtime = ExpertTreeRuntime(
            self.tree,
            errors_changed=self._show_editor_errors,
        )
        self._renderer = ExpertTreeRenderer(
            self.tree,
            self.session,
            self._runtime,
            atoms=atoms,
            parent=self,
        )

        self._pending_session_paths: dict[InputParameterPath, None] = {}
        self._session_update_timer = QTimer(self)
        self._session_update_timer.setSingleShot(True)
        self._session_update_timer.timeout.connect(self._flush_session_changes)

        self._pending_append_focus: tuple[
            InputParameterPath, tuple[int, ...]
        ] | None = None
        self._append_focus_timer = QTimer(self)
        self._append_focus_timer.setSingleShot(True)
        self._append_focus_timer.timeout.connect(self._restore_pending_append_focus)

        self.filter_edit.textChanged.connect(self.apply_filter)
        clear_button.clicked.connect(self.clear_filter)
        self.changed_only_checkbox.toggled.connect(
            lambda _checked: self.apply_filter(self.filter_edit.text())
        )
        expand_button.clicked.connect(self.tree.expandAll)
        collapse_button.clicked.connect(self.tree.collapseAll)
        self.changed_only_checkbox.setChecked(show_changed_only)
        self.session.editApplied.connect(self._session_changed)
        self.rebuild()

    @property
    def parameters(self) -> Any:
        return self.session.working_parameters

    @property
    def has_errors(self) -> bool:
        return self._runtime.has_errors

    @property
    def error_text(self) -> str:
        return self.error_label.text()

    def option_item(self, path: InputParameterPath) -> QTreeWidgetItem | None:
        """Return the rendered item for one option path, if present."""
        return self._runtime.option_item(path)

    def set_show_changed_only(self, enabled: bool) -> None:
        self.changed_only_checkbox.setChecked(enabled)

    def clear_filter(self) -> None:
        self.filter_edit.clear()
        self.filter_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def apply_filter(self, text: str) -> None:
        needle = (text or "").strip().lower()
        changed_only = self.changed_only_checkbox.isChecked()

        def visit(item: QTreeWidgetItem) -> bool:
            matches = not needle or needle in (item.text(0) or "").lower()
            changed = bool(item.data(0, ExpertTreeRole.CHANGED))
            child_visible = any(visit(item.child(i)) for i in range(item.childCount()))
            visible = (matches and (not changed_only or changed or child_visible)) or child_visible
            item.setHidden(not visible)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def commit_pending(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is not None:
            focus.clearFocus()
        for item, editor in self._editor_widgets():
            if editor is None or sip.isdeleted(editor) or sip.isdeleted(item):
                continue
            if not editor.commit():
                self.filter_edit.clear()
                self.changed_only_checkbox.setChecked(False)
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.scrollToItem(item)
                editor.setFocus()
                return False
        return not self.has_errors

    def rebuild(self) -> None:
        self._runtime.clear()
        self._field_specs = applicable_expert_fields(self.parameters)
        self._suppressed_paths = frozenset(
            path for spec in self._field_specs.values() for path in spec.related_paths
        )
        self.tree.clear()
        self._renderer.build(self._field_specs, self._suppressed_paths)
        for path, item in self._runtime.option_items():
            self._update_changed_style(
                resolve_option(self.parameters, path),
                item,
                refresh_filter=False,
            )
        self.tree.expandAll()
        self._collapse_groups()
        self.apply_filter(self.filter_edit.text())

    def _session_changed(self, paths, reset: bool) -> None:
        if reset:
            self._session_update_timer.stop()
            self._pending_session_paths.clear()
            self._append_focus_timer.stop()
            self._pending_append_focus = None
            self.rebuild()
            return
        for path in paths:
            self._pending_session_paths[path] = None
        if self._pending_session_paths:
            self._session_update_timer.start(0)

    def _flush_session_changes(self) -> None:
        changed_paths = tuple(self._pending_session_paths)
        self._pending_session_paths.clear()
        if changed_paths:
            self._apply_session_changes(changed_paths)

    def _apply_session_changes(self, changed_paths: tuple[InputParameterPath, ...]) -> None:
        refreshed: set[int] = set()
        for path in changed_paths:
            item = self._runtime.option_item(path)
            if item is None:
                continue
            option = resolve_option(self.parameters, path)
            shape = self._renderer.option_shape(option, self._field_specs.get(path))
            old_shape = self._runtime.option_shape(path)
            if shape != old_shape or (old_shape is not None and old_shape.contains_draft):
                append_container = self._focused_append_container_path(item)
                self._renderer.render_option(
                    option,
                    path,
                    item.parent(),
                    item,
                    self._field_specs.get(path),
                )
                self._collapse_groups(item)
                if append_container is not None:
                    self._pending_append_focus = (path, append_container)
                    self._append_focus_timer.start(0)
            else:
                self._refresh_subtree(item, refreshed)
            self._update_changed_style(option, item, refresh_filter=False)

        for registration in self._runtime.editors_depending_on(
            changed_paths,
            exclude_ids=refreshed,
        ):
            editor = registration.editor
            item = registration.item
            editor.refresh()
            self._renderer.apply_placement_presentation(editor, registration.placement)
            refreshed.add(id(editor))
            path = self._runtime.option_path_for_item(item)
            if path:
                try:
                    option = resolve_option(self.parameters, path)
                except (AttributeError, KeyError):
                    continue
                self._update_changed_style(
                    option,
                    item,
                    refresh_filter=False,
                )
        self.apply_filter(self.filter_edit.text())

    def _restore_pending_append_focus(self) -> None:
        pending = self._pending_append_focus
        self._pending_append_focus = None
        if pending is None:
            return
        path, container_path = pending
        item = self._runtime.option_item(path)
        if item is not None:
            self._focus_append_editor(item, container_path)

    def _refresh_subtree(self, item: QTreeWidgetItem, refreshed: set[int]) -> None:
        editor = self.tree.itemWidget(item, 2)
        if isinstance(editor, ParameterValueEditor) and id(editor) not in refreshed:
            editor.refresh()
            refreshed.add(id(editor))
        for index in range(item.childCount()):
            self._refresh_subtree(item.child(index), refreshed)

    def _focused_append_container_path(
        self,
        option_item: QTreeWidgetItem,
    ) -> tuple[int, ...] | None:
        focus = QApplication.focusWidget()
        if focus is None:
            return None
        for item, editor in self._editor_widgets():
            if editor is None or sip.isdeleted(editor):
                continue
            if editor is not focus and not editor.isAncestorOf(focus):
                continue
            current = item
            while current is not None and current is not option_item:
                if current.data(0, ExpertTreeRole.APPEND):
                    container = current.parent()
                    path = []
                    while container is not None and container is not option_item:
                        parent = container.parent()
                        if parent is None:
                            return None
                        path.append(parent.indexOfChild(container))
                        container = parent
                    return tuple(reversed(path)) if container is option_item else None
                current = current.parent()
            return None
        return None

    def _focus_append_editor(
        self,
        option_item: QTreeWidgetItem,
        container_path: tuple[int, ...],
    ) -> None:
        container = option_item
        for index in container_path:
            if index < 0 or index >= container.childCount():
                return
            container = container.child(index)
        append_item = next(
            (
                container.child(index)
                for index in range(container.childCount())
                if container.child(index).data(0, ExpertTreeRole.APPEND)
            ),
            None,
        )
        if append_item is None:
            return

        def first_editor(item: QTreeWidgetItem):
            for index in range(item.childCount()):
                editor = first_editor(item.child(index))
                if editor is not None:
                    return editor
            editor = self.tree.itemWidget(item, 2)
            return editor if isinstance(editor, ParameterValueEditor) else None

        editor = first_editor(append_item)
        if editor is not None:
            self.tree.scrollToItem(append_item)
            editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def _show_editor_errors(self, messages: tuple[str, ...]) -> None:
        self.error_label.setText("\n".join(messages))
        self.error_label.setVisible(bool(messages))
        self.validationChanged.emit(bool(messages))

    def _editor_widgets(self):
        return [
            (registration.item, registration.editor)
            for registration in self._runtime.live_editors()
        ]

    def _collapse_groups(self, root: QTreeWidgetItem | None = None) -> None:
        root = root or self.tree.invisibleRootItem()

        def visit(item):
            if item.data(0, ExpertTreeRole.COLLAPSE):
                item.setExpanded(False)
            for index in range(item.childCount()):
                visit(item.child(index))

        visit(root)

    def _update_changed_style(
        self,
        option: Any,
        item: QTreeWidgetItem,
        *,
        refresh_filter: bool = True,
    ) -> None:
        changed = bool(option.is_changed())
        related = item.data(0, ExpertTreeRole.RELATED_PATHS) or ()
        changed = changed or any(
            resolve_option(self.parameters, path).is_changed() for path in related
        )
        item.setData(0, ExpertTreeRole.CHANGED, changed)
        font = item.font(0)
        font.setBold(changed)
        item.setFont(0, font)
        if refresh_filter:
            self.apply_filter(self.filter_edit.text())
