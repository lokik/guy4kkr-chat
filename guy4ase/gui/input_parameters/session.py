"""Transactional editing state for the guided input-parameter dialog."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from ase2sprkkr import InputParameters
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QUndoCommand, QUndoStack

from guy4ase.gui.input_parameters.bindings import (
    InputParameterPath,
    resolve_option,
    values_equal,
)

DormantKey = tuple[InputParameterPath, int]
DormantState = MutableMapping[DormantKey, Any]


class SessionTransactionPlugin(Protocol):
    """Adjust a candidate and its non-serialized editing state atomically."""

    def apply(
        self,
        before_parameters: InputParameters,
        candidate_parameters: InputParameters,
        dormant: DormantState,
    ) -> None: ...


@dataclass(frozen=True)
class _SessionSnapshot:
    """The complete state restored by one undo/redo operation."""

    parameters: InputParameters
    dormant: dict[DormantKey, Any]


def _parameters_equal(left: InputParameters, right: InputParameters) -> bool:
    """Compare effective editable values, excluding derived/generated options."""
    if left.task_name != right.task_name:
        return False
    # Generated getters are deliberately excluded.  The non-generated effective
    # values are the editable state; generated values are reconstructed by
    # ase2sprkkr from that state.
    left_values = left.as_dict(only_changed=False, generated=False, copy=True)
    right_values = right.as_dict(only_changed=False, generated=False, copy=True)
    return values_equal(left_values, right_values)


def _option_values_equal(value_type: Any, left: Any, right: Any) -> bool:
    """Compare complete option values without feeding occurrence maps to a type.

    ``Option(..., all_values=True)`` returns a mapping for numbered/defaulted
    options.  A grammar type comparator describes one occurrence, not that
    wrapper mapping, so compare matching occurrences independently while still
    delegating leaf semantics (and errors) to the grammar type itself.
    """
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        if left.keys() != right.keys():
            return False
        return all(
            _option_values_equal(value_type, left[key], right[key])
            for key in left
        )
    result = value_type.is_the_same_value(left, right)
    if isinstance(result, np.ndarray):
        return bool(np.all(result))
    return bool(result)


def _changed_values(before: InputParameters, after: InputParameters) -> dict:
    """Keep option values intact, including arrays and per-type dictionaries."""
    left = before.as_dict(only_changed=False, generated=False, copy=True)
    right = after.as_dict(only_changed=False, generated=False, copy=True)
    changes = {}
    for section in dict.fromkeys((*left, *right)):
        old, new = left.get(section, {}), right.get(section, {})
        for name in dict.fromkeys((*old, *new)):
            a, b = old.get(name), new.get(name)
            if not values_equal(a, b):
                changes[(section, name)] = (a, b)
    return changes


def _history_value(value: Any) -> str:
    if value is None:
        return "Not set"
    if isinstance(value, np.ndarray):
        value = value.tolist()
    text = str(value)
    return text if len(text) <= 120 else text[:117] + "…"


class _ReplaceParametersCommand(QUndoCommand):
    def __init__(
        self,
        session: "InputParametersSession",
        before: _SessionSnapshot,
        after: _SessionSnapshot,
        *,
        text: str,
        source_page: str | None,
        path: InputParameterPath | None,
        field_index: int | None,
    ) -> None:
        super().__init__(text)
        self._session = session
        self._before = before
        self._after = after
        self.source_page = source_page
        self.path = path
        self.field_index = field_index
        self.changes = _changed_values(before.parameters, after.parameters)
        self._first_redo = True

    def description(self, *, undo: bool) -> str:
        lines = [("Undo: " if undo else "Redo: ") + self.text()]
        for path, (before, after) in list(self.changes.items())[:6]:
            name = ".".join(path)
            if path == self.path and self.field_index is not None:
                index = self.field_index
                before = before[index] if before is not None and len(before) > index else None
                after = after[index] if after is not None and len(after) > index else None
                name += f"[{index + 1}]"
            source, target = (after, before) if undo else (before, after)
            lines.append(f"{name}: {_history_value(source)} → {_history_value(target)}")
        if len(self.changes) > 6:
            lines.append(f"… and {len(self.changes) - 6} more parameters")
        return "\n".join(lines)

    def _notify_navigation(self) -> None:
        """Request navigation to the source field and first changed array element."""
        paths = tuple(dict.fromkeys(((self.path,) if self.path else ()) + tuple(self.changes)))
        indices = {}
        for path, (before, after) in self.changes.items():
            if isinstance(before, (list, tuple, np.ndarray)) and isinstance(after, (list, tuple, np.ndarray)):
                for index in range(max(len(before), len(after))):
                    if (index >= len(before) or index >= len(after)
                            or not values_equal(before[index], after[index])):
                        indices[path] = index
                        break
        if self.path is not None and self.field_index is not None:
            indices[self.path] = self.field_index
        self._session.historyApplied.emit(paths, self.source_page, indices)

    def undo(self) -> None:
        self._session._install(self._before, self.path, reset=True)
        self._notify_navigation()

    def redo(self) -> None:
        self._session._install(
            self._after,
            self.path,
            reset=not self._first_redo or self.path is None,
        )
        # QUndoStack.push() calls redo too. Ordinary edits must not navigate.
        if not self._first_redo:
            self._notify_navigation()
        self._first_redo = False


class InputParametersSession(QObject):
    """Own an isolated working copy and its undo/redo history."""

    valueChanged = pyqtSignal(object)
    parametersReplaced = pyqtSignal()
    editApplied = pyqtSignal(object, bool)  # changed paths, discard all drafts
    modifiedChanged = pyqtSignal(bool)
    historyApplied = pyqtSignal(object, object, object)

    def __init__(
        self,
        parameters: InputParameters,
        parent: QObject | None = None,
        *,
        plugins: Iterable[SessionTransactionPlugin] = (),
    ) -> None:
        super().__init__(parent)
        self._initial = parameters.copy(copy_values=True)
        self._working = parameters.copy(copy_values=True)
        self._plugins = tuple(plugins)
        # Non-serialized field values belong to editing state. Commands retain
        # them with the parameter snapshot, including across history branches.
        self._dormant: dict[DormantKey, Any] = {}
        self._modified = False
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)

    @property
    def task_name(self) -> str:
        return self._working.task_name

    @property
    def working_parameters(self) -> InputParameters:
        """Borrow the live working parameters for read-only inspection.

        This property does not copy. Callers must not mutate the returned object:
        edits would bypass session transactions, notifications and plugins, and
        undo commands may retain the same object as a history snapshot. Prefer
        :meth:`option` and :meth:`value` for ordinary reads, session mutation
        methods for edits, and :meth:`result` when an independently mutable copy
        is required.
        """
        return self._working

    def result(self) -> InputParameters:
        """Return an independently mutable copy of the current parameters."""
        return self._working.copy(copy_values=True)

    def fork(self, parent: QObject | None = None) -> "InputParametersSession":
        """Create an independent session with the complete current edit state."""
        session = InputParametersSession(
            self._working,
            parent,
            plugins=self._plugins,
        )
        session._dormant = deepcopy(self._dormant)
        return session

    def option(self, path: InputParameterPath) -> Any:
        return resolve_option(self._working, path)

    def value(self, path: InputParameterPath) -> Any:
        """Read the complete option, including global and per-type overrides."""
        return self.option(path)(all_values=True)

    def display_value(self, path: InputParameterPath, index: int | None = None) -> Any:
        """Return an active component or its non-serialized displayed value."""
        value = self.value(path)
        if index is None:
            return value
        try:
            if value is not None and len(value) > index:
                return value[index]
        except (TypeError, IndexError):
            pass
        return self._dormant.get((path, index))

    def history_description(self, *, undo: bool) -> str:
        """Describe the next history command, with old/new values for its tooltip."""
        stack = self.undo_stack
        available = stack.canUndo() if undo else stack.canRedo()
        if not available:
            return "Nothing to undo" if undo else "Nothing to redo"
        command = stack.command(stack.index() - 1 if undo else stack.index())
        return command.description(undo=undo)

    def is_changed(self, path: InputParameterPath) -> bool:
        left = resolve_option(self._initial, path)(all_values=True)
        current = resolve_option(self._working, path)
        right = current(all_values=True)
        return not _option_values_equal(current._definition.type, right, left)

    def changed_paths(self, paths: Iterable[InputParameterPath]) -> set[InputParameterPath]:
        return {path for path in paths if self.is_changed(path)}

    def is_modified(self) -> bool:
        return not _parameters_equal(self._initial, self._working)

    def set_value(
        self,
        path: InputParameterPath,
        value: Any,
        *,
        source_page: str | None = None,
        text: str | None = None,
    ) -> bool:
        return self.mutate(
            lambda candidate: resolve_option(candidate, path).set(value),
            text=text or f"Change {'.'.join(path)}",
            source_page=source_page,
            path=path,
        )

    def mutate(
        self,
        callback: Callable[[InputParameters], Any],
        *,
        text: str,
        source_page: str | None = None,
        path: InputParameterPath | None = None,
        field_index: int | None = None,
    ) -> bool:
        """Apply a compound edit to a copy and record it as one command.

        The callback may update several dependent options. Exceptions propagate
        without installing the candidate; an unchanged candidate adds no command.
        Return whether a command was added. Page/path/index identify the field
        to reveal on undo or redo, not a separate store of parameter values.
        """
        candidate = self._working.copy(copy_values=True)
        callback(candidate)
        return self._push(
            candidate,
            text=text,
            source_page=source_page,
            path=path,
            field_index=field_index,
        )

    def replace_parameters(
        self,
        parameters: InputParameters,
        *,
        text: str = "Replace input parameters",
        source_page: str | None = None,
    ) -> bool:
        """Install same-schema serialized input as one undoable full replacement.

        The effective task may change when one schema represents a task family
        (currently BSFEK/BSFKK). Dormant values are session-only editing state and
        therefore do not belong to a newly loaded/reparsed ``InputParameters``
        object. A full replacement starts with empty dormant state; undo still
        restores the complete previous snapshot. Use :meth:`replace_from_session`
        when importing another editing session whose dormant state is intentionally
        part of the transfer.
        """
        expected = self._working.definition_name
        actual = parameters.definition_name
        if actual.casefold() != expected.casefold():
            raise ValueError(
                f"Expected {expected.upper()} input-parameter schema, "
                f"got {actual.upper()}."
            )
        candidate = parameters.copy(copy_values=True)
        return self._push(
            candidate,
            text=text,
            source_page=source_page,
            path=None,
            initial_dormant={},
        )

    def replace_from_session(
        self,
        session: "InputParametersSession",
        *,
        text: str = "Replace input parameters",
        source_page: str | None = None,
    ) -> bool:
        """Import another session's complete state as one undoable command.

        The source session has already applied its transaction plugins. Its
        dormant state is therefore installed together with its parameters
        without applying the plugins a second time. The two sessions must share
        one input-parameter schema, while their effective tasks may differ.
        """
        parameters = session.result()
        expected = self._working.definition_name
        actual = parameters.definition_name
        if actual.casefold() != expected.casefold():
            raise ValueError(
                f"Expected {expected.upper()} input-parameter schema, "
                f"got {actual.upper()}."
            )
        return self._push_snapshot(
            parameters,
            deepcopy(session._dormant),
            text=text,
            source_page=source_page,
            path=None,
        )

    def _push(
        self,
        candidate: InputParameters,
        *,
        text: str,
        source_page: str | None,
        path: InputParameterPath | None,
        field_index: int | None = None,
        initial_dormant: dict[DormantKey, Any] | None = None,
    ) -> bool:
        dormant = deepcopy(
            self._dormant if initial_dormant is None else initial_dormant
        )
        for plugin in self._plugins:
            plugin.apply(self._working, candidate, dormant)
        return self._push_snapshot(
            candidate,
            dormant,
            text=text,
            source_page=source_page,
            path=path,
            field_index=field_index,
        )

    def _push_snapshot(
        self,
        candidate: InputParameters,
        dormant: dict[DormantKey, Any],
        *,
        text: str,
        source_page: str | None,
        path: InputParameterPath | None,
        field_index: int | None = None,
    ) -> bool:
        if (
            _parameters_equal(candidate, self._working)
            and values_equal(dormant, self._dormant)
        ):
            return False
        before = _SessionSnapshot(self._working, deepcopy(self._dormant))
        after = _SessionSnapshot(candidate, deepcopy(dormant))
        command = _ReplaceParametersCommand(
            self,
            before,
            after,
            text=text,
            source_page=source_page,
            path=path,
            field_index=field_index,
        )
        self.undo_stack.push(command)
        return True

    def _install(
        self,
        snapshot: _SessionSnapshot,
        path: InputParameterPath | None,
        *,
        reset: bool = False,
    ) -> None:
        """Install an immutable-by-convention snapshot and notify all editors."""
        # Snapshots placed on the undo stack are never mutated: every user edit
        # starts from a fresh copy. Reusing the snapshot here is therefore safe.
        changes = tuple(_changed_values(self._working, snapshot.parameters))
        self._working = snapshot.parameters
        self._dormant = snapshot.dormant
        self.editApplied.emit(changes, reset)
        if path is not None:
            self.valueChanged.emit(path)
        self.parametersReplaced.emit()
        modified = self.is_modified()
        if modified != self._modified:
            self._modified = modified
            self.modifiedChanged.emit(modified)


def default_input_parameter_plugins() -> tuple[SessionTransactionPlugin, ...]:
    """Return the standard transaction policy shared by all input editors."""
    from guy4ase.gui.input_parameters.single_site_contour import (
        SingleSiteContourPlugin,
    )

    return (SingleSiteContourPlugin(),)


def create_input_parameters_session(
    parameters: InputParameters,
    parent: QObject | None = None,
) -> InputParametersSession:
    """Create an editing session with the application's standard policy."""
    return InputParametersSession(
        parameters,
        parent,
        plugins=default_input_parameter_plugins(),
    )
