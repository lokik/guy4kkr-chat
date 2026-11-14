"""Grammar-aware scalar editors shared independently of dialog layout."""
from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any

import numpy as np
from ase2sprkkr.common.grammar_types import (
    Array,
    Boolean,
    Flag,
    Integer,
    Keyword,
    Real,
    SetOf,
    String,
    Table,
)
from ase2sprkkr.common.warnings import DataValidityError
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QWidget

from ase2sprkkr_gui.gui.input_parameters.defaults import default_text
from ase2sprkkr_gui.gui.input_parameters.field_binding import FieldValue
from ase2sprkkr_gui.gui.input_parameters.keyword_choices import (
    keyword_allows_unset,
    keyword_items,
)
from ase2sprkkr_gui.gui.input_parameters.specs.schema import FieldPlacement
from ase2sprkkr_gui.gui.widgets.input_parameters.commit import (
    EditorCommit,
    EditorValidationError,
)
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import ParameterValueEditor
from ase2sprkkr_gui.gui.widgets.nullable_spinbox import (
    NullableDoubleSpinBox,
    NullableSpinBox,
)


def coalesce(*args):
    for value in args:
        if value is not None:
            return value
    return None


def _first(value: Any, fallback: Any = None) -> Any:
    if isinstance(value, np.ndarray):
        return value.flat[0] if value.size else fallback
    if isinstance(value, (list, tuple)):
        return value[0] if value else fallback
    return fallback if value is None else value


