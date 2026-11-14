"""Qt-independent binding of one guided field placement to its session."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from ase2sprkkr.common.grammar_types import Array, SetOf

from ase2sprkkr_gui.gui.input_parameters.bindings import InputParameterPath, resolve_option


@dataclass(frozen=True)
class FieldValue:
    """Value and default metadata needed by a visual value editor."""

    value: Any
    default: Any = None
    implicit_default: bool = False
    explicit: bool | None = None


def _indexed(value: Any, index: int) -> Any:
    if value is None:
        return None
    try:
        return value[index] if len(value) > index else None
    except (TypeError, IndexError):
        return None


class _SessionBindingBase:
    """Shared session transaction plumbing for field bindings."""

    @property
    def parameters(self) -> Any:
        return self.session.working_parameters

    def set_value(self, value: Any) -> Any:
        return self.update_value(
            lambda _current: value,
            text=f"Change {self.placement.label.rstrip(':')}",
        )

    def update_value(
        self,
        transform: Callable[[Any], Any],
        *,
        text: str,
        field_index: int | None = None,
    ) -> Any:
        """Transform the model value in one candidate-copy session transaction."""
        def operation(candidate: Any) -> None:
            old_value = self.model_value_from(candidate)
            self.replace_in(candidate, transform(old_value))

        return self.session.mutate(
            operation,
            source_page=self.page_id,
            path=self.path,
            field_index=field_index,
            text=text,
        )

    def value_at(self, path: InputParameterPath) -> Any:
        return self.session.value(path)

    def set_path_value(self, path: InputParameterPath, value: Any, *, text: str) -> Any:
        return self.session.set_value(
            path,
            value,
            source_page=self.page_id,
            text=text,
        )

    def mutate(
        self,
        callback: Callable[[Any], Any],
        *,
        text: str,
        path: InputParameterPath | None = None,
        field_index: int | None = None,
    ) -> Any:
        return self.session.mutate(
            callback,
            source_page=self.page_id,
            path=path or self.path,
            field_index=field_index,
            text=text,
        )


class SessionFieldBinding(_SessionBindingBase):
    """Bind an ordinary option directly to its authoritative session value."""

    def __init__(
        self,
        session: Any,
        placement: Any,
        page_id: str,
    ) -> None:
        self.session = session
        self.placement = placement
        self.page_id = page_id
        self.path: InputParameterPath = placement.path

    @property
    def option(self) -> Any:
        return self.session.option(self.path)

    @property
    def allows_unset(self) -> bool:
        option = self.option
        optional = option._definition.is_optional
        return bool(
            optional(option) if callable(optional) else optional
        ) or option.default_value is not None

    @property
    def value_type(self) -> Any:
        return self.option._definition.type

    @property
    def read_only(self) -> bool:
        return False

    @property
    def allow_empty(self) -> bool:
        return False

    def read(self) -> FieldValue:
        """Return the field value to display without mutating session state."""
        option = self.option
        complete_value = self.session.value(self.path)
        explicit = option.is_set()
        return FieldValue(
            complete_value,
            option.default_value,
            implicit_default=not explicit and complete_value is not None,
            explicit=explicit,
        )

    def model_value_from(self, parameters: Any) -> Any:
        """Return this option's logical model value from a parameter snapshot."""
        return resolve_option(parameters, self.path)(all_values=True)

    def replace_in(self, parameters: Any, value: Any) -> None:
        """Replace this option in a candidate snapshot without opening a transaction."""
        resolve_option(parameters, self.path).set(value)


class ProjectedFieldBinding(_SessionBindingBase):
    """A composable child view into a parent binding's model value."""

    def __init__(
        self,
        parent: Any,
        placement: Any,
        *,
        project_value: Callable[[Any], Any],
        replace_value: Callable[[Any, Any], Any],
        value_type: Any,
        allows_unset: bool = False,
        allow_empty: bool = False,
        read_only: bool = False,
        project_state: Callable[[FieldValue], FieldValue] | None = None,
        project_default: Callable[[Any], Any] | None = None,
    ) -> None:
        self.parent = parent
        self.session = parent.session
        self.page_id = parent.page_id
        self.path = parent.path
        self.placement = placement
        self._project_value = project_value
        self._replace_value = replace_value
        self._value_type = value_type
        self._allows_unset = allows_unset
        self._allow_empty = allow_empty
        self._read_only = read_only
        self._project_state = project_state
        self._project_default = project_default or project_value

    @property
    def option(self) -> None:
        return None

    @property
    def value_type(self) -> Any:
        return self._value_type

    @property
    def allows_unset(self) -> bool:
        return self._allows_unset

    @property
    def allow_empty(self) -> bool:
        return self._allow_empty

    @property
    def read_only(self) -> bool:
        return self._read_only

    def model_value_from(self, parameters: Any) -> Any:
        return self._project_value(self.parent.model_value_from(parameters))

    def replace_in(self, parameters: Any, value: Any) -> None:
        parent_value = self.parent.model_value_from(parameters)
        replacement = self._replace_value(parent_value, value)
        self.parent.replace_in(parameters, replacement)

    def read(self) -> FieldValue:
        parent_state = self.parent.read()
        if self._project_state is not None:
            return self._project_state(parent_state)
        return FieldValue(
            self._project_value(parent_state.value),
            self._project_default(parent_state.default),
            implicit_default=parent_state.implicit_default,
            explicit=parent_state.explicit,
        )


