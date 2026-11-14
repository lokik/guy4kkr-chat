"""Compound controls used only by the guided BSF task."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
)

from ase2sprkkr_gui.gui.input_parameters.bsf import (
    EK,
    bsf_mode,
    select_path,
    set_energy_points,
)
from ase2sprkkr_gui.gui.input_parameters.keyword_choices import keyword_items
from ase2sprkkr_gui.gui.misc.tables import fit_table_height
from ase2sprkkr_gui.gui.widgets.input_parameters.value_editor import (
    ParameterValueEditorWidget,
)
from ase2sprkkr_gui.gui.widgets.numeric_table import (
    CoordinateDelegate,
    CoordinateTable,
    coordinate_value,
)


class BsfMeshEditor(ParameterValueEditorWidget):
    """Edit BSF E-k/k-k mode and the main energy sampling as one value."""

    dependencies = (("ENERGY", "NE"), ("TASK", "KPATH"))
    full_width = False
    help_text = (
        "NE = 1: k–k map at fixed energy; NE > 1: E–k path. "
        "Switching resets mode-specific settings (undoable)."
    )

    def __init__(self, binding, placement, atoms=None, parent=None):
        super().__init__(parent)
        self.binding = binding
        self.placement = placement
        self.atoms = atoms
        self._refreshing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("E–k: energy range along a path", EK)
        self.mode_combo.addItem("k–k: plane at fixed energy", "KK")
        self.energy_count = QSpinBox(self)
        self.energy_count.setRange(1, 100000)
        self.energy_count.setPrefix("Energy points: ")
        self.energy_count.setKeyboardTracking(False)
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.energy_count)
        self.setMinimumHeight(
            self.mode_combo.sizeHint().height()
            + self.energy_count.sizeHint().height()
            + layout.spacing()
        )

        self.mode_combo.currentIndexChanged.connect(self._select_mode)
        self.energy_count.editingFinished.connect(self.commit)

    def _set_points(self, points: int) -> bool:
        try:
            self.binding.mutate(
                lambda parameters: set_energy_points(parameters, points, atoms=self.atoms),
                path=self.placement.path,
                field_index=0,
                text="Change BSF mode / energy points",
            )
        except Exception as exc:
            self.validationChanged.emit(str(exc))
            return False
        self.validationChanged.emit("")
        return True

    def _select_mode(self) -> None:
        if not self._refreshing:
            self._set_points(200 if self.mode_combo.currentData() == EK else 1)

    def commit(self) -> bool:
        if self._refreshing or not self.isEnabled():
            return True
        return self._set_points(self.energy_count.value())

    def refresh(self) -> None:
        self._refreshing = True
        try:
            values = self.binding.value_at(self.placement.path)
            points = int(values[self.placement.index or 0])
            mode = EK if bsf_mode(self.binding.parameters) == EK else "KK"
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(mode))
            self.energy_count.setValue(points)
            self.energy_count.setEnabled(points > 1)
        finally:
            self._refreshing = False

    def focus_for_history(self, _path, _index) -> None:
        self.mode_combo.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_editor_tooltip(self, text: str) -> None:
        self.setToolTip(text)
        self.mode_combo.setToolTip(text)
        self.energy_count.setToolTip(text)


class BsfKPathEditor(ParameterValueEditorWidget):
    """Select an atom-dependent predefined path or edit a custom path."""

    # Additional input beyond placement.paths: KA determines the custom-path
    # summary. Mode transitions that replace KPATH already touch its own path.
    dependencies = (("TASK", "KA"),)

    def __init__(self, binding, placement, atoms=None, parent=None):
        super().__init__(parent)
        self.binding = binding
        self.placement = placement
        self.atoms = atoms
        self._refreshing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.path_combo = QComboBox(self)
        for value, description in keyword_items(
            binding.option, atoms=atoms
        ):
            if value is None:
                label = description
            elif description:
                label = f"{value}: {description}"
            else:
                label = f"Predefined {value}"
            self.path_combo.addItem(label, value)
            if description:
                self.path_combo.setItemData(
                    self.path_combo.count() - 1,
                    description,
                    Qt.ItemDataRole.ToolTipRole,
                )
        self.path_combo.view().setMinimumWidth(600)
        self.path_summary = QLabel(self)
        self.path_edit = QPushButton("Custom k-path…", self)
        row.addWidget(self.path_combo, 1)
        row.addWidget(self.path_edit)
        layout.addLayout(row)
        layout.addWidget(self.path_summary)
        self.setMinimumHeight(
            max(self.path_combo.sizeHint().height(), self.path_edit.sizeHint().height())
            + self.path_summary.sizeHint().height()
            + layout.spacing()
        )
        self.setFocusProxy(self.path_combo)

        self.path_combo.currentIndexChanged.connect(self._select_predefined_path)
        self.path_edit.clicked.connect(self._edit_custom_path)

    def _edit_custom_path(self) -> None:
        parent = self.window()
        if self.atoms is None:
            QMessageBox.warning(parent, "K-path", "A structure is required to edit the Brillouin-zone path.")
            return
        try:
            self.binding.mutate(
                lambda parameters: parameters.TASK.k_path_gui(self.atoms, parent=parent),
                text="Edit custom K-path",
                path=self.placement.path,
            )
        except Exception as error:
            QMessageBox.critical(parent, "K-path Error", str(error))

    def _select_predefined_path(self) -> None:
        if self._refreshing:
            return
        value = self.path_combo.currentData()
        try:
            self.binding.mutate(
                lambda parameters: select_path(parameters, value),
                path=self.placement.path,
                text=(
                    "Select custom K-path"
                    if value is None
                    else "Select predefined K-path"
                ),
            )
        except Exception as exc:
            self.validationChanged.emit(str(exc))
            return
        self.validationChanged.emit("")

    def refresh(self) -> None:
        self._refreshing = True
        try:
            value = self.binding.value_at(self.placement.path)
            self._set_combo_value(value)
            self.path_edit.setEnabled(value is None)
            if value is not None:
                summary = self.path_combo.currentText()
            else:
                try:
                    count = len(self.binding.value_at(("TASK", "KA")))
                    summary = f"Custom path, {count} segment(s)"
                except (KeyError, TypeError):
                    summary = "No path selected"
            self.path_summary.setText(summary)
            self.path_summary.setWordWrap(True)
        finally:
            self._refreshing = False

    def _set_combo_value(self, value) -> None:
        """Display imported unavailable values without offering them as choices."""
        for index in range(self.path_combo.count()):
            if self.path_combo.itemData(index) == value:
                self.path_combo.setCurrentIndex(index)
                return
        if value is None:
            self.path_combo.setCurrentIndex(-1)
            self.path_combo.setPlaceholderText("Not set")
            return
        self.path_combo.addItem(f"{value} (current value, unavailable)", value)
        self.path_combo.model().item(self.path_combo.count() - 1).setEnabled(False)
        self.path_combo.setCurrentIndex(self.path_combo.count() - 1)

    def commit(self) -> bool:
        # The combo commits immediately; the modal custom editor is applied by
        # the owning dialog as one session mutation.
        return True

    def focus_for_history(self, _path, _index) -> None:
        self.path_combo.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_editor_tooltip(self, text: str) -> None:
        self.setToolTip(text)
        for widget in (self.path_combo, self.path_summary, self.path_edit):
            widget.setToolTip(text)


class BsfVectorsEditor(ParameterValueEditorWidget):
    """Edit BSF path segments or the plane origin as one atomic control.

    The table is an editing buffer, refreshed from the session on undo/redo.
    Invalid drafts remain visible until corrected or a session refresh replaces
    them; display rounding never changes the values committed to the session.
    """

    # Additional inputs beyond placement.paths (KA and related KE).
    dependencies = (("ENERGY", "NE"), ("TASK", "KPATH"))
    full_width = True

    def __init__(self, binding, placement, atoms=None, parent=None):
        del atoms
        super().__init__(parent)
        self.binding = binding
        self.placement = placement
        self._refreshing = False
        self._ek = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = CoordinateTable(self)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.delegate = CoordinateDelegate(self.table)
        self.delegate.invalid.connect(self.validationChanged)
        self.table.setItemDelegate(self.delegate)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.copyRequested.connect(self.copy)
        self.table.pasteRequested.connect(self.paste)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        self.add_button = self._button(row, "Add segment", self.add_segment)
        self.remove_button = self._button(row, "Remove", self.remove_segments)
        self.up_button = self._button(row, "↑", lambda: self.move_segment(-1))
        self.up_button.setToolTip("Move selected segment up")
        self.down_button = self._button(row, "↓", lambda: self.move_segment(1))
        self.down_button.setToolTip("Move selected segment down")
        self.clear_button = self._button(row, "Default origin", self.clear_origin)
        row.addStretch(1)
        self._button(row, "Copy", self.copy)
        self._button(row, "Paste", self.paste)
        layout.addLayout(row)
        hint = QLabel(
            "Cartesian coordinates in 2π/a. Fractions (1/2) and spreadsheet paste are supported. "
            "Display is shortened; edit or hover for full precision.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.setFocusProxy(self.table)

    def _button(self, layout, text, callback):
        button = QPushButton(text, self)
        button.setAutoDefault(False)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def refresh(self) -> None:
        self._ek = bsf_mode(self.binding.parameters) == EK
        starts = self.binding.value_at(("TASK", "KA"))
        ends = self.binding.value_at(("TASK", "KE")) if self._ek else None
        count = (
            max(len(starts) if starts is not None else 0, len(ends) if ends is not None else 0)
            if self._ek
            else 1
        )
        rows = []
        for index in range(count):
            start = list(starts[index]) if starts is not None and index < len(starts) else [None] * 3
            end = list(ends[index]) if ends is not None and index < len(ends) else [None] * 3
            rows.append(start + end if self._ek else start)
        self._show_rows(rows)
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            button.setVisible(self._ek)
        self.clear_button.setVisible(not self._ek)

    def _show_rows(self, rows) -> None:
        """Replace the table draft without committing or emitting cell edits."""
        self._refreshing = True
        try:
            self.table.setColumnCount(6 if self._ek else 3)
            headers = (
                [f"Start {axis}" for axis in ("kx", "ky", "kz")]
                + [f"End {axis}" for axis in ("kx", "ky", "kz")]
                if self._ek
                else ["kx", "ky", "kz"]
            )
            self.table.setHorizontalHeaderLabels(headers)
            self.table.setRowCount(len(rows))
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    item = QTableWidgetItem()
                    if value is not None:
                        item.setData(Qt.ItemDataRole.EditRole, value)
                        item.setToolTip(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, column, item)
            self.add_button.setEnabled(len(rows) < 9)
            fit_table_height(self.table)
        finally:
            self._refreshing = False

    def _rows(self):
        return [
            [self.table.item(row, column).data(Qt.ItemDataRole.EditRole) for column in range(self.table.columnCount())]
            for row in range(self.table.rowCount())
        ]

    def _apply(self, text, row=0, column=0) -> bool:
        """Parse all cells and commit KA/KE together, retaining invalid drafts."""
        try:
            rows = [[coordinate_value(value) for value in values] for values in self._rows()]
            updates = {"KA": [values[:3] for values in rows] or None}
            if self._ek:
                updates["KE"] = [values[3:] for values in rows] or None
            path = ("TASK", "KE" if column >= 3 else "KA")
            self.binding.mutate(
                lambda parameters: parameters.TASK.set(updates),
                text=text,
                path=path,
                field_index=row,
            )
            self.validationChanged.emit("")
            if self.table.rowCount():
                self.table.setCurrentCell(min(row, self.table.rowCount() - 1), column)
            return True
        except (ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
            self.validationChanged.emit(str(exc))
            return False

    def _cell_changed(self, item) -> None:
        if not self._refreshing:
            text = "Edit K-path coordinate" if self._ek else "Edit plane origin"
            self._apply(text, item.row(), item.column())

    def add_segment(self) -> None:
        rows = self._rows()
        if len(rows) >= 9:
            self.validationChanged.emit("A path can contain at most 9 segments.")
            return
        index = self.table.currentRow() + 1 if self.table.currentRow() >= 0 else len(rows)
        start = rows[index - 1][3:].copy() if index else [0.0, 0.0, 0.0]
        try:
            end = [coordinate_value(value) for value in start]
            end[0] += 1.0
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            self.validationChanged.emit(str(exc))
            return
        rows.insert(index, start + end)
        self._show_rows(rows)
        self._apply("Add K-path segment", index)

    def remove_segments(self) -> None:
        selected = {index.row() for index in self.table.selectedIndexes()}
        if not selected:
            return
        rows = [row for index, row in enumerate(self._rows()) if index not in selected]
        self._show_rows(rows)
        self._apply("Remove K-path segments", min(selected))

    def move_segment(self, offset) -> None:
        row = self.table.currentRow()
        target = row + offset
        rows = self._rows()
        if row < 0 or not 0 <= target < len(rows):
            return
        rows[row], rows[target] = rows[target], rows[row]
        self._show_rows(rows)
        self._apply("Move K-path segment", target)

    def clear_origin(self) -> None:
        self.binding.set_path_value(
            ("TASK", "KA"),
            None,
            text="Use default plane origin",
        )
        self.validationChanged.emit("")

    def copy(self) -> None:
        """Copy the selection rectangle as full-precision tab-separated data."""
        selected = self.table.selectedIndexes()
        if not selected:
            return
        rows = self._rows()
        first_row, last_row = min(i.row() for i in selected), max(i.row() for i in selected)
        first_column, last_column = min(i.column() for i in selected), max(i.column() for i in selected)
        text = "\n".join(
            "\t".join("" if value is None else str(value) for value in row[first_column:last_column + 1])
            for row in rows[first_row:last_row + 1]
        )
        QApplication.clipboard().setText(text)

    def paste(self) -> None:
        """Insert a rectangular numeric block at the active cell as one edit."""
        try:
            lines = QApplication.clipboard().text().strip().splitlines()
            if not lines:
                return
            values = [
                [coordinate_value(value) for value in (line.split("\t") if "\t" in line else line.split())]
                for line in lines
            ]
            if not values[0] or any(len(row) != len(values[0]) for row in values):
                raise ValueError("Paste a rectangular block of coordinates.")
            row = max(0, self.table.currentRow())
            column = max(0, self.table.currentColumn())
            if (
                column + len(values[0]) > self.table.columnCount()
                or row + len(values) > (9 if self._ek else 1)
            ):
                raise ValueError("Pasted coordinates exceed the table size (at most 9 segments).")
            rows = self._rows()
            while len(rows) < row + len(values):
                rows.append([None] * self.table.columnCount())
            for index, data in enumerate(values):
                rows[row + index][column:column + len(data)] = data
            self._show_rows(rows)
            self._apply("Paste K-path coordinates", row, column)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            self.validationChanged.emit(str(exc))

    def commit(self) -> bool:
        # Cells commit atomically as they are edited; an invalid draft is
        # already retained and reported through validationChanged.
        return True

    def focus_for_history(self, path, index) -> None:
        if self.table.rowCount():
            column = 3 if path[-1] == "KE" and self._ek else 0
            self.table.setCurrentCell(min(index or 0, self.table.rowCount() - 1), column)
        self.table.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_editor_tooltip(self, text: str) -> None:
        self.setToolTip(text)
        self.table.setToolTip(text)
