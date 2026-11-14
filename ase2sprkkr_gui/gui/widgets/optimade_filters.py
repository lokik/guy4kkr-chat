from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.online_databases import (
    PropertyFilter,
    PropertyFilterDefinition,
)


class CollapsibleSection(QWidget):
    """A compact section whose contents do not consume space when closed."""

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.toggle = QToolButton(self)
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.toggle.toggled.connect(self._set_open)
        layout.addWidget(self.toggle)

        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 0, 0, 0)
        self.content.setVisible(False)
        layout.addWidget(self.content)
        self._set_open(False)

    def _set_open(self, opened: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow
        )
        self.content.setVisible(opened)


class OptionalIntegerRange(QWidget):
    def __init__(
        self, maximum: int, parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.minimum = self._spin("Min: ", maximum)
        self.maximum = self._spin("Max: ", maximum)
        layout.addWidget(self.minimum)
        layout.addWidget(self.maximum)

    def _spin(self, prefix: str, maximum: int) -> QSpinBox:
        spin = QSpinBox(self)
        spin.setRange(0, maximum)
        spin.setSpecialValueText("Any")
        spin.setPrefix(prefix)
        return spin

    def values(self) -> tuple[Optional[int], Optional[int]]:
        return (
            self.minimum.value() or None,
            self.maximum.value() or None,
        )

    def clear(self) -> None:
        self.minimum.setValue(0)
        self.maximum.setValue(0)


class OptionalDateRange(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.after = QLineEdit(self)
        self.after.setPlaceholderText("From YYYY-MM-DD")
        layout.addWidget(self.after)
        self.before = QLineEdit(self)
        self.before.setPlaceholderText("To YYYY-MM-DD")
        layout.addWidget(self.before)

    def values(self) -> tuple[Optional[date], Optional[date]]:
        return (
            self._value(self.after.text(), "earliest"),
            self._value(self.before.text(), "latest"),
        )

    @staticmethod
    def _value(value: str, label: str) -> Optional[date]:
        value = value.strip()
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"The {label} modification date must use YYYY-MM-DD."
            ) from exc

    def clear(self) -> None:
        self.after.clear()
        self.before.clear()


class ProviderPropertyFilterEditor(QWidget):
    """Build provider-specific conditions from an explicit safe definition."""

    validation_failed = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._definitions: dict[str, PropertyFilterDefinition] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.property_combo = QComboBox(self)
        self.property_combo.currentIndexChanged.connect(
            self._property_changed
        )
        layout.addWidget(self.property_combo)

        condition = QHBoxLayout()
        self.operator_combo = QComboBox(self)
        self.operator_combo.setMinimumWidth(0)
        self.operator_combo.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        condition.addWidget(self.operator_combo)
        self.value_stack = QStackedWidget(self)
        self.value_edit = QLineEdit(self.value_stack)
        self.value_edit.returnPressed.connect(self._add_filter)
        self.value_combo = QComboBox(self.value_stack)
        self.value_combo.setMinimumWidth(0)
        self.value_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.value_combo.setMinimumContentsLength(0)
        self.value_combo.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.value_stack.addWidget(self.value_edit)
        self.value_stack.addWidget(self.value_combo)
        condition.addWidget(self.value_stack, 1)
        self.add_button = QPushButton("Add", self)
        self.add_button.setMinimumWidth(0)
        self.add_button.clicked.connect(self._add_filter)
        condition.addWidget(self.add_button)
        layout.addLayout(condition)

        self.filter_list = QListWidget(self)
        self.filter_list.setMaximumHeight(96)
        layout.addWidget(self.filter_list)
        remove_row = QHBoxLayout()
        remove_row.addStretch(1)
        self.remove_button = QPushButton("Remove selected", self)
        self.remove_button.clicked.connect(self._remove_selected)
        remove_row.addWidget(self.remove_button)
        layout.addLayout(remove_row)

    def set_definitions(
        self, definitions: Sequence[PropertyFilterDefinition]
    ) -> None:
        self.clear()
        self._definitions = {item.key: item for item in definitions}
        self.property_combo.clear()
        for definition in definitions:
            label = definition.label
            if definition.unit:
                label += f" ({definition.unit})"
            self.property_combo.addItem(label, definition.key)
        self.setEnabled(bool(definitions))
        self._property_changed()

    def filters(self) -> tuple[PropertyFilter, ...]:
        return tuple(
            self.filter_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.filter_list.count())
        )

    def clear(self) -> None:
        self.filter_list.clear()
        self.value_edit.clear()

    def _definition(self) -> Optional[PropertyFilterDefinition]:
        return self._definitions.get(str(self.property_combo.currentData()))

    def _property_changed(self) -> None:
        definition = self._definition()
        self.operator_combo.clear()
        self.value_combo.clear()
        if definition is None:
            return
        for operator, label in definition.operators:
            self.operator_combo.addItem(label, operator)
        if definition.choices:
            for label, value in definition.choices:
                self.value_combo.addItem(label, value)
            self.value_stack.setCurrentWidget(self.value_combo)
        else:
            self.value_edit.clear()
            self.value_edit.setPlaceholderText(definition.placeholder)
            self.value_stack.setCurrentWidget(self.value_edit)

    def _add_filter(self) -> None:
        definition = self._definition()
        if definition is None:
            return
        operator = str(self.operator_combo.currentData())
        if definition.choices:
            value = self.value_combo.currentData()
        else:
            value = self.value_edit.text().strip()
            if not value:
                self.validation_failed.emit(
                    f"Enter a value for {definition.label}."
                )
                return
            try:
                if definition.value_type == "integer":
                    value = int(value)
                elif definition.value_type == "float":
                    value = float(value)
            except ValueError:
                self.validation_failed.emit(
                    f"Enter a valid number for {definition.label}."
                )
                return
        criterion = PropertyFilter(definition.key, operator, value)
        operator_label = self.operator_combo.currentText()
        text = f"{definition.label} {operator_label} {value}"
        if definition.unit:
            text += f" {definition.unit}"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, criterion)
        item.setToolTip(text)
        self.filter_list.addItem(item)
        self.value_edit.clear()

    def _remove_selected(self) -> None:
        for item in self.filter_list.selectedItems():
            self.filter_list.takeItem(self.filter_list.row(item))
