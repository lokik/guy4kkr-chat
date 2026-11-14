"""Global and per-atomic-type editors for DEFAULTDICT scaling options."""
import numpy as np
from ase2sprkkr.common.grammar_types import Array
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyle,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from ase2sprkkr_gui.gui.misc.tables import fit_table_height
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import (
    ParameterValueEditorWidget,
)
from ase2sprkkr_gui.gui.widgets.numeric_table import CoordinateDelegate, coordinate_value


class RelativisticScalingEditor(ParameterValueEditorWidget):
    """Rows are the global setting and explicit type indices (not site indices).

    A scalar/one-element array applies to all orbitals. Array-capable option
    types expose s, p, d, f, ... columns without rewriting values on refresh.
    """
    def __init__(self, binding, placement, atoms=None, parent=None):
        del atoms
        super().__init__(parent)
        self.binding, self.path = binding, placement.path
        self._refreshing = False
        self._keys = []
        self._value_columns = 1
        self.orbital_resolved = isinstance(binding.value_type, Array)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(self)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegate(CoordinateDelegate(self.table))
        self.table.itemChanged.connect(self.commit)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.type_index = QSpinBox(self)
        self.type_index.setRange(1, 999999)
        self.type_index.setPrefix("Type ")
        self.type_index.setToolTip("Atomic-type index in the potential file (not an atom/site index).")
        buttons.addWidget(self.type_index)
        self.add_button = QPushButton("Add", self)
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self.add_type)
        buttons.addWidget(self.add_button)
        self.remove_button = QPushButton("Remove selected type", self)
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(lambda _checked=False: self.remove_type())
        buttons.addWidget(self.remove_button)
        layout.addLayout(buttons)
        hint = QLabel("Global applies to all atomic types. Add type-specific settings using their potential-file indices.", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.setFocusProxy(self.table)

    def refresh(self):
        """Render defaults and broadcast short orbital arrays without expanding storage."""
        self._refreshing = True
        try:
            values = self.binding.read().value or {}
            self._keys = ["def"] + sorted(key for key in values if key != "def")
            columns = 1
            if self.orbital_resolved:
                columns = max(4, max((np.size(value) for value in values.values()), default=1))
                try:
                    columns = max(columns, int(np.max(self.binding.value_at(("SITES", "NL")))))
                except (KeyError, TypeError, ValueError):
                    pass
            self._value_columns = columns
            self.table.setColumnCount(columns + 1)
            orbitals = ("s", "p", "d", "f", "g", "h", "i")
            value_headers = (
                [
                    orbitals[i] if i < len(orbitals) else f"l={i}"
                    for i in range(columns)
                ]
                if self.orbital_resolved
                else ["Scale (all orbitals)"]
            )
            self.table.setHorizontalHeaderLabels([*value_headers, ""])
            self.table.horizontalHeader().setSectionResizeMode(
                columns,
                QHeaderView.ResizeMode.ResizeToContents,
            )
            self.table.setRowCount(len(self._keys))
            self.table.setVerticalHeaderLabels(["Global" if key == "def" else f"Type {key}" for key in self._keys])
            for row, key in enumerate(self._keys):
                value = np.atleast_1d(values.get(key, 1.0))
                for column in range(columns):
                    number = float(value[min(column, len(value) - 1)])
                    item = QTableWidgetItem()
                    item.setData(Qt.ItemDataRole.EditRole, number)
                    item.setToolTip(f"{self.path[-1]}{'' if key == 'def' else key}: {number!r}")
                    self.table.setItem(row, column, item)
                if key != "def":
                    remove = QToolButton(self.table)
                    remove.setAutoRaise(True)
                    remove.setIcon(self.style().standardIcon(
                        QStyle.StandardPixmap.SP_DialogCloseButton
                    ))
                    remove.setToolTip(f"Remove type {key}")
                    remove.setAccessibleName(
                        f"Remove {self.path[-1]} value for type {key}"
                    )
                    remove.clicked.connect(
                        lambda _checked=False, type_index=key:
                            self.remove_type(type_index)
                    )
                    self.table.setCellWidget(row, columns, remove)
            fit_table_height(self.table)
            index = 1
            while index in values:
                index += 1
            self.type_index.setValue(index)
        finally:
            self._refreshing = False

    def commit(self, *_args):
        """Commit valid rows together, preserving untouched scalar/array representations."""
        if self._refreshing or not self.isEnabled():
            return True
        try:
            # Keep untouched rows in their original representation, including
            # absent global defaults and short arrays.
            values = dict(self.binding.read().value or {})
            for row, key in enumerate(self._keys):
                cells = [
                    coordinate_value(
                        self.table.item(row, column).data(
                            Qt.ItemDataRole.EditRole
                        )
                    )
                    for column in range(self._value_columns)
                ]
                previous = np.atleast_1d(values.get(key, 1.0))
                if any(value != previous[min(i, len(previous) - 1)] for i, value in enumerate(cells)):
                    values[key] = cells if self.orbital_resolved else cells[0]
            self.binding.set_value(values)
            self.validationChanged.emit("")
            return True
        except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
            self.validationChanged.emit(str(exc))
            return False

    def add_type(self):
        """Commit the draft, then add a unity override or focus an existing type."""
        if not self.commit():
            return
        values = dict(self.binding.read().value or {})
        index = self.type_index.value()
        if index not in values:
            values[index] = [1.0] if self.orbital_resolved else 1.0
            self.binding.set_path_value(
                self.path,
                values,
                text=f"Add {self.path[-1]} for type {index}",
            )
            self.refresh()
        self.table.setCurrentCell(self._keys.index(index), 0)

    def remove_type(self, index=None):
        """Remove the selected explicit override; the global row cannot be removed."""
        if index is None:
            row = self.table.currentRow()
            if row <= 0:
                return
            index = self._keys[row]
        values = dict(self.binding.read().value or {})
        if index not in values:
            return
        del values[index]
        self.binding.set_path_value(
            self.path,
            values,
            text=f"Remove {self.path[-1]} for type {index}",
        )
        self.refresh()
        self.validationChanged.emit("")