class FixedArrayDraft:
    """Presentation-only component values for one incomplete fixed Array."""

    def __init__(self, parent: Any, length: int, value: Any) -> None:
        self.parent = parent
        self.length = length
        self.values = _copied_sequence(value) if value is not None else []
        self.values.extend([None] * (length - len(self.values)))

    def value(self, index: int) -> Any:
        return self.values[index]

    def set_value(self, index: int, value: Any) -> None:
        self.values[index] = value
        if all(component is not None for component in self.values):
            complete = self.parent.value_type.convert(self.values)
            self.parent.set_value(complete)


class DraftFieldBinding:
    """Editor contract over one component in a presentation-only fixed Array draft."""

    def __init__(
        self,
        parent: Any,
        draft: FixedArrayDraft,
        index: int,
        placement: Any,
    ) -> None:
        self.parent = parent
        self.draft = draft
        self.index = index
        self.session = parent.session
        self.page_id = parent.page_id
        self.path = parent.path
        self.placement = placement

    @property
    def option(self) -> None:
        return None

    @property
    def parameters(self) -> Any:
        return self.session.working_parameters

    @property
    def value_type(self) -> Any:
        return self.parent.value_type.type

    @property
    def allows_unset(self) -> bool:
        return True

    @property
    def allow_empty(self) -> bool:
        return False

    @property
    def read_only(self) -> bool:
        return False

    def read(self) -> FieldValue:
        parent_state = self.parent.read()
        default = _indexed(parent_state.default, self.index)
        return FieldValue(
            self.draft.value(self.index),
            default,
            implicit_default=parent_state.implicit_default,
            explicit=parent_state.explicit,
        )

    def set_value(self, value: Any) -> None:
        self.draft.set_value(self.index, value)


def _copied_sequence(value: Any) -> list[Any]:
    if isinstance(value, np.ndarray):
        return value.copy().tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return list(value)


def _project_index(value: Any, index: int) -> Any:
    if value is None:
        return None
    try:
        return value[index]
    except (TypeError, IndexError, KeyError):
        return None


def array_item_binding(
    parent: Any,
    index: int,
    placement: Any,
    *,
    allows_unset: bool = False,
    allow_empty: bool = False,
    read_only: bool = False,
    append: bool = False,
) -> ProjectedFieldBinding:
    """Project one structural Array/SetOf item using its grammar conversion."""
    parent_type = parent.value_type
    if not isinstance(parent_type, (Array, SetOf)):
        raise TypeError(f"{parent_type} does not support structural item access")

    def project(value: Any) -> Any:
        return _project_index(value, index)

    def replace(value: Any, child: Any) -> Any:
        if append:
            result = [] if value is None else _copied_sequence(value)
        elif isinstance(value, np.ndarray):
            result = value.copy()
        else:
            result = [] if value is None else _copied_sequence(value)
        if index < len(result):
            result[index] = child
        elif append and index == len(result):
            result.append(child)
        else:
            raise IndexError(index)
        return parent_type.convert(result)

    return ProjectedFieldBinding(
        parent,
        placement,
        project_value=project,
        replace_value=replace,
        value_type=parent_type.type,
        allows_unset=allows_unset,
        allow_empty=allow_empty,
        read_only=read_only,
        project_default=lambda value: _project_index(value, index),
    )


def sequence_value_binding(
    parent: Any,
    index: int,
    placement: Any,
    *,
    value_type: Any,
    allows_unset: bool = False,
    allow_empty: bool = False,
    read_only: bool = False,
    append: bool = False,
    remove_on_none: bool = False,
) -> ProjectedFieldBinding:
    """Project one occurrence from an outer repeated-value sequence."""
    def replace(value: Any, child: Any) -> Any:
        result = [] if value is None else _copied_sequence(value)
        if remove_on_none and child is None:
            if index < len(result):
                result.pop(index)
        elif index < len(result):
            result[index] = child
        elif append and index == len(result):
            result.append(child)
        else:
            raise IndexError(index)
        return result or None

    return ProjectedFieldBinding(
        parent,
        placement,
        project_value=lambda value: _project_index(value, index),
        replace_value=replace,
        value_type=value_type,
        allows_unset=allows_unset,
        allow_empty=allow_empty,
        read_only=read_only,
        project_default=lambda _value: None,
    )


