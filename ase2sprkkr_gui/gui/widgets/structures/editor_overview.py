"""Detailed, read-only overview with linked cluster/host site selection."""
from __future__ import annotations

from html import escape

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QBoxLayout, QComboBox, QFormLayout, QHeaderView, QHBoxLayout, QLabel, QRadioButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ase2sprkkr_gui.gui.widgets.structures.editor_preview import atom_colors
from ase2sprkkr_gui.gui.widgets.structures.editor_section import EditorSection
from ase2sprkkr_gui.gui.widgets.structures.overview import structure_facts
from ase2sprkkr_gui.physics.composition import site_composition


def _symmetry_description(atoms):
    """Use the scientific symmetry API, never guessed space groups."""
    if atoms is None or not all(atoms.pbc) or not len(atoms):
        return "Not applicable to this nonperiodic structure"
    from ase2sprkkr.sprkkr.symmetry import analyze_symmetry
    try:
        dataset = analyze_symmetry(atoms, equivalence="occupation").dataset
    except (ValueError, TypeError, AttributeError) as error:
        return f"Unavailable: {error}"
    international = getattr(dataset, "international", "?")
    number = getattr(dataset, "number", "?")
    hall = getattr(dataset, "hall", "?")
    hall_number = getattr(dataset, "hall_number", "?")
    return (
        f"Space group: {international} (No. {number})\n"
        f"Hall symbol: {hall} (No. {hall_number})"
    )


def _fact_columns(facts: str, symmetry: str = "") -> tuple[list[str], list[str]]:
    """Keep identity and geometry/symmetry in distinct readable columns."""
    identity, details = [], []
    for line in facts.splitlines():
        if line.startswith(("Cell (Å):", "Angles (°):", "SCF status:")):
            details.append(line)
        else:
            identity.append(line)
    details.extend(symmetry.splitlines())
    return identity, details


def _fact_cells(line: str | None) -> str:
    """Produce one label/value pair with a consistent value starting position."""
    if line is None:
        return "<td></td><td></td>"
    if ":" not in line:
        return f'<td colspan="2">{escape(line)}</td>'
    label, value = line.split(":", 1)
    return (
        f'<td valign="top" style="padding-right: 10px; white-space: nowrap;">'
        f'{escape(label)}:</td><td valign="top">{escape(value.strip())}</td>'
    )


def _fact_table(left: list[str], right: list[str] | None = None) -> str:
    """Aligned, selectable facts with a modest gap between the two groups."""
    rows = []
    for index in range(max(len(left), len(right or []))):
        lhs = left[index] if index < len(left) else None
        cells = _fact_cells(lhs)
        if right is not None:
            rhs = right[index] if index < len(right) else None
            cells += '<td width="36"></td>' + _fact_cells(rhs)
        rows.append(f"<tr>{cells}</tr>")
    return '<table cellspacing="0" cellpadding="2">' + "".join(rows) + "</table>"


