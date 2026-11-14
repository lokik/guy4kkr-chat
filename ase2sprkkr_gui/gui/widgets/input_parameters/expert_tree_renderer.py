"""Recursive Qt rendering for the Expert input-parameter tree."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from enum import IntEnum
from typing import Any

import numpy as np
from ase2sprkkr.common.configuration_containers import Section
from ase2sprkkr.common.grammar_types import Array, SetOf, String, Table
from ase2sprkkr.common.grammar_types import Sequence as GrammarSequence
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath, resolve_option
from ase2sprkkr_gui.gui.input_parameters.expert_fields import ExpertFieldSpec
from ase2sprkkr_gui.gui.input_parameters.field_binding import (
    DraftFieldBinding,
    FixedArrayDraft,
    SessionFieldBinding,
    array_item_binding,
    mapping_value_binding,
    sequence_item_binding,
    sequence_value_binding,
    table_cell_binding,
)
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.specs.schema import FieldPlacement
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_runtime import ExpertTreeRuntime
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_structure import (
    ValueShape,
    describe_repeated,
    describe_value,
    value_items,
)
from ase2sprkkr_gui.gui.widgets.input_parameters.modal_editor import ExpertFieldEditorDialog
from ase2sprkkr_gui.gui.widgets.input_parameters.registry import create_editor
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import ParameterValueEditor


class ExpertTreeRole(IntEnum):
    """Presentation-only metadata stored on ``QTreeWidgetItem`` objects."""

    CHANGED = int(Qt.ItemDataRole.UserRole)
    RELATED_PATHS = int(Qt.ItemDataRole.UserRole) + 1
    COLLAPSE = int(Qt.ItemDataRole.UserRole) + 2
    APPEND = int(Qt.ItemDataRole.UserRole) + 3


_SHAPE_UNSET = object()
_REPEATED_SHAPES = frozenset(("repeated-dict", "repeated-sequence"))


def _option_value(option: Any) -> Any:
    try:
        return option.get()
    except Exception:  # noqa: BLE001 - generated getters can fail on incomplete data.
        return None


def _all_values(option: Any) -> Any:
    try:
        return option(all_values=True)
    except Exception:  # noqa: BLE001 - generated getters can fail on incomplete data.
        return None


class ExpertTreeRenderer:
    """Build and update the concrete Qt tree for Expert parameter values."""

    def __init__(
        self,
        tree: QTreeWidget,
        session: InputParametersSession,
        runtime: ExpertTreeRuntime,
        *,
        atoms: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        self.tree = tree
        self.session = session
        self.runtime = runtime
        self.atoms = atoms
        self.parent = parent
        self._field_specs: dict[InputParameterPath, ExpertFieldSpec] = {}
        self._suppressed_paths: frozenset[InputParameterPath] = frozenset()

    @property
    def parameters(self) -> Any:
        return self.session.working_parameters

    def build(
        self,
        field_specs: dict[InputParameterPath, ExpertFieldSpec],
        suppressed_paths: frozenset[InputParameterPath],
    ) -> None:
        self._field_specs = field_specs
        self._suppressed_paths = suppressed_paths
        self._build_section(self.parameters)

    def option_shape(
        self,
        option: Any,
        spec: ExpertFieldSpec | None,
    ) -> ValueShape | None:
        if spec is not None and spec.small_editor is None:
            return ValueShape("leaf", spec.editor)
        inline_editor = spec.small_editor if spec is not None else "auto"
        if option._definition.is_repeated:
            return describe_repeated(
                option._definition.type,
                _all_values(option),
                is_dict=option._definition.is_repeated.is_dict,
                default_value=option.default_value,
                editor=inline_editor,
            )
        return describe_value(
            option._definition.grammar_type,
            _option_value(option),
            inline_editor,
        )

    def render_option(
        self,
        option: Any,
        path: InputParameterPath,
        parent: QTreeWidgetItem | None,
        item: QTreeWidgetItem | None = None,
        spec: ExpertFieldSpec | None = None,
    ) -> QTreeWidgetItem:
        grammar = option._definition.grammar_type
        shape = self.option_shape(option, spec)
        placement = FieldPlacement(path, option.name)
        row_label = option.name
        type_label = str(option._definition.type)
        related_paths: tuple[InputParameterPath, ...] = ()
        if spec is not None:
            if spec.small_editor is None:
                placement = spec.placement(path, option.name)
                type_label = spec.type_label or type_label
                related_paths = spec.related_paths
                node_item = item or self._new_item(parent, placement.label, type_label, option.info)
                self._reset_row(
                    node_item,
                    placement.label,
                    type_label,
                    option.info,
                    related_paths,
                )
                binding = SessionFieldBinding(self.session, placement, "expert")
                self._render_value(
                    binding,
                    placement,
                    option._definition.type,
                    node_item,
                    path,
                    spec=spec,
                    shape=shape,
                )
            else:
                placement = spec.placement(path, option.name, editor=spec.small_editor)
                row_label = placement.label
                type_label = spec.type_label or type_label
                related_paths = spec.related_paths
                node_item = item or self._new_item(parent, row_label, type_label, option.info)
                self._reset_row(
                    node_item,
                    row_label,
                    type_label,
                    option.info,
                    related_paths,
                )
                if self._is_repeated(shape):
                    self._render_repeated(option, path, placement, node_item)
                else:
                    binding = SessionFieldBinding(self.session, placement, "expert")
                    self._render_value(
                        binding,
                        placement,
                        grammar,
                        node_item,
                        path,
                        spec=spec,
                        shape=shape,
                    )
                self._install_full_editor(node_item, path, spec)
        else:
            node_item = item or self._new_item(parent, row_label, type_label, option.info)
            self._reset_row(node_item, row_label, type_label, option.info)
            if self._is_repeated(shape):
                self._render_repeated(option, path, placement, node_item)
            else:
                binding = SessionFieldBinding(self.session, placement, "expert")
                self._render_value(
                    binding,
                    placement,
                    grammar,
                    node_item,
                    path,
                    shape=shape,
                )

        self.runtime.register_option(path, node_item, shape)
        return node_item

    def apply_placement_presentation(
        self,
        editor: ParameterValueEditor,
        placement: FieldPlacement,
    ) -> None:
        text = placement.special_value_text
        if not text:
            return
        if isinstance(editor, QLineEdit):
            editor.setPlaceholderText(text)
        elif hasattr(editor, "setSpecialValueText"):
            editor.setSpecialValueText(text)

    @staticmethod
    def _is_repeated(shape: ValueShape | None) -> bool:
        return shape is not None and shape.kind in _REPEATED_SHAPES

    def _build_section(self, parent: Any, treeitem: QTreeWidgetItem | None = None) -> None:
        expert_parent = None
        for option in parent:
            if isinstance(option, Section):
                info = option.info
                item = QTreeWidgetItem([option.name, "", "", "", info])
                item.setToolTip(4, info)
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
                self._add_child(treeitem, item)
                self._build_section(option, item)
                continue
            path = tuple(option._get_path().split("."))
            if path in self._suppressed_paths:
                continue
            if bool(getattr(option._definition, "expert", False)):
                if expert_parent is None:
                    expert_parent = QTreeWidgetItem(["expert", "", "", "", "Expert options"])
                    self._add_child(treeitem, expert_parent)
                row_parent = expert_parent
            else:
                row_parent = treeitem
            self.render_option(option, path, row_parent, spec=self._field_specs.get(path))

    def _add_child(self, parent: QTreeWidgetItem | None, item: QTreeWidgetItem) -> None:
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)

    def _new_item(
        self,
        parent: QTreeWidgetItem | None,
        label: str,
        type_label: str = "",
        comment: str = "",
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label, type_label, "", "", comment])
        self._add_child(parent, item)
        return item

    @staticmethod
    def _reset_row(
        item: QTreeWidgetItem,
        label: str,
        type_label: str,
        comment: str,
        related: tuple[InputParameterPath, ...] = (),
    ) -> None:
        item.setText(0, label)
        item.setText(1, type_label)
        item.setText(4, comment)
        item.setToolTip(1, type_label)
        item.setToolTip(4, comment)
        item.setData(0, ExpertTreeRole.RELATED_PATHS, related)

    def _render_value(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: Any,
        item: QTreeWidgetItem,
        path: InputParameterPath,
        *,
        spec: ExpertFieldSpec | None = None,
        append: bool = True,
        shape: ValueShape | None | object = _SHAPE_UNSET,
    ) -> None:
        if isinstance(binding, DraftFieldBinding):
            self._install_editor(item, binding, placement, spec=spec)
            return

        if shape is _SHAPE_UNSET:
            value = binding.model_value_from(binding.parameters)
            shape = describe_value(
                grammar,
                value,
                placement.editor,
                allow_append=append,
            )

        if shape is None or shape.kind in ("leaf", "sequence-leaf"):
            self._install_editor(item, binding, placement, spec=spec)
            return
        if shape.kind == "array":
            self._render_array(binding, placement, grammar, item, path, shape)
            return
        if shape.kind == "sequence":
            self._render_sequence(binding, placement, grammar, item, path)
            return
        if shape.kind == "table":
            self._render_table(binding, placement, grammar, item, path)
            return
        raise RuntimeError(f"Unsupported Expert tree value shape: {shape.kind}")

    def _render_array(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: Any,
        item: QTreeWidgetItem,
        path: InputParameterPath,
        shape: ValueShape,
    ) -> None:
        self._install_editor(item, binding, placement)
        self._render_array_children(binding, placement, grammar, item, path, shape=shape)

    def _render_sequence(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: GrammarSequence,
        item: QTreeWidgetItem,
        path: InputParameterPath,
    ) -> None:
        values = value_items(binding.model_value_from(binding.parameters))
        self._install_editor(item, binding, placement)
        self._clear_children(item)
        names = getattr(grammar, "names", None)
        labels = [f"[{i}]" for i in range(len(grammar.types))]
        if isinstance(names, Mapping):
            for name, index in names.items():
                if isinstance(index, int) and 0 <= index < len(labels):
                    labels[index] = str(name)
        for index, subtype in enumerate(grammar.types):
            child_placement = FieldPlacement(path, labels[index])
            child_binding = sequence_item_binding(
                binding,
                index,
                child_placement,
                value_type=subtype,
                allows_unset=False,
            )
            child = self._new_item(item, labels[index], str(subtype))
            child_shape = describe_value(subtype, values[index])
            self._render_value(
                child_binding,
                child_placement,
                subtype,
                child,
                path,
                shape=child_shape,
            )

    def _render_table(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: Table,
        item: QTreeWidgetItem,
        path: InputParameterPath,
    ) -> None:
        self._clear_children(item)
        value = binding.model_value_from(binding.parameters)
        if value is None:
            self._set_value_label(item, "<Table>")
            return
        try:
            array = value if isinstance(value, np.ndarray) else grammar.convert(value)
        except Exception:  # noqa: BLE001 - preserve opaque input fallback.
            self._set_value_label(item, "<Data>")
            return
        if not isinstance(array, np.ndarray):
            self._set_value_label(item, "<Data>")
            return

        self._set_value_label(item, "<Table>")
        sequence = grammar.sequence
        if array.dtype.names:
            names = list(array.dtype.names)
            rows = range(len(array))
            cells_for_row = lambda row: [
                (name, row, name, index) for index, name in enumerate(names)
            ]
        else:
            data = np.asarray(array)
            if data.ndim == 1:
                if len(sequence.types) != 1:
                    return
                data = data.reshape((-1, 1))
            if data.ndim != 2:
                return
            names = getattr(grammar, "names", None) or [
                f"[{i}]" for i in range(data.shape[1])
            ]
            rows = range(data.shape[0])
            cells_for_row = lambda row: [
                (
                    names[col] if col < len(names) else f"[{col}]",
                    row,
                    col,
                    col,
                )
                for col in range(data.shape[1])
            ]

        for row_index in rows:
            row_item = self._new_item(item, f"[{row_index}]", "row")
            for label, row, column, column_index in cells_for_row(row_index):
                subtype = (
                    sequence.types[column_index]
                    if column_index < len(sequence.types)
                    else String()
                )
                cell_placement = FieldPlacement(path, str(label))
                cell_binding = table_cell_binding(
                    binding,
                    row,
                    column,
                    cell_placement,
                    value_type=subtype,
                )
                cell = self._new_item(row_item, str(label), str(subtype))
                cell_shape = describe_value(subtype, array[row][column] if array.dtype.names else data[row, column])
                self._render_value(
                    cell_binding,
                    cell_placement,
                    subtype,
                    cell,
                    path,
                    shape=cell_shape,
                )

    def _render_repeated(
        self,
        option: Any,
        path: InputParameterPath,
        placement: FieldPlacement,
        item: QTreeWidgetItem,
    ) -> None:
        root = SessionFieldBinding(self.session, placement, "expert")
        grammar = option._definition.type
        repeated = option._definition.is_repeated
        value = _all_values(option)
        self._clear_children(item)
        if repeated.is_dict:
            mapping = value if isinstance(value, Mapping) else {}
            default = mapping_value_binding(
                root,
                "def",
                placement,
                value_type=grammar,
                default=option.default_value,
                allows_unset=True,
            )
            if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
                whole_placement = replace(placement, editor="text")
                self._install_editor(item, default, whole_placement)
            else:
                default_shape = describe_value(
                    grammar,
                    mapping.get("def", option.default_value),
                    placement.editor,
                    allow_append=False,
                )
                self._render_value(
                    default,
                    placement,
                    grammar,
                    item,
                    path,
                    append=False,
                    shape=default_shape,
                )
            if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
                group = self._new_item(
                    item,
                    "Default items",
                    str(grammar.type),
                    "Items of the default value",
                )
                self._render_array_children(
                    default,
                    placement,
                    grammar,
                    group,
                    path,
                    append=False,
                )
                group.setData(0, ExpertTreeRole.COLLAPSE, True)
            keys = sorted(
                (key for key in mapping if key != "def"),
                key=lambda key: (not isinstance(key, int), key),
            )
            for key in keys:
                child_placement = FieldPlacement(path, f"[{key}]", editor=placement.editor)
                binding = mapping_value_binding(
                    root,
                    key,
                    child_placement,
                    value_type=grammar,
                    default=option.default_value,
                    allows_unset=True,
                )
                child = self._new_item(item, child_placement.label, str(grammar))
                if isinstance(grammar, (Array, SetOf)) and getattr(
                    grammar, "array_access", False
                ):
                    child.setData(0, ExpertTreeRole.COLLAPSE, True)
                    whole_placement = replace(child_placement, editor="text")
                    self._install_editor(child, binding, whole_placement)
                    self._render_array_children(
                        binding,
                        child_placement,
                        grammar,
                        child,
                        path,
                        append=False,
                    )
                else:
                    child_shape = describe_value(grammar, mapping[key], child_placement.editor)
                    self._render_value(
                        binding,
                        child_placement,
                        grammar,
                        child,
                        path,
                        shape=child_shape,
                    )
                self._install_action(
                    child,
                    "Remove repeated value",
                    f"Remove repeated value {key}",
                    lambda current=binding: current.set_value(None),
                    remove=True,
                )
            numeric = [key for key in keys if isinstance(key, int)]
            next_key = max(numeric, default=0) + 1
            append_placement = FieldPlacement(
                path,
                f"[{next_key}]",
                editor=(
                    "text"
                    if isinstance(grammar, (Array, SetOf))
                    else placement.editor
                ),
                special_value_text="Add value…",
            )
            append_binding = mapping_value_binding(
                root,
                next_key,
                append_placement,
                value_type=grammar,
                allows_unset=False,
                allow_empty=True,
            )
            append_item = self._new_item(
                item,
                append_placement.label,
                str(grammar),
                "Add numbered value",
            )
            append_item.setData(0, ExpertTreeRole.APPEND, True)
            self._install_editor(append_item, append_binding, append_placement)
            if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
                self._render_array_children(
                    append_binding,
                    append_placement,
                    grammar,
                    append_item,
                    path,
                    append=False,
                )
        else:
            sequence = value_items(value)
            summary = f"<{len(sequence)} value{'s' if len(sequence) != 1 else ''}>"
            self._set_value_label(item, summary)
            for index, entry in enumerate(sequence):
                self._render_sequence_occurrence(
                    root,
                    grammar,
                    path,
                    item,
                    index,
                    value=entry,
                    append=False,
                )
            self._render_sequence_occurrence(
                root,
                grammar,
                path,
                item,
                len(sequence),
                value=None,
                append=True,
            )

    def _render_array_children(
        self,
        binding: Any,
        placement: FieldPlacement,
        grammar: Any,
        item: QTreeWidgetItem,
        path: InputParameterPath,
        *,
        append: bool | None = None,
        shape: ValueShape | None = None,
    ) -> None:
        self._clear_children(item)
        value = binding.model_value_from(binding.parameters)
        if shape is None:
            shape = describe_value(
                grammar,
                value,
                allow_append=True if append is None else append,
            )
        if shape is None or shape.kind != "array":
            raise RuntimeError("Array child rendering requires an array ValueShape")

        display_length, fixed, can_append, incomplete, child_shapes = shape.detail
        values = value_items(value)
        display = list(values)
        if fixed:
            display.extend([None] * max(0, display_length - len(display)))
        minimum = getattr(grammar, "min_length", None)
        draft = FixedArrayDraft(binding, minimum, value) if incomplete else None
        for index, _component in enumerate(display):
            child_placement = FieldPlacement(path, f"[{index}]")
            child_binding = (
                DraftFieldBinding(binding, draft, index, child_placement)
                if draft is not None
                else array_item_binding(
                    binding,
                    index,
                    child_placement,
                    allows_unset=False,
                )
            )
            child = self._new_item(item, child_placement.label, str(grammar.type))
            if isinstance(child_binding, DraftFieldBinding):
                self._install_editor(child, child_binding, child_placement)
            else:
                self._render_value(
                    child_binding,
                    child_placement,
                    grammar.type,
                    child,
                    path,
                    shape=child_shapes[index],
                )
        if can_append:
            index = len(values)
            child_placement = FieldPlacement(
                path,
                f"[{index}]",
                special_value_text="Append…",
            )
            child_binding = array_item_binding(
                binding,
                index,
                child_placement,
                append=True,
                allow_empty=True,
            )
            child = self._new_item(
                item,
                child_placement.label,
                str(grammar.type),
                "Append new item",
            )
            child.setData(0, ExpertTreeRole.APPEND, True)
            self._render_value(child_binding, child_placement, grammar.type, child, path)

    def _render_sequence_occurrence(
        self,
        root: Any,
        grammar: Any,
        path: InputParameterPath,
        parent: QTreeWidgetItem,
        index: int,
        *,
        value: Any,
        append: bool,
    ) -> None:
        label = f"[{index + 1}]"
        placement = FieldPlacement(
            path,
            label,
            special_value_text="Add value…" if append else None,
        )
        binding = sequence_value_binding(
            root,
            index,
            placement,
            value_type=grammar,
            allows_unset=not append,
            allow_empty=append,
            append=append,
            remove_on_none=not append,
        )
        item = self._new_item(
            parent,
            label,
            str(grammar),
            "Add numbered value" if append else "",
        )
        if append:
            item.setData(0, ExpertTreeRole.APPEND, True)
        if isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False):
            whole_placement = replace(placement, editor="text")
            self._install_editor(item, binding, whole_placement)
            if not append:
                item.setData(0, ExpertTreeRole.COLLAPSE, True)
                occurrence_shape = describe_value(grammar, value, allow_append=False)
                self._render_array_children(
                    binding,
                    placement,
                    grammar,
                    item,
                    path,
                    shape=occurrence_shape,
                )
        else:
            occurrence_shape = None if append else describe_value(grammar, value)
            self._render_value(
                binding,
                placement,
                grammar,
                item,
                path,
                append=not append,
                shape=_SHAPE_UNSET if append else occurrence_shape,
            )
        if not append:
            self._install_action(
                item,
                "Remove repeated value",
                f"Remove repeated value {index + 1}",
                lambda current=binding: current.set_value(None),
                remove=True,
            )

    def _install_editor(
        self,
        item: QTreeWidgetItem,
        binding: Any,
        placement: FieldPlacement,
        *,
        spec: ExpertFieldSpec | None = None,
    ) -> ParameterValueEditor:
        existing = self.tree.itemWidget(item, 2)
        if isinstance(existing, ParameterValueEditor):
            editor = existing
            editor.refresh()
        else:
            editor = create_editor(binding, placement, atoms=self.atoms, parent=self.tree)
            self.tree.setItemWidget(item, 2, editor)
            self._connect_editor(item, editor)
            editor.refresh()
        self.apply_placement_presentation(editor, placement)
        if spec and spec.minimum_width:
            editor.setMinimumWidth(spec.minimum_width)
            self.tree.setColumnWidth(2, max(spec.minimum_width, self.tree.columnWidth(2)))
        self.runtime.register_editor(editor, item, placement)
        return editor

    def _install_full_editor(
        self,
        item: QTreeWidgetItem,
        path: InputParameterPath,
        spec: ExpertFieldSpec,
    ) -> None:
        self._install_action(
            item,
            f"Open full editor for {'.'.join(path)}",
            f"Open full editor for {'.'.join(path)}",
            lambda p=path, s=spec: self._open_full_editor(p, s),
            icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )

    def _install_action(
        self,
        item: QTreeWidgetItem,
        label: str,
        tooltip: str,
        callback: Any,
        *,
        remove: bool = False,
        icon: QStyle.StandardPixmap | None = None,
    ) -> None:
        button = QToolButton(self.tree)
        button.setAutoRaise(True)
        button.setToolTip(tooltip)
        button.setAccessibleName(label)
        if icon is not None:
            button.setIcon(self.tree.style().standardIcon(icon))
        elif remove:
            button.setIcon(self.tree.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
        else:
            button.setText(label)
        button.clicked.connect(lambda _checked=False, action=callback: action())
        self.tree.setItemWidget(item, 3, button)

    def _set_value_label(self, item: QTreeWidgetItem, text: str) -> None:
        item.setText(2, text)
        item.setToolTip(2, text)
        label = QLabel(text)
        label.setToolTip(text)
        self.tree.setItemWidget(item, 2, label)

    def _clear_children(self, item: QTreeWidgetItem) -> None:
        self.runtime.unregister_subtree(item, include_root=False)
        while item.childCount():
            item.removeChild(item.child(0))

    def _connect_editor(self, item: QTreeWidgetItem, editor: ParameterValueEditor) -> None:
        editor.validationChanged.connect(
            lambda message, row=item: self.runtime.set_error(
                row,
                row.text(0),
                message,
            )
        )
        item.setSizeHint(2, editor.sizeHint())

    def _open_full_editor(self, path: InputParameterPath, spec: ExpertFieldSpec) -> None:
        option = resolve_option(self.parameters, path)
        dialog = ExpertFieldEditorDialog(
            self.parameters,
            path,
            spec,
            atoms=self.atoms,
            parent=self.parent,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            placement = FieldPlacement(path, option.name)
            SessionFieldBinding(self.session, placement, "expert").set_value(dialog.value)