def sequence_item_binding(
    parent: Any,
    index: int,
    placement: Any,
    *,
    value_type: Any,
    allows_unset: bool = False,
    allow_empty: bool = False,
    read_only: bool = False,
    project_default: Callable[[Any], Any] | None = None,
) -> ProjectedFieldBinding:
    """Project one heterogeneous Sequence field and reconstruct its grammar type."""
    parent_type = parent.value_type

    def replace(value: Any, child: Any) -> Any:
        result = _copied_sequence(value)
        result[index] = child
        source = tuple(result) if isinstance(value, tuple) else result
        return parent_type.convert(source)

    return ProjectedFieldBinding(
        parent,
        placement,
        project_value=lambda value: _project_index(value, index),
        replace_value=replace,
        value_type=value_type,
        allows_unset=allows_unset,
        allow_empty=allow_empty,
        read_only=read_only,
        project_default=project_default or (lambda value: _project_index(value, index)),
    )


_MAPPING_DEFAULT = object()


def mapping_value_binding(
    parent: Any,
    key: Any,
    placement: Any,
    *,
    value_type: Any,
    default: Any = _MAPPING_DEFAULT,
    allows_unset: bool = False,
    allow_empty: bool = False,
    read_only: bool = False,
    project_state: Callable[[FieldValue], FieldValue] | None = None,
) -> ProjectedFieldBinding:
    """Project a mapping occurrence, copying mappings for every replacement.

    When no explicit fallback is supplied, a missing numbered occurrence inherits
    the mapping's ``def`` value. This mirrors SPR-KKR repeated-dictionary
    semantics and lets a newly appended override start from the effective
    default rather than from an empty value.
    """
    def fallback(value: Any) -> Any:
        if default is not _MAPPING_DEFAULT:
            return default
        if isinstance(value, Mapping) and key != "def":
            return value.get("def")
        return None

    def project(value: Any) -> Any:
        if isinstance(value, Mapping) and key in value:
            return value[key]
        return fallback(value)

    def replace(value: Any, child: Any) -> Any:
        result = dict(value) if isinstance(value, Mapping) else {}
        if child is None:
            result.pop(key, None)
        else:
            result[key] = child
        return result or None

    def occurrence_state(parent_state: FieldValue) -> FieldValue:
        explicit = key in parent.session.option(parent.path)
        value = project(parent_state.value)
        return FieldValue(
            value,
            fallback(parent_state.value),
            implicit_default=not explicit and value is not None,
            explicit=explicit,
        )

    return ProjectedFieldBinding(
        parent,
        placement,
        project_value=project,
        replace_value=replace,
        value_type=value_type,
        allows_unset=allows_unset,
        allow_empty=allow_empty,
        read_only=read_only,
        project_state=project_state or occurrence_state,
    )


def table_cell_binding(
    parent: Any,
    row: int,
    column: Any,
    placement: Any,
    *,
    value_type: Any,
    allows_unset: bool = False,
    allow_empty: bool = False,
    read_only: bool = False,
) -> ProjectedFieldBinding:
    """Project one cell from a supported NumPy-backed Table representation."""
    parent_type = parent.value_type

    def table_array(value: Any) -> np.ndarray:
        array = value if isinstance(value, np.ndarray) else parent_type.convert(value)
        return np.array(array, copy=True)

    def project(value: Any) -> Any:
        if value.dtype.names:
            return value[row][column]
        return value[row, column]

    def replace(value: Any, child: Any) -> Any:
        result = table_array(value)
        if result.dtype.names:
            result[row][column] = child
        else:
            result[row, column] = child
        return parent_type.convert(result)

    return ProjectedFieldBinding(
        parent,
        placement,
        project_value=project,
        replace_value=replace,
        value_type=value_type,
        allows_unset=allows_unset,
        allow_empty=allow_empty,
        read_only=read_only,
        project_default=lambda _value: None,
    )


class IndexedFieldBinding(SessionFieldBinding):
    """Expose one explicitly declared component of an array-valued option."""

    @property
    def index(self) -> int:
        return self.placement.index

    @property
    def value_type(self) -> Any:
        return self.option._definition.type.type

    def read(self) -> FieldValue:
        option = self.option
        complete_value = self.session.value(self.path)
        explicit = option.is_set()
        return FieldValue(
            self.session.display_value(self.path, self.index),
            _indexed(option.default_value, self.index),
            implicit_default=not explicit and complete_value is not None,
            explicit=explicit,
        )

    def set_value(self, value: Any) -> Any:
        index = self.index

        def update(parameters):
            option = resolve_option(parameters, self.path)
            values = list(option())
            while len(values) <= index:
                values.append(values[0] if values else value)
            values[index] = value
            option.set(values)

        return self.mutate(
            update,
            path=self.path,
            field_index=index,
            text=f"Change {self.placement.label.rstrip(':')}",
        )


def create_field_binding(
    session: Any,
    placement: Any,
    page_id: str,
) -> SessionFieldBinding:
    """Create the narrow binding required by one field placement."""
    binding_type = (
        IndexedFieldBinding
        if placement.index is not None
        else SessionFieldBinding
    )
    return binding_type(session, placement, page_id)
