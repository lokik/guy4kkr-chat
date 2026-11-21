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
from ase2sprkkr_gui.gui.widgets.structures.occupation import OccupationEditor


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

        # This is the same occupation component used by the embedding editor.
        # Model mutations remain delegated to ElementAssignmentDraft.
        self.occupation_editor = OccupationEditor(
            left,
            on_add=lambda: self.draft.add_occupancy(self.site, value=0.0),
            on_remove=lambda entry: self.draft.remove_occupancy(self.site, entry),
            on_symbol=lambda entry, value: self.draft.set_occupancy_symbol(
                self.site, entry, value
            ),
            on_value=lambda entry, value: self.draft.set_occupancy_value(
                self.site, entry, value
            ),
            on_normalize=lambda: self.draft.normalize_occupancy(self.site),
            on_restore=self._restore_initial_occupation,
            on_validation=lambda msg: self._notify_occupation_validation(msg),
            on_focus=lambda: (
                self._on_activity(self.label)
                if callable(self._on_activity) else None
            ),
            selector=select_element,
        )
        self.vbox.addWidget(self.occupation_editor)
        self.occupation_editor.set_initial_occupation(self.site.occupancies)
        # Splitting symmetry changes the grouping of Wyckoff positions, not
        # their occupation. Keep this bulk-only action outside the shared widget.
        self.break_btn = QPushButton("Break symmetry")
        self.break_btn.setVisible(bool(site.can_split))
        if callable(self._on_break):
            self.break_btn.clicked.connect(lambda: self._on_break(self.site))
        self.vbox.addWidget(
            self.break_btn, alignment=Qt.AlignmentFlag.AlignRight
        )
        # Compatibility handles used by this dialog's older callers/tests.
        self.rows = self.occupation_editor.rows
        self.normalize_check = self.occupation_editor.normalize_check
        self.add_btn = self.occupation_editor.add_btn
        self.rows_box = self.occupation_editor.rows_box

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

    def _restore_initial_occupation(
        self, original: list[OccupancyEntry]
    ) -> list[OccupancyEntry]:
        self.site.occupancies[:] = original
        return self.site.occupancies

    def load_occupancy(self) -> None:
        """Load the site's model entries into the common occupation editor."""
        self.occupation_editor.set_entries(self.site.occupancies)

    def _notify_occupation_validation(self, message: str | None) -> None:
        if self._on_validation is not None:
            # The assigned site model remains the authority for validity.
            self._on_validation(self.label, message)

    def add_row(self) -> None:
        self.occupation_editor.add_row()

    def _normalize(self) -> None:
        self.occupation_editor.normalize()

    def _validate_controls_state(self) -> None:
        self.occupation_editor._validate()

    def _validate_totals(self) -> None:
        self.occupation_editor._validate()

    # The original position-editor focus behavior stays independent from
    # occupation rows (which now install their own focus filter).
    def eventFilter(self, obj, event):  # type: ignore[override]
        if event.type() == QEvent.Type.FocusIn:
            if isinstance(obj, QDoubleSpinBox):
                row = obj.property("pos_row")
                col = obj.property("pos_col")
                if row is not None and col is not None:
                    self.positions_table.setCurrentCell(int(row), int(col))
                    if callable(self._on_activity):
                        self._on_activity(self.label, int(row), False)
        return super().eventFilter(obj, event)

    def is_valid(self) -> bool:
        return self.draft.is_site_valid(self.site)

