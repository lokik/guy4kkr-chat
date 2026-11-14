"""Qt presentation for one element-assignment site."""
from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.ase.element_assignment import (
    AssignmentSite,
    ElementAssignmentDraft,
    OccupancyEntry,
)


class QLetterRow(QWidget):
    """Container for one Wyckoff letter's element rows."""
    glyph_font = QFont()
    glyph_font.setBold(True)
    glyph_font.setPointSize(12)

    def __init__(self, draft: ElementAssignmentDraft,
                 site: AssignmentSite,
                 parent: Optional[QWidget] = None,
                 on_activity: Optional[callable] = None,
                 on_break: Optional[callable] = None,
                 select_element=None,
                 on_validation=None):
        super().__init__(parent)
        self.draft = draft
        self.site = site
        self._select_element = select_element
        self._on_validation = on_validation
        self._on_activity = on_activity
        self._on_break = on_break
        self.rows: list[Dict[str, Any]] = []

        # Two-column layout: left = element assignment, right = positions table
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)

        # Site header (separate line, spans both columns)
        header_w = QWidget(self)
        header_v = QVBoxLayout(header_w)
        header_v.setContentsMargins(0, 0, 0, 0)
        header_v.setSpacing(2)
        line = QFrame(header_w)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        header_v.addWidget(line)
        self.site_label = QLabel()
        f = self.site_label.font()
        f.setBold(True)
        self.site_label.setFont(f)
        header_v.addWidget(self.site_label)
        grid.addWidget(header_w, 0, 0, 1, 2)

        left = QWidget(self)
        left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.vbox = QVBoxLayout(left)
        self.vbox.setContentsMargins(0, 0, 0, 0)

        # Controls row
        controls = QHBoxLayout()
        controls.addStretch(1)
        self.normalize_btn = QPushButton("Normalize")
        self.normalize_btn.clicked.connect(self._normalize)
        controls.addWidget(self.normalize_btn)
        # Break symmetry button (visible only when multiplicity > 1)
        self.break_btn = QPushButton("Break symmetry")
        can_break = site.can_split
        self.break_btn.setVisible(bool(can_break))
        if can_break and callable(self._on_break):
            self.break_btn.clicked.connect(lambda: self._on_break(self.site))
        controls.addWidget(self.break_btn)
        self.vbox.addLayout(controls)

        # Rows area
        self.rows_box = QVBoxLayout()
        self.vbox.addLayout(self.rows_box)

        # Add-row button
        add_row = QHBoxLayout()
        self.add_btn = QPushButton("＋ Add element")
        self.add_btn.clicked.connect(self.add_row)
        add_row.addWidget(self.add_btn)
        self.vbox.addLayout(add_row)

        # Positions table (fractional X/Y/Z per equivalent site)
        # Positions on the right; title omitted (there is a global header above all sites)
        self.positions_group = QGroupBox(self)
        self.positions_group.setTitle("")
        self.positions_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        pos_v = QVBoxLayout(self.positions_group)
        pos_v.setContentsMargins(6, 6, 6, 6)
        self.positions_table = QTableWidget(0, 3, self.positions_group)
        self.positions_table.setHorizontalHeaderLabels(["X", "Y", "Z"])
        self.positions_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.positions_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.positions_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.positions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.positions_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        pos_v.addWidget(self.positions_table)

        pos_btns = QHBoxLayout()
        pos_btns.addStretch(1)
        self.add_pos_btn = QPushButton("＋")
        self.add_pos_btn.setToolTip("Add position")
        self.add_pos_btn.setFixedWidth(34)
        self.add_pos_btn.clicked.connect(self._add_position)
        pos_btns.addWidget(self.add_pos_btn)

        self.del_pos_btn = QPushButton()
        self.del_pos_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.del_pos_btn.setToolTip("Delete selected position")
        self.del_pos_btn.setFixedWidth(34)
        self.del_pos_btn.clicked.connect(self._delete_position)
        pos_btns.addWidget(self.del_pos_btn)

        pos_v.addLayout(pos_btns)

        grid.addWidget(left, 1, 0, alignment=Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.positions_group, 1, 1, alignment=Qt.AlignmentFlag.AlignTop)

        self._pos_spins: list[list[QDoubleSpinBox]] = []

        self.load_site()

    @property
    def label(self):
        return self.site.label

    def load_site(self) -> None:
        """Refresh all controls from the assignment model."""
        self.site_label.setText(f"Site kind {self.site.label}")

        self._refresh_break_button()

        self._rebuild_positions_table()
        self.load_occupancy()
        self._validate_controls_state()
        self._validate_totals()

    def _refresh_break_button(self) -> None:
        self.break_btn.setVisible(bool(self.site.can_split))

    def _rebuild_positions_table(self) -> None:
        positions = self.site.positions
        n_rows = len(positions)
        old_rows = self.positions_table.rowCount()
        self.positions_table.setRowCount(n_rows)
        self._pos_spins = []

        def setup(i, j, spin):
            spin.setProperty("pos_row", i)
            spin.setProperty("pos_col", j)
            spin.valueChanged.connect(lambda v, r=i, c=j: self._on_position_changed(r, c, v))
            spin.installEventFilter(self)
            spin.blockSignals(True)
            try:
                spin.setValue(float(positions[i][j]))
            finally:
                spin.blockSignals(False)

        for i in range(min(old_rows, n_rows)):
            for j in range(3):
                spin = self.positions_table.cellWidget(i, j)
                if isinstance(spin, QDoubleSpinBox):
                    try:
                        spin.valueChanged.disconnect()
                    except TypeError:
                        pass
                    setup(i, j, spin)

        for i in range(old_rows, n_rows):
            spin_row: list[QDoubleSpinBox] = []
            for j in range(3):
                spin = QDoubleSpinBox(self.positions_table)
                spin.setRange(0.0, 1.0)
                spin.setDecimals(4)
                spin.setSingleStep(0.05)
                spin.setAlignment(Qt.AlignmentFlag.AlignRight)
                self.positions_table.setCellWidget(i, j, spin)
                spin_row.append(spin)
                setup(i, j, spin)
            self._pos_spins.append(spin_row)

        header_h = self.positions_table.horizontalHeader().height()
        row_h = self.positions_table.verticalHeader().defaultSectionSize()
        self.positions_table.setMinimumHeight(header_h + n_rows * row_h + 2)
        self.positions_table.setMaximumHeight(header_h + n_rows * row_h + 2)

        # Enable delete only when there is more than one row
        self.del_pos_btn.setEnabled(n_rows > 1)

    def _current_position_row(self) -> int:
        r = self.positions_table.currentRow()
        return int(r) if r is not None and r >= 0 else 0

    def _add_position(self) -> None:
        new_index = self.draft.add_position(self.site)
        self._refresh_break_button()
        self._rebuild_positions_table()
        self.positions_table.setCurrentCell(new_index, 0)
        if callable(self._on_activity):
            self._on_activity(self.label, new_index, True)

    def _delete_position(self) -> None:
        row = self._current_position_row()
        if not self.draft.remove_position(self.site, row):
            return
        self._refresh_break_button()
        self._rebuild_positions_table()

        new_row = min(row, len(self.site.positions) - 1)
        self.positions_table.setCurrentCell(new_row, 0)
        if callable(self._on_activity):
            self._on_activity(self.label, new_row, True)

    def _on_position_changed(self, row: int, col: int, value: float) -> None:
        self.draft.set_position_component(self.site, row, col, value)
        # Ensure preview updates immediately when positions change
        if callable(self._on_activity):
            self._on_activity(self.label, row, True)

    def load_occupancy(self) -> None:
        """Refresh element controls from the model's occupancy entries."""
        # remove existing row widgets
        for r in list(self.rows):
            r['w'].setParent(None)
        self.rows.clear()

        for entry in self.site.occupancies:
            self._add_entry_widget(entry)

    def add_row(self) -> None:
        """Add a blank element row."""
        self._add_entry_widget(self.draft.add_occupancy(self.site))
        self._validate_controls_state()
        self._validate_totals()

    def _add_entry_widget(self, entry: OccupancyEntry) -> None:
        select_element = self._select_element

        row_w = QWidget(self)
        row_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        h = QHBoxLayout(row_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        elem_edit = QLineEdit()
        elem_edit.setPlaceholderText("Element")
        elem_edit.setText(entry.symbol)
        elem_edit.setMaxLength(3)
        elem_edit.setFixedWidth(55)
        label_elem = QLabel("Element")
        label_elem.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h.addWidget(label_elem)
        h.addWidget(elem_edit)

        pick_btn = QPushButton("⚛️")
        pick_btn.setFont(self.glyph_font)
        pick_btn.setToolTip("Pick element")
        pick_btn.setEnabled(select_element is not None)
        pick_btn.setFixedWidth(34)
        h.addWidget(pick_btn)

        occ_spin = QDoubleSpinBox()
        occ_spin.setRange(0.0, 1.0)
        occ_spin.setDecimals(3)
        occ_spin.setSingleStep(0.05)
        occ_spin.setValue(entry.value)
        label_occ = QLabel("occupation")
        label_occ.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        occ_spin.setFixedWidth(70)
        h.addWidget(occ_spin)

        # Keep controls left; push only the trash button to the far right.
        h.addStretch(1)

        del_btn = QPushButton()
        del_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        del_btn.setToolTip("Remove this element row")
        del_btn.setFixedWidth(34)
        h.addWidget(del_btn)

        row = {
            'w': row_w,
            'elem': elem_edit,
            'occ': occ_spin,
            'del': del_btn,
            'pick': pick_btn,
            'entry': entry,
        }
        self.rows.append(row)
        self.rows_box.addWidget(row_w)

        def do_pick():
            sym = select_element(self)
            if sym:
                elem_edit.setText(sym)
        pick_btn.clicked.connect(do_pick)
        del_btn.clicked.connect(lambda: self._remove_row(row))
        # Validation only; no redraw on value changes
        elem_edit.textChanged.connect(
            lambda text: self._on_symbol_changed(row, text)
        )
        occ_spin.valueChanged.connect(
            lambda value: self._on_occupancy_changed(row, value)
        )

        # Focus-driven highlighting
        for w in (elem_edit, occ_spin, pick_btn, del_btn):
            w.installEventFilter(self)

        self._validate_row(row)

    def _remove_row(self, row: Dict[str, Any]) -> None:
        if not self.draft.remove_occupancy(self.site, row['entry']):
            return
        row['w'].setParent(None)
        self.rows.remove(row)
        self._validate_controls_state()
        self._validate_totals()

    def _validate_controls_state(self) -> None:
        # disable delete when only one row
        for r in self.rows:
            r['del'].setEnabled(len(self.rows) > 1)

    def _validate_row(self, row: Dict[str, Any]) -> None:
        elem = row['elem'].text().strip()
        ok = self.draft.symbol_is_valid(elem)
        # Styling: red border when invalid. Keep readable background.
        if ok or elem == "":
            row['elem'].setStyleSheet("")
        else:
            # Use a darker background only if palette seems light; simple heuristic
            row['elem'].setStyleSheet("QLineEdit { border: 1px solid #cc3333; background-color: #330000; color: #ffecec; }")
        self._validate_totals()

    def _normalize(self) -> None:
        self.draft.normalize_occupancy(self.site)
        for r in self.rows:
            r['occ'].blockSignals(True)
            r['occ'].setValue(r['entry'].value)
            r['occ'].blockSignals(False)
        self._validate_totals()

    def _validate_totals(self) -> None:
        over = self.draft.occupancy_is_overfull(self.site)
        # red border on all occupancy widgets when overfull
        style_bad = "QDoubleSpinBox { border: 1px solid #cc3333; }"
        for r in self.rows:
            r['occ'].setStyleSheet(style_bad if over else "")
        msg = f"Occupation too large for site {self.label}" if over else None
        if self._on_validation is not None:
            self._on_validation(self.label, msg)

    # Focus event filter to trigger highlighting only when user focuses a widget.
    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() == QEvent.Type.FocusIn:
            if isinstance(obj, QDoubleSpinBox):
                r = obj.property("pos_row")
                c = obj.property("pos_col")
                if r is not None and c is not None:
                    self.positions_table.setCurrentCell(int(r), int(c))
            if callable(self._on_activity):
                if isinstance(obj, QDoubleSpinBox) and obj.property("pos_row") is not None:
                    self._on_activity(self.label, int(obj.property("pos_row")), False)
                else:
                    self._on_activity(self.label)
        return super().eventFilter(obj, event)

    def is_valid(self) -> bool:
        return self.draft.is_site_valid(self.site)

    def _on_symbol_changed(self, row: Dict[str, Any], text: str) -> None:
        self.draft.set_occupancy_symbol(self.site, row['entry'], text)
        self._validate_row(row)

    def _on_occupancy_changed(
        self, row: Dict[str, Any], value: float
    ) -> None:
        self.draft.set_occupancy_value(self.site, row['entry'], value)
        self._validate_totals()
