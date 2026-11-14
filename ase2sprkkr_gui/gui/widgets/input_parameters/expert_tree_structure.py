"""Qt-free structural description of values rendered by the Expert tree."""
from __future__ import annotations

from collections.abc import Mapping, Sequence as AbcSequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from ase2sprkkr.common.grammar_types import Array, SetOf, String, Table
from ase2sprkkr.common.grammar_types import Sequence as GrammarSequence


@dataclass(frozen=True)
class ValueShape:
    """Structural part of an Expert-tree value presentation.

    Scalar values deliberately do not participate in the shape. Two values
    with the same ``ValueShape`` can therefore be refreshed in-place; a shape
    change means that the corresponding tree branch has to be rebuilt.

    ``contains_draft`` records drafts that are part of the represented model
    value. They are intentionally rebuilt on an external refresh even while
    their structural shape is otherwise unchanged. Append-only draft rows are
    not part of the current model value: they commit by changing the shape, so
    they must not force unrelated existing editors to be rebuilt.
    """

    kind: str
    detail: Any = None
    contains_draft: bool = False


def value_items(value: Any) -> list[Any]:
    """Normalize sequence-like values for structural inspection."""
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, AbcSequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def sequence_values(grammar: GrammarSequence, value: Any) -> list[Any] | None:
    """Return a complete Sequence value, or None while it needs whole-value editing."""
    if value is None:
        return None
    try:
        grammar.validate(value)
    except (TypeError, ValueError):
        return None
    return value_items(value)


def describe_value(
    grammar: Any,
    value: Any,
    editor: str = "auto",
    *,
    allow_append: bool = True,
) -> ValueShape | None:
    """Describe only the parts of a value that affect the rendered tree shape."""
    if editor != "auto":
        return ValueShape("leaf", editor)

    if _array_children(grammar):
        values = value_items(value)
        minimum = getattr(grammar, "min_length", None)
        maximum = getattr(grammar, "max_length", None)
        fixed = minimum is not None and minimum == maximum
        display = list(values)
        if fixed:
            display.extend([None] * max(0, minimum - len(display)))
        children = tuple(describe_value(grammar.type, child) for child in display)
        append = allow_append and not fixed and (maximum is None or len(values) < maximum)
        incomplete = fixed and any(child is None for child in display)
        return ValueShape(
            "array",
            (len(display), fixed, append, incomplete, children),
            incomplete or _children_contain_draft(children),
        )

    if isinstance(grammar, GrammarSequence):
        values = sequence_values(grammar, value)
        if values is None:
            return ValueShape("sequence-leaf")
        children = tuple(
            describe_value(child_type, values[index])
            for index, child_type in enumerate(grammar.types)
        )
        return ValueShape(
            "sequence",
            children,
            _children_contain_draft(children),
        )

    if isinstance(grammar, Table):
        return _describe_table(grammar, value)

    return None


def describe_repeated(
    grammar: Any,
    value: Any,
    *,
    is_dict: bool,
    default_value: Any,
    editor: str = "auto",
) -> ValueShape:
    """Describe the structural presentation of a repeated option.

    Repeated arrays are special in the Qt renderer: existing occurrences are
    expanded into child rows even when the occurrence also has an explicit
    whole-value editor. Their shape therefore has to be inspected as ``auto``.
    Append rows are intentionally excluded from ``contains_draft`` because
    their draft is not yet model state; once committed, the repeated shape
    changes and the row is rebuilt naturally.
    """
    repeated_editor = "auto" if _array_children(grammar) else editor

    if is_dict:
        mapping = value if isinstance(value, Mapping) else {}
        entries = [("def", mapping.get("def", default_value))]
        entries.extend(
            (key, mapping[key])
            for key in sorted(
                (key for key in mapping if key != "def"),
                key=lambda key: (not isinstance(key, int), key),
            )
        )
        shapes = tuple(
            (
                key,
                describe_value(
                    grammar,
                    item,
                    repeated_editor,
                    allow_append=False,
                ),
            )
            for key, item in entries
        )
        contains_draft = _children_contain_draft(shape for _, shape in shapes)
        return ValueShape("repeated-dict", shapes, contains_draft)

    shapes = tuple(
        describe_value(grammar, item, repeated_editor)
        for item in value_items(value)
    )
    return ValueShape(
        "repeated-sequence",
        shapes,
        _children_contain_draft(shapes),
    )


def _describe_table(grammar: Table, value: Any) -> ValueShape:
    if value is None:
        return ValueShape("table")
    try:
        array = value if isinstance(value, np.ndarray) else grammar.convert(value)
    except Exception:  # noqa: BLE001 - invalid/opaque imported values stay displayable.
        return ValueShape("table", "opaque")
    if not isinstance(array, np.ndarray):
        return ValueShape("table", "opaque")

    sequence = grammar.sequence
    rows = []
    if array.dtype.names:
        names = list(array.dtype.names)
        for row in range(len(array)):
            rows.append(
                tuple(
                    describe_value(
                        sequence.types[index] if index < len(sequence.types) else String(),
                        array[row][name],
                    )
                    for index, name in enumerate(names)
                )
            )
    else:
        data = np.asarray(array)
        if data.ndim == 1 and len(sequence.types) == 1:
            data = data.reshape((-1, 1))
        if data.ndim != 2:
            return ValueShape("table", (data.shape, "opaque"))
        for row in range(data.shape[0]):
            rows.append(
                tuple(
                    describe_value(
                        sequence.types[column] if column < len(sequence.types) else String(),
                        data[row, column],
                    )
                    for column in range(data.shape[1])
                )
            )

    row_shapes = tuple(rows)
    return ValueShape(
        "table",
        (array.shape, array.dtype.names, row_shapes),
        any(_children_contain_draft(row) for row in row_shapes),
    )


def _array_children(grammar: Any) -> bool:
    return isinstance(grammar, (Array, SetOf)) and getattr(grammar, "array_access", False)


def _children_contain_draft(children) -> bool:
    return any(child is not None and child.contains_draft for child in children)