class EditorOverviewWidget(QWidget):
    """Structure facts and a table linked to an external cluster preview.

    The table always uses direct atom indices; its Host mode is a separate
    coordinate system whose rows are mapped to cluster atoms via embedding data.
    """

    siteSelectionChanged = pyqtSignal(str, int)
    colorModeChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._atoms = None
        self._host_atoms = None
        root = QVBoxLayout(self)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(self.scroll, 1)
        content = QWidget(self.scroll)
        self.scroll.setWidget(content)
        layout = QVBoxLayout(content)

        self.info_box = EditorSection("Structure information", content)
        info_layout = self.info_box.content_layout
        info_layout.setContentsMargins(14, 0, 0, 0)
        self.info_columns = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.info_columns.setSpacing(40)
        self.main = QLabel(self.info_box)
        self.main.setWordWrap(True)
        self.main.setTextFormat(Qt.TextFormat.RichText)
        self.main.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_columns.addWidget(self.main, 1, Qt.AlignmentFlag.AlignTop)
        self.symmetry = QLabel(self.info_box)
        self.symmetry.setWordWrap(True)
        self.symmetry.setTextFormat(Qt.TextFormat.RichText)
        self.symmetry.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_columns.addWidget(self.symmetry, 1, Qt.AlignmentFlag.AlignTop)
        info_layout.addLayout(self.info_columns)
        layout.addWidget(self.info_box)

        self.host_box = EditorSection(
            "Host structure", content, layout_type=QFormLayout,
        )
        host_layout = self.host_box.content_layout
        host_layout.setContentsMargins(14, 0, 0, 0)
        self.host_facts = QLabel(self.host_box)
        self.host_facts.setWordWrap(True)
        self.host_facts.setTextFormat(Qt.TextFormat.RichText)
        self.host_facts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        host_layout.addRow(self.host_facts)
        layout.addWidget(self.host_box)

        self.bulk_boxes = {}
        for side in ("left", "right"):
            box = EditorSection(
                f"{side.title()} bulk", content, layout_type=QFormLayout,
            )
            section = box.content_layout
            section.setContentsMargins(14, 0, 0, 0)
            summary = QLabel(box)
            summary.setWordWrap(True)
            summary.setTextFormat(Qt.TextFormat.RichText)
            summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            section.addRow(summary)
            layout.addWidget(box)
            self.bulk_boxes[side] = (box, summary)

        self.table_box = EditorSection("Atomic sites", content)
        table_layout = self.table_box.content_layout
        table_layout.setContentsMargins(14, 0, 0, 0)

        self.site_table = QTableWidget(0, 9, self.table_box)
        self.site_table.setHorizontalHeaderLabels([
            "Site", "Occupation", "Color", "x (Å)", "y (Å)", "z (Å)",
            "x (fractional)", "y (fractional)", "z (fractional)",
        ])
        self.site_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.site_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.site_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.site_table.setMinimumHeight(240)
        self.site_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.site_table.currentCellChanged.connect(self._selection_changed)

        # Radio buttons are to the right of the table in two rows; the table
        # keeps its own grid and column headers.
        self.site_scope = QWidget(self.table_box)
        scope_layout = QVBoxLayout(self.site_scope)
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(5)
        self.cluster_radio = QRadioButton("Cluster", self.site_scope)
        self.host_radio = QRadioButton("Host", self.site_scope)
        self.cluster_radio.setChecked(True)
        self.cluster_radio.toggled.connect(self._scope_changed)
        self.host_radio.toggled.connect(self._scope_changed)
        scope_layout.addWidget(self.cluster_radio)
        scope_layout.addWidget(self.host_radio)
        self.color_label = QLabel("Color by:", self.site_scope)
        scope_layout.addWidget(self.color_label)
        self.color_by = QComboBox(self.site_scope)
        self.color_by.addItem("Site type", "site_type")
        self.color_by.addItem("Species", "species")
        self.color_by.setToolTip(
            "Choose colors by crystallographic site type or chemical species"
        )
        self.color_by.currentIndexChanged.connect(self._color_mode_changed)
        scope_layout.addWidget(self.color_by)

        self.table_row = QHBoxLayout()
        self.table_row.addWidget(self.site_table, 1)
        self.table_row.addWidget(
            self.site_scope, 0, Qt.AlignmentFlag.AlignTop,
        )
        table_layout.addLayout(self.table_row)
        layout.addWidget(self.table_box, 1)
        layout.addStretch(1)

    @property
    def site_scope_name(self):
        if self._host_atoms is not None and self.host_radio.isChecked():
            return "host"
        return "cluster"

    @property
    def color_mode(self):
        return self.color_by.currentData()

    def _color_mode_changed(self, _index):
        self._populate_sites()
        self.colorModeChanged.emit(self.color_mode)

    def _scope_changed(self, checked):
        if checked:
            self._populate_sites()

    def _selection_changed(self, row, _column, _old_row, _old_column):
        self.siteSelectionChanged.emit(self.site_scope_name, int(row))

    def _populate_sites(self):
        scope = self.site_scope_name
        atoms = self._host_atoms if scope == "host" else self._atoms
        # Preserve a selected atom when only the underlying structure draft
        # changes, but begin at the first site when switching table scope.
        previous_row = (
            self.site_table.currentRow()
            if getattr(self, "_populated_scope", None) == scope else 0
        )
        self._populated_scope = scope
        self.site_table.blockSignals(True)
        self.site_table.setUpdatesEnabled(False)
        try:
            if atoms is None:
                self.site_table.setRowCount(0)
                return
            positions = atoms.get_positions()
            scaled = atoms.get_scaled_positions(wrap=False)
            labels = atoms.arrays.get("labels")
            colors = atom_colors(atoms, self.color_mode)
            self.site_table.setRowCount(len(atoms))
            for i in range(len(atoms)):
                name = str(labels[i]) if labels is not None else str(i + 1)
                try:
                    occupation = site_composition(atoms, i)
                except (ValueError, TypeError, KeyError, AttributeError):
                    occupation = atoms[i].symbol
                cells = [name, str(occupation), ""]
                cells += [f"{value:.5f}" for value in positions[i]]
                cells += [f"{value:.5f}" for value in scaled[i]]
                for column, value in enumerate(cells):
                    item = QTableWidgetItem(value)
                    if column == 2:
                        # A colored cell doubles as a compact legend for the
                        # active preview; keep the exact color in its tooltip.
                        item.setBackground(QColor(str(colors[i])))
                        item.setToolTip(str(colors[i]))
                    elif column >= 3:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    self.site_table.setItem(i, column, item)
            if len(atoms):
                self.site_table.setCurrentCell(
                    min(max(previous_row, 0), len(atoms) - 1), 0,
                )
        finally:
            self.site_table.setUpdatesEnabled(True)
            self.site_table.blockSignals(False)
        self.siteSelectionChanged.emit(
            self.site_scope_name, self.site_table.currentRow()
        )

    def set_structure(self, atoms):
        self._atoms = atoms
        if atoms is None:
            self._host_atoms = None
            self.main.clear()
            self.symmetry.clear()
            self.host_box.hide()
            self.site_scope.hide()
            self._populate_sites()
            return
        is_cluster = "sprkkr_embedding" in getattr(atoms, "arrays", {})
        info = atoms.info
        host = info.get("sprkkr_embedding_host") if is_cluster else None
        self._host_atoms = getattr(host, "atoms", host)
        self.site_scope.show()
        self.cluster_radio.setVisible(self._host_atoms is not None)
        self.host_radio.setVisible(self._host_atoms is not None)
        if self._host_atoms is None and self.host_radio.isChecked():
            self.cluster_radio.setChecked(True)
        symmetry = (
            "Cluster symmetry: refer to the host symmetry below"
            if is_cluster else
            _symmetry_description(atoms) if all(atoms.pbc) else
            "Space groups of the two bulk regions are shown separately"
        )
        summary, details = _fact_columns(structure_facts(atoms), symmetry)
        self.main.setText(_fact_table(summary))
        self.symmetry.setText(_fact_table(details))
        self.host_box.setVisible(self._host_atoms is not None)
        if self._host_atoms is not None:
            summary, details = _fact_columns(
                structure_facts(self._host_atoms),
                _symmetry_description(self._host_atoms),
            )
            self.host_facts.setText(_fact_table(summary, details))
        regions = getattr(
            self._host_atoms if is_cluster else atoms, "regions", {},
        )
        for name, (box, label) in self.bulk_boxes.items():
            region = regions.get(name)
            box.setVisible(region is not None)
            if region is None:
                continue
            try:
                part = region.create_atoms()
                summary, details = _fact_columns(
                    structure_facts(part), _symmetry_description(part),
                )
                label.setText(_fact_table(summary, details))
            except (ValueError, TypeError, AttributeError) as error:
                label.setText(_fact_table([f"Unavailable: {error}"]))
        self._populate_sites()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Preserve two columns in the normal editor, but stack when narrow.
        self.info_columns.setDirection(
            QBoxLayout.Direction.LeftToRight
            if self.scroll.viewport().width() >= 720
            else QBoxLayout.Direction.TopToBottom
        )
