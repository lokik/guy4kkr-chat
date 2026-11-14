from __future__ import annotations

from typing import Dict, Optional

import numpy as np
from ase import Atoms
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.ase.element_assignment import AssignmentSite, ElementAssignmentDraft
from ase2sprkkr_gui.gui.dialogs.structures.element_selector import select_element
from ase2sprkkr_gui.gui.plots.lattice import plot_lattice, plot_sites_in_lattice
from ase2sprkkr_gui.gui.widgets.structures.element_assignment import QLetterRow


class ElementAssignmentDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, back: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Assign Elements to Wyckoff Sites")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        # Wider default window to accommodate expanded left panel
        self.resize(1400, 650)
        self._allow_back = bool(back)
        self._letter_widgets: list[QLetterRow] = []
        self._draft: ElementAssignmentDraft | None = None
        self._active_letter: tuple(Optional[str],Optional[int]) = (None, None)
        self._site_errors: Dict[str, Optional[str]] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        root.addWidget(splitter, 1)

        # Left: Scroll area for letters
        left = QWidget()
        left_v = QVBoxLayout(left)
        self.scroll = QScrollArea(left)
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.scroll.setWidget(self.container)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        left_v.addWidget(self.scroll, 1)
        # Keep left column wide enough and stable so headers and inputs fit
        # Widen left panel for better readability of element rows
        left.setMinimumWidth(750)
        # Initial splitter sizing (favor left)
        splitter.setSizes([850, 550])
        splitter.addWidget(left)

        # Right: 3D preview
        right = QWidget()
        right_v = QVBoxLayout(right)

        # Lattice vectors table (editable)
        lattice_vectors_group = QGroupBox("Lattice Vectors (Å)")
        lattice_vectors_layout = QVBoxLayout(lattice_vectors_group)
        self.lattice_vectors_table = QTableWidget(3, 3)
        self.lattice_vectors_table.setHorizontalHeaderLabels(["x", "y", "z"])
        self.lattice_vectors_table.setVerticalHeaderLabels(["a", "b", "c"])
        self.lattice_vectors_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.lattice_vectors_table.verticalHeader().setMinimumWidth(40)
        self.lattice_vectors_table.setMaximumHeight(120)

        # Initialize with spinboxes
        self.lattice_spinboxes = []
        for i in range(3):
            row_spinboxes = []
            for j in range(3):
                spinbox = QDoubleSpinBox()
                spinbox.setRange(-1000.0, 1000.0)
                spinbox.setDecimals(4)
                spinbox.setSingleStep(0.1)
                spinbox.setValue(0.0)
                spinbox.setAlignment(Qt.AlignmentFlag.AlignRight)
                spinbox.valueChanged.connect(self._on_lattice_vector_changed)
                self.lattice_vectors_table.setCellWidget(i, j, spinbox)
                row_spinboxes.append(spinbox)
            self.lattice_spinboxes.append(row_spinboxes)

        lattice_vectors_layout.addWidget(self.lattice_vectors_table)
        right_v.addWidget(lattice_vectors_group, 0)

        self.fig = Figure(figsize=(4, 4))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.canvas = FigureCanvas(self.fig)
        right_v.addWidget(self.canvas, 1)
        # Error label at the bottom of right panel (larger, centered)
        self.error_label = QLabel("")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.error_label.setStyleSheet(
            "QLabel { color: #cc3333; font-size: 14px; font-weight: 600; padding: 4px 0; }"
        )
        right_v.addWidget(self.error_label)
        splitter.addWidget(right)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        if self._allow_back:
            self.back_btn = QPushButton("Back")
            self.back_btn.clicked.connect(self._on_back)
            btns.addWidget(self.back_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.cancel_btn)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self._on_ok)
        self.ok_btn.setEnabled(False)
        btns.addWidget(self.ok_btn)
        root.addLayout(btns)


    def setup(
        self,
        atoms: Atoms | ElementAssignmentDraft,
        back: bool = False,
    ) -> None:
        # reset state
        self._allow_back = bool(back)
        self._site_errors.clear()
        self._update_error_label()
        for child in list(self._letter_widgets):
            child.setParent(None)
        self._draft = (
            atoms
            if isinstance(atoms, ElementAssignmentDraft)
            else ElementAssignmentDraft(atoms)
        )
        cell = self._draft.cell

        # Update lattice vector spinboxes
        for i in range(3):
            for j in range(3):
                self.lattice_spinboxes[i][j].blockSignals(True)
                self.lattice_spinboxes[i][j].setValue(cell[i, j])
                self.lattice_spinboxes[i][j].blockSignals(False)

        self._build_site_rows()

        self._update_ok_state()
        self._draw_preview()

    def _build_site_rows(self) -> None:
        draft = self._require_draft()
        self._site_errors.clear()
        self._update_error_label()
        # Clear entire container layout (prevents duplicated spacers/headers across setups)
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._letter_widgets.clear()

        # Build site rows
        for site in draft.sites:
            row = QLetterRow(
                draft, site, self.container,
                on_activity=self._mark_active, on_break=self._break_site,
                select_element=select_element, on_validation=self._site_validation_changed,
            )
            self.container_layout.addWidget(row)
            self._letter_widgets.append(row)

        # Global headers above all sites: left = Occupation, right = Positions
        if self._letter_widgets:
            first = self._letter_widgets[0]
            header = QWidget(self.container)
            header_grid = QGridLayout(header)
            header_grid.setContentsMargins(0, 0, 0, 6)
            header_grid.setHorizontalSpacing(10)
            header_grid.setColumnStretch(0, 1)
            header_grid.setColumnStretch(1, 0)

            occ_lbl = QLabel("Occupation")
            f = occ_lbl.font()
            f.setBold(True)
            occ_lbl.setFont(f)

            pos_lbl = QLabel("Positions")
            pos_lbl.setFont(f)
            pos_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            pm = first.positions_group.layout().contentsMargins()
            pos_lbl.setContentsMargins(pm.left(), 0, 0, 0)
            pos_lbl.setFixedWidth(first.positions_group.sizeHint().width())

            header_grid.addWidget(occ_lbl, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            header_grid.addWidget(pos_lbl, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            self.container_layout.insertWidget(0, header)

        # Spacer to consume remaining space
        spacer = QWidget(self.container)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.container_layout.addWidget(spacer)

    def _break_site(self, site: AssignmentSite) -> None:
        self._require_draft().split_site(site)
        self._build_site_rows()
        self._update_ok_state()
        self._draw_preview()

    def _site_validation_changed(self, label, message) -> None:
        self._update_ok_state()
        self._set_site_error(label, message)

    def _update_ok_state(self) -> None:
        ok = self._draft is not None and self._draft.is_valid()
        self.ok_btn.setEnabled(ok)

    def _on_ok(self) -> None:
        draft = self._require_draft()
        if not draft.is_valid():
            return
        # Materialization may mutate its source Atoms in place. The dialog only
        # confirms the isolated draft; an authoritative source is applied later
        # by WorkspaceController while it owns the shared structure lock.
        self._result = draft
        self.accept()

    def _on_back(self) -> None:
        self._result = 'back'
        self.done(42)

    def _mark_active(self, label: str, index:int=None, force=False) -> None:
        # Avoid redraw if the letter stays the same
        if not force and (label, index) == self._active_letter:
            return
        self._active_letter = (label, index)
        self._draw_preview()

    def _on_lattice_vector_changed(self, value: float) -> None:
        """Handle changes to lattice vector spinboxes."""
        draft = self._require_draft()
        for i in range(3):
            for j in range(3):
                draft.set_cell_component(
                    i, j, self.lattice_spinboxes[i][j].value()
                )

        # Redraw visualization
        self._draw_preview()

    def _draw_preview(self) -> None:
        self.ax.clear()
        draft = self._require_draft()
        lattice = draft.cell
        plot_lattice(self.ax, lattice)

        # collect other vs active positions
        others = []
        active = []
        label, index = self._active_letter

        for site in draft.sites:
            if label == site.label:
                if index is not None:
                    active.append(site.positions[index:index + 1])
                    others.append(site.positions[:index])
                    others.append(site.positions[index + 1:])
                    continue
                to = active
            else:
                to = others
            to.append(site.positions)
        if others:
            plot_sites_in_lattice(self.ax, lattice, np.vstack(others), role='inactive')
        if active:
            plot_sites_in_lattice(self.ax, lattice, np.vstack(active), role='active')
        self.canvas.draw()

    # ---- error aggregation helpers ----
    def _set_site_error(self, letter: str, message: Optional[str]) -> None:
        if message:
            self._site_errors[letter] = message
        else:
            self._site_errors.pop(letter, None)
        self._update_error_label()

    def _update_error_label(self) -> None:
        self.error_label.setText("\n".join(self._site_errors.values()))

    def _require_draft(self) -> ElementAssignmentDraft:
        if self._draft is None:
            raise RuntimeError("Element assignment dialog has not been set up")
        return self._draft


def select_site_elements(
    atoms: Atoms | ElementAssignmentDraft,
    parent: Optional[QWidget] = None,
    back: bool = False,
    *,
    apply: bool = True,
) -> Optional[Atoms | ElementAssignmentDraft] | str:
    """
    PyQt6 element assignment dialog.

        Returns an ase.Atoms instance with:
            - positions in Cartesian coordinates
            - symbols
            - array 'spacegroup_kinds' (int per atom; a->0, b->1, ...)
            - atoms.info['occupancy'] (dict keyed by stringified
              spacegroup kind, with occupancy mappings as values)
            - array 'labels' (str per atom: site labels like 'a', 'b.1', ...)
        Or 'back' or None.
    """
    dlg = ElementAssignmentDialog(parent, back=back)
    dlg.setup(atoms)
    code = dlg.exec()
    if code == 42:
        return 'back'
    if code == QDialog.DialogCode.Accepted:
        draft = dlg._result
        return draft.apply() if apply else draft
    return None