def _plain_literal(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _plain_literal(value.tolist())
    if isinstance(value, dict):
        return {key: _plain_literal(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_literal(child) for child in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _stringify_value(grammar_type: Any, value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(grammar_type, (Array, SetOf)):
        return repr(_plain_literal(value))
    if isinstance(value, np.ndarray) and not isinstance(grammar_type, Table):
        return "<Data>"
    try:
        return str(grammar_type.string(value))
    except Exception:
        try:
            return str(value)
        except Exception:
            return fallback


def _python_input_value(text: str) -> Any:
    """Decode Python-like values, treating ase2sprkkr brace arrays as lists."""
    node = ast.parse(text, mode="eval").body
    if isinstance(node, ast.Set):
        node = ast.fix_missing_locations(ast.List(elts=node.elts, ctx=ast.Load()))
    return ast.literal_eval(ast.Expression(body=node))


class _ScalarValueEditor(ParameterValueEditor):
    """Lifecycle implementation shared by concrete scalar Qt controls."""

    def bind(
        self,
        read_state: Callable[[], FieldValue],
        apply_value: Callable[[Any], None],
    ) -> None:
        self._read_state = read_state
        self._apply_value = apply_value
        self._commit = EditorCommit(self, self._draft, self._apply_draft)
        self.refresh()

    @property
    def validationChanged(self):
        return self._commit.validationChanged

    def refresh(self) -> None:
        with QSignalBlocker(self):
            self._show_state(self._read_state())
        self._commit.refresh()

    def commit(self, *_args: Any) -> bool:
        return self._commit.commit()

    def _draft(self) -> Any:
        raise NotImplementedError

    def _apply_user_value(self, value: Any) -> None:
        """Translate only expected backend data validation into editor feedback."""
        try:
            self._apply_value(value)
        except DataValidityError as error:
            raise EditorValidationError(str(error)) from error

    def _apply_draft(self, value: Any) -> None:
        self._apply_user_value(value)
        self._sync_display()

    def _sync_display(self) -> None:
        """Re-read the authoritative value after a successful callback."""
        with QSignalBlocker(self):
            self._show_state(self._read_state())

    def _show_state(self, state: FieldValue) -> None:
        raise NotImplementedError


class IntegerEditor(NullableSpinBox, _ScalarValueEditor):
    """Nullable integer input with backend-default placeholder support."""

    def __init__(self, *, nullable: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nullable = nullable

    @classmethod
    def from_binding(cls, binding, placement, *, atoms=None, parent=None):
        del atoms
        nullable = binding.allows_unset
        editor = cls(nullable=nullable, parent=parent)
        grammar_type = binding.value_type
        minimum = coalesce(placement.minimum, getattr(grammar_type, "min", None), -2147483647)
        maximum = coalesce(placement.maximum, getattr(grammar_type, "max", None), 2147483647)
        step = placement.step or 1
        lower = minimum - int(step) if nullable else minimum
        editor.setRange(lower, maximum)
        editor.setSingleStep(int(step))
        if placement.special_value_text:
            editor.setSpecialValueText(placement.special_value_text)
        if nullable:
            editor.set_unset_value(editor.minimum())
        editor.setReadOnly(binding.read_only)
        editor.setKeyboardTracking(False)
        editor.bind(binding.read, binding.set_value)
        editor.valueChanged.connect(editor.commit)
        return editor

    def _draft(self) -> int | None:
        if (
            self._nullable
            and not self.cleanText().strip()
            and not self.is_default_display()
        ):
            return None
        value = int(self.value())
        return None if self._nullable and value == int(self.minimum()) else value

    def _show_state(self, state: FieldValue) -> None:
        fallback = self.minimum() if self._nullable else 0
        value = int(_first(state.value, fallback))
        self.setValue(value)
        placeholder = default_text(state.default)
        self.lineEdit().setPlaceholderText(placeholder)
        if state.implicit_default and state.value is not None:
            self.show_default(value, placeholder)


class RealEditor(NullableDoubleSpinBox, _ScalarValueEditor):
    """Nullable real input with backend-default placeholder support."""

    def __init__(self, *, nullable: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nullable = nullable

    @classmethod
    def from_binding(cls, binding, placement, *, atoms=None, parent=None):
        del atoms
        nullable = binding.allows_unset
        editor = cls(nullable=nullable, parent=parent)
        grammar_type = binding.value_type
        lo = coalesce(placement.minimum, getattr(grammar_type, "min", None), -1e16)
        hi = coalesce(placement.maximum, getattr(grammar_type, "max", None), 1e16)
        step = placement.step or 0.1
        editor.setDecimals(placement.decimals)
        editor.setSingleStep(float(step))
        editor.setRange(lo - float(step) if nullable else lo, hi)
        if placement.special_value_text:
            editor.setSpecialValueText(placement.special_value_text)
        if nullable:
            editor.set_unset_value(editor.minimum())
        editor.setReadOnly(binding.read_only)
        editor.setKeyboardTracking(False)
        editor.bind(binding.read, binding.set_value)
        editor.valueChanged.connect(editor.commit)
        return editor

    def _draft(self) -> float | None:
        if (
            self._nullable
            and not self.cleanText().strip()
            and not self.is_default_display()
        ):
            return None
        value = float(self.value())
        return None if self._nullable and value == float(self.minimum()) else value

    def _show_state(self, state: FieldValue) -> None:
        fallback = self.minimum() if self._nullable else 0.0
        value = float(_first(state.value, fallback))
        self.setValue(value)
        placeholder = default_text(state.default)
        self.lineEdit().setPlaceholderText(placeholder)
        if state.implicit_default and state.value is not None:
            self.show_default(value, placeholder)


class BooleanEditor(QCheckBox, _ScalarValueEditor):
    """Boolean/flag value editor."""

    @classmethod
    def from_binding(cls, binding, placement, *, atoms=None, parent=None):
        del placement, atoms
        editor = cls(parent)
        editor.setEnabled(not binding.read_only)
        editor.bind(binding.read, binding.set_value)
        editor.toggled.connect(editor.commit)
        return editor

    def _draft(self) -> bool:
        return self.isChecked()

    def _show_state(self, state: FieldValue) -> None:
        self.setChecked(bool(state.value))


class ChoiceEditor(QComboBox, _ScalarValueEditor):
    """Choice editor which preserves imported values absent from the schema."""

    def __init__(
        self,
        *,
        normalize: Callable[[FieldValue], Any],
        unavailable_unknown: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._normalize = normalize
        self._unavailable_unknown = unavailable_unknown

    @classmethod
    def from_binding(cls, binding, placement, *, atoms=None, parent=None):
        del atoms
        editor = cls(
            normalize=lambda state: state.value,
            unavailable_unknown=False,
            parent=parent,
        )
        for index, choice in enumerate(placement.choices):
            editor.addItem(choice.label, choice.value)
            editor.setItemData(index, choice.label, Qt.ItemDataRole.ToolTipRole)
        editor.setEnabled(not binding.read_only)
        editor.bind(binding.read, binding.set_value)
        editor.currentIndexChanged.connect(editor.commit)
        return editor

    def _draft(self) -> Any:
        return self.currentData()

    def _show_state(self, state: FieldValue) -> None:
        value = self._normalize(state)
        for index in range(self.count()):
            if self.itemData(index) == value:
                self.setCurrentIndex(index)
                return
        if value is None:
            self.setCurrentIndex(-1)
            self.setPlaceholderText("Not set")
            return
        label = (
            f"{value} (current value, unavailable)"
            if self._unavailable_unknown
            else str(value)
        )
        self.addItem(label, value)
        if self._unavailable_unknown:
            self.model().item(self.count() - 1).setEnabled(False)
        self.setCurrentIndex(self.count() - 1)


class TextEditor(QLineEdit, _ScalarValueEditor):
    """Text/literal fallback editor using the input grammar for conversion."""

    def __init__(
        self,
        grammar_type: Any,
        *,
        nullable: bool,
        allow_empty: bool,
        value_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._grammar_type = grammar_type
        self._nullable = nullable
        self._allow_empty = allow_empty
        self._value_name = value_name

    literal = False

    @classmethod
    def from_binding(cls, binding, placement, *, atoms=None, parent=None):
        del atoms
        editor = cls(
            binding.value_type,
            nullable=binding.allows_unset,
            allow_empty=binding.allow_empty,
            value_name=placement.label or "Value",
            parent=parent,
        )
        editor.setReadOnly(binding.read_only)
        editor.bind(binding.read, binding.set_value)
        editor.editingFinished.connect(editor.commit)
        return editor

    def _draft(self) -> str:
        return self.text().strip()

    def _apply_draft(self, text: str) -> None:
        if not text:
            if self._allow_empty:
                return
            if self._nullable:
                self._apply_user_value(None)
                self._sync_display()
                return
            raise EditorValidationError(f"{self._value_name} must have a value")

        try:
            if self.literal:
                value = ast.literal_eval(text)
            else:
                try:
                    value = _python_input_value(text)
                except (SyntaxError, ValueError):
                    value = text
            value = self._grammar_type.convert(value)
            self._grammar_type.validate(value)
        except (SyntaxError, TypeError, ValueError) as error:
            raise EditorValidationError(str(error)) from error

        self._apply_user_value(value)
        self._sync_display()

    def _show_state(self, state: FieldValue) -> None:
        value = None if state.implicit_default else state.value
        if self.literal and value is not None:
            text = repr(_plain_literal(value))
        else:
            text = _stringify_value(
                self._grammar_type,
                value,
                fallback="" if value is None else str(value),
            )
        self.setText(text)
        self.setPlaceholderText(default_text(state.default))


class LiteralEditor(TextEditor):
    """Python-literal presentation for structured option values."""

    literal = True


class KeywordEditor(ChoiceEditor):
    """Keyword choices supplied by the option grammar and current atoms."""

    @classmethod
    def from_binding(cls, binding, placement, *, atoms=None, parent=None):
        grammar_type = binding.value_type
        allows_unset = keyword_allows_unset(binding.option, grammar_type)
        editor = cls(
            normalize=lambda state: (
                None
                if allows_unset and state.explicit is False
                else state.value
            ),
            unavailable_unknown=True,
            parent=parent,
        )
        labels = {choice.value: choice.label for choice in placement.choices}
        for index, (keyword, info) in enumerate(
            keyword_items(binding.option, value_type=grammar_type, atoms=atoms)
        ):
            label = labels.get(
                keyword,
                info if keyword is None else f"{keyword}: {info}" if info else str(keyword),
            )
            editor.addItem(label, keyword)
            editor.setItemData(index, label, Qt.ItemDataRole.ToolTipRole)
        editor.setEnabled(not binding.read_only)
        if placement.descriptions:
            editor.view().setMinimumWidth(560)
        editor.bind(binding.read, binding.set_value)
        editor.currentIndexChanged.connect(editor.commit)
        return editor
