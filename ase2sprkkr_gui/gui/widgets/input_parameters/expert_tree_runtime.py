"""Runtime bookkeeping for editors installed in the Expert input tree."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6 import sip
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath
from ase2sprkkr_gui.gui.input_parameters.specs.schema import FieldPlacement
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_structure import ValueShape
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import ParameterValueEditor


@dataclass(frozen=True)
class EditorRegistration:
    editor: ParameterValueEditor
    item: QTreeWidgetItem
    dependencies: frozenset[InputParameterPath]
    placement: FieldPlacement


class ExpertTreeRuntime:
    """Own live Qt-editor registries associated with one Expert tree.

    Rendering decides *what* belongs in the tree. This object tracks the
    resulting live option rows and shapes, editors, their dependencies and
    validation errors, and tears down cell widgets before rendered subtrees are
    detached from the Qt item model.
    """

    def __init__(
        self,
        tree: QTreeWidget,
        *,
        errors_changed: Callable[[tuple[str, ...]], None] | None = None,
    ) -> None:
        self.tree = tree
        self._errors_changed = errors_changed
        self._option_rows: dict[InputParameterPath, QTreeWidgetItem] = {}
        self._option_shapes: dict[InputParameterPath, ValueShape | None] = {}
        self._option_paths: dict[int, InputParameterPath] = {}
        self._editors: dict[int, EditorRegistration] = {}
        self._errors: dict[int, tuple[QTreeWidgetItem, str, str]] = {}

    @property
    def has_errors(self) -> bool:
        return bool(self._errors)

    @property
    def error_messages(self) -> tuple[str, ...]:
        return tuple(f"{label}: {error}" for _, label, error in self._errors.values())

    def option_items(self) -> tuple[tuple[InputParameterPath, QTreeWidgetItem], ...]:
        """Return a stable snapshot of currently registered option rows."""
        self.prune()
        return tuple(self._option_rows.items())

    def option_item(self, path: InputParameterPath) -> QTreeWidgetItem | None:
        item = self._option_rows.get(path)
        if item is not None and sip.isdeleted(item):
            self._remove_option(path, item)
            return None
        return item

    def option_path_for_item(self, item: QTreeWidgetItem) -> InputParameterPath | None:
        """Return a path only when ``item`` is itself a registered option row."""
        return self._option_paths.get(id(item))

    def option_shape(self, path: InputParameterPath) -> ValueShape | None:
        return self._option_shapes.get(path)

    def register_option(
        self,
        path: InputParameterPath,
        item: QTreeWidgetItem,
        shape: ValueShape | None = None,
    ) -> None:
        previous = self._option_rows.get(path)
        if previous is not None and previous is not item:
            self._option_paths.pop(id(previous), None)
        old_path = self._option_paths.get(id(item))
        if old_path is not None and old_path != path:
            self._option_rows.pop(old_path, None)
            self._option_shapes.pop(old_path, None)
        self._option_rows[path] = item
        self._option_shapes[path] = shape
        self._option_paths[id(item)] = path

    def register_editor(
        self,
        editor: ParameterValueEditor,
        item: QTreeWidgetItem,
        placement: FieldPlacement,
    ) -> None:
        dependencies = set(placement.paths)
        dependencies.update(getattr(editor, "dependencies", ()))
        self._editors[id(editor)] = EditorRegistration(
            editor,
            item,
            frozenset(dependencies),
            placement,
        )

    def live_editors(self) -> tuple[EditorRegistration, ...]:
        self.prune()
        return tuple(self._editors.values())

    def editors_depending_on(
        self,
        paths: tuple[InputParameterPath, ...],
        *,
        exclude_ids: set[int] | None = None,
    ) -> tuple[EditorRegistration, ...]:
        changed = set(paths)
        excluded = exclude_ids or set()
        return tuple(
            registration
            for registration in self.live_editors()
            if id(registration.editor) not in excluded
            and registration.dependencies.intersection(changed)
        )

    def set_error(self, item: QTreeWidgetItem, label: str, message: str) -> None:
        before = self.error_messages
        key = id(item)
        if message:
            self._errors[key] = (item, label, message)
        else:
            self._errors.pop(key, None)
        self._publish_errors_if_changed(before)

    def unregister_subtree(
        self,
        item: QTreeWidgetItem,
        *,
        include_root: bool = True,
    ) -> None:
        """Unregister a subtree and remove its cell widgets from the Qt view.

        The renderer may detach the corresponding ``QTreeWidgetItem`` objects
        immediately afterwards.  Cell widgets must be removed while their
        model indexes are still valid; otherwise the view can retain widgets
        associated with detached rows.
        """
        before = self.error_messages
        self._unregister_subtree(item, include_root=include_root)
        self._publish_errors_if_changed(before)

    def clear(self) -> None:
        before = self.error_messages
        self._option_rows.clear()
        self._option_shapes.clear()
        self._option_paths.clear()
        self._editors.clear()
        self._errors.clear()
        self._publish_errors_if_changed(before)

    def prune(self) -> None:
        before = self.error_messages
        live_options = {
            path: item
            for path, item in self._option_rows.items()
            if not sip.isdeleted(item)
        }
        self._option_rows = live_options
        self._option_shapes = {
            path: self._option_shapes.get(path)
            for path in live_options
        }
        self._option_paths = {id(item): path for path, item in live_options.items()}
        self._editors = {
            key: registration
            for key, registration in self._editors.items()
            if not sip.isdeleted(registration.editor)
            and not sip.isdeleted(registration.item)
            and self.tree.itemWidget(registration.item, 2) is registration.editor
        }
        live_editor_items = {id(registration.item) for registration in self._editors.values()}
        self._errors = {
            key: (item, label, error)
            for key, (item, label, error) in self._errors.items()
            if not sip.isdeleted(item) and key in live_editor_items
        }
        self._publish_errors_if_changed(before)

    def _unregister_subtree(
        self,
        item: QTreeWidgetItem,
        *,
        include_root: bool,
    ) -> None:
        for index in range(item.childCount()):
            self._unregister_subtree(item.child(index), include_root=True)
        if include_root:
            self._unregister_item(item)

    def _unregister_item(self, item: QTreeWidgetItem) -> None:
        editor = self.tree.itemWidget(item, 2)
        if editor is not None:
            self._editors.pop(id(editor), None)
        self._errors.pop(id(item), None)
        path = self._option_paths.pop(id(item), None)
        if path is not None and self._option_rows.get(path) is item:
            self._option_rows.pop(path, None)
            self._option_shapes.pop(path, None)

        # QTreeWidget owns widgets installed with setItemWidget().  Remove them
        # while the item's model index is still valid; the renderer detaches
        # the QTreeWidgetItem only after this method returns.
        for column in range(self.tree.columnCount()):
            if self.tree.itemWidget(item, column) is not None:
                self.tree.removeItemWidget(item, column)

    def _remove_option(self, path: InputParameterPath, item: QTreeWidgetItem) -> None:
        if self._option_rows.get(path) is item:
            self._option_rows.pop(path, None)
            self._option_shapes.pop(path, None)
        self._option_paths.pop(id(item), None)

    def _publish_errors_if_changed(self, before: tuple[str, ...]) -> None:
        current = self.error_messages
        if current != before and self._errors_changed is not None:
            self._errors_changed(current)
