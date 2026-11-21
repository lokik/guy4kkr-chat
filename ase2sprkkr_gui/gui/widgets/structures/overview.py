"""Compact, read-only structure information in the Guided workflow sidebar."""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from ase.data.colors import jmol_colors
from PyQt6.QtCore import QSignalBlocker, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QFrame,
    QLabel,
    QRadioButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.presentation import structure_kind_label
from ase2sprkkr_gui.gui.misc.colors import blend
from ase2sprkkr_gui.gui.style import action_card_stylesheet
from ase2sprkkr_gui.gui.widgets.centered_icon_buttons import CenteredIconToolButton
from ase2sprkkr_gui.gui.plots.atom_sizes import marker_areas
from ase2sprkkr_gui.gui.widgets.structures.embedding_preview import EmbeddingPreview
from ase2sprkkr_gui.physics.composition import structure_formula
from ase2sprkkr_gui.physics.lattice import detect_structure_kind

# Keep a compact preview responsive even for a large supercell or cluster.
_MAX_PREVIEW_SITES = 400
_CELL_CORNERS = np.array(
    [[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)],
    dtype=float,
)


def _host_atoms(host):
    """Resolve a periodic host Potential or geometrical host reference."""
    return getattr(host, "atoms", host) if host is not None else None


def _host_status(host) -> str | None:
    try:
        status = host.SCF_INFO.SCFSTATUS()
    except (AttributeError, TypeError, KeyError):
        return None
    return str(status).strip().upper() if status is not None else None


def _periodicity(atoms) -> str:
    axes = [axis for axis, enabled in zip("xyz", atoms.get_pbc()) if enabled]
    if not axes:
        return "None (finite cluster)"
    return ", ".join(axes) + f" ({len(axes)}D)"


def _element_symbols(atoms) -> str:
    """Include mixed-occupancy species, not only ASE's representative atoms."""
    symbols = set(atoms.get_chemical_symbols())
    occupancies = getattr(atoms, "info", {}).get("occupancy")
    if isinstance(occupancies, Mapping):
        for occupation in occupancies.values():
            if isinstance(occupation, Mapping):
                symbols.update(str(symbol) for symbol in occupation)
    if (getattr(atoms, "are_sites_inited", None) is not None
            and atoms.are_sites_inited()):
        for site in atoms.sites:
            symbols.update(t.symbol for t in site.occupation.atomic_types())
    return ", ".join(sorted(symbols))


def _structure_summary_lines(atoms, *, kind=None) -> list[str]:
    """Structure identity fields shared by the full and compact presentations."""
    kind = detect_structure_kind(atoms) if kind is None else kind
    return [
        f"Type: {structure_kind_label(kind) or 'Unknown structure'}",
        f"Composition: {structure_formula(atoms)}",
        f"Elements: {_element_symbols(atoms)}",
        f"Sites: {len(atoms)}",
        f"Periodicity: {_periodicity(atoms)}",
    ]


def structure_facts(atoms, *, kind=None, status=None) -> str:
    """Plain-text structure facts, including meaningful cell data if periodic."""
    if atoms is None:
        return ""
    lines = _structure_summary_lines(atoms, kind=kind)
    if any(atoms.get_pbc()):
        # The third length in a 2D slab may denote vacuum/lead separation;
        # report the actual simulation cell, not an inferred bulk lattice.
        a, b, c, alpha, beta, gamma = atoms.cell.cellpar()
        lines.extend((
            f"Cell (Å): a={a:.3f}, b={b:.3f}, c={c:.3f}",
            f"Angles (°): α={alpha:.1f}, β={beta:.1f}, γ={gamma:.1f}",
        ))
    if status:
        lines.append(f"SCF status: {status}")
    return "\n".join(lines)


def _host_fact_columns(atoms, *, status: str | None = None) -> tuple[str, str]:
    """Compact host facts: identity on the left, cell/SCF state on the right."""
    if atoms is None:
        return "", ""
    summary = "\n".join(_structure_summary_lines(atoms))
    geometry = []
    if any(atoms.get_pbc()):
        a, b, c, alpha, beta, gamma = atoms.cell.cellpar()
        geometry.extend((
            "Cell (Å) / angles (°)",
            f"a={a:.3f}    α={alpha:.1f}",
            f"b={b:.3f}    β={beta:.1f}",
            f"c={c:.3f}    γ={gamma:.1f}",
        ))
    if status:
        geometry.append(f"SCF status: {status}")
    return summary, "\n".join(geometry)


class StructureOverviewWidget(QFrame):
    """Current cluster/bulk summary and, when applicable, its periodic host.

    The plot only uses positions/numbers/cell; it never materializes a Potential,
    modifies an Atoms object, or reclassifies its host as a cluster.
    """

    visualizeRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("guidedStructureOverview")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._atoms = None
        self._host = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(7)

        # The scope selector belongs beside the plot, together with the
        # projection and Fit controls, rather than consuming a row above it.
        self._view_selector = QWidget(self)
        self._view_selector.setObjectName("guidedStructureViewSelector")
        source_layout = QVBoxLayout(self._view_selector)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(2)
        self._view_group = QButtonGroup(self._view_selector)
        self.host_radio = QRadioButton("Host", self._view_selector)
        self.host_radio.setObjectName("guidedHostPreviewRadio")
        self.cluster_radio = QRadioButton("Cluster", self._view_selector)
        self.cluster_radio.setObjectName("guidedClusterPreviewRadio")
        for button in (self.host_radio, self.cluster_radio):
            self._view_group.addButton(button)
            source_layout.addWidget(button)
        self.cluster_radio.setChecked(True)

        # This belongs only to the main overview, not to reusable previews
        # or their fullscreen copies.
        self.external_viewer_button = CenteredIconToolButton(self)
        self.external_viewer_button.setObjectName("guidedExternalViewerButton")
        self.external_viewer_button.setIcon(QIcon.fromTheme(
            "applications-graphics",
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
        ))
        self.external_viewer_button.setIconSize(QSize(26, 26))
        self.external_viewer_button.setText("Viewer")
        self.external_viewer_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        )
        self.external_viewer_button.setFixedHeight(68)
        self.external_viewer_button.setToolTip("External viewer")
        self.external_viewer_button.setAccessibleName("External viewer")
        accent = blend(
            self.palette().color(QPalette.ColorRole.Button),
            self.palette().color(QPalette.ColorRole.Mid), .78,
        )
        self.external_viewer_button.setStyleSheet(
            action_card_stylesheet(
                self.palette(), accent, "QToolButton", accent_width=3,
            )
            + "QToolButton { padding: 3px 7px; }"
        )
        self.external_viewer_button.clicked.connect(
            lambda _checked=False: self.visualizeRequested.emit()
        )

        self.preview = EmbeddingPreview(
            self,
            compact=True,
            controls_on_right=True,
            controls_header=self._view_selector,
            controls_footer=self.external_viewer_button,
        )
        self.preview.setObjectName("guidedStructurePreview")
        for button in (self.host_radio, self.cluster_radio):
            button.toggled.connect(self._render_preview)
        self.preview.setMinimumHeight(190)
        self.preview.setMaximumHeight(240)
        outer.addWidget(self.preview)

        self._info_widget = QWidget(self)
        info = QVBoxLayout(self._info_widget)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(7)

        self.details = QLabel(self._info_widget)
        self.details.setObjectName("guidedStructureFacts")
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        info.addWidget(self.details)

        self.host_heading = QLabel("Host structure", self._info_widget)
        host_font = self.host_heading.font()
        host_font.setBold(True)
        self.host_heading.setFont(host_font)
        info.addWidget(self.host_heading)

        # A compact two-column host summary avoids a long single text block.
        # Narrow overview panels fall back to stacking the same two groups.
        self._host_info = QWidget(self._info_widget)
        self._host_info.setObjectName("guidedHostColumns")
        self._host_layout = QBoxLayout(
            QBoxLayout.Direction.LeftToRight, self._host_info
        )
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.setSpacing(8)
        self.host_details = QLabel(self._host_info)
        self.host_details.setObjectName("guidedHostFacts")
        self.host_geometry = QLabel(self._host_info)
        self.host_geometry.setObjectName("guidedHostGeometry")
        for label in (self.host_details, self.host_geometry):
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            self._host_layout.addWidget(label, 1)
        info.addWidget(self._host_info)
        info.addStretch(1)

        outer.addWidget(self._info_widget)

    def set_structure(self, atoms, *, kind=None, scf_status=None) -> None:
        """Refresh latest structure and its host, including in-place SCF updates."""
        self._atoms = atoms
        self._host = getattr(atoms, "embedding_host", None)
        self.details.setText(structure_facts(atoms, kind=kind, status=scf_status))
        host_atoms = _host_atoms(self._host)
        has_host = host_atoms is not None
        self.host_heading.setVisible(has_host)
        self._host_info.setVisible(has_host)
        summary, geometry = _host_fact_columns(
            host_atoms, status=_host_status(self._host)
        )
        self.host_details.setText(summary)
        self.host_geometry.setText(geometry)
        self.host_geometry.setVisible(bool(geometry))

        # Keep the selected source while the same kind of structure is
        # refreshed. With no host, return to the ordinary structure preview.
        self._view_selector.setVisible(has_host)
        if not has_host and not self.cluster_radio.isChecked():
            # Checking Cluster toggles both radio buttons. Ignore the two
            # intermediate notifications; _render_preview() runs once below.
            with QSignalBlocker(self.host_radio), QSignalBlocker(self.cluster_radio):
                self.cluster_radio.setChecked(True)
        self.preview.setVisible(atoms is not None)
        self._render_preview()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Two columns are helpful only while they have enough room to read.
        self._host_layout.setDirection(
            QBoxLayout.Direction.LeftToRight
            if self.width() >= 390 else QBoxLayout.Direction.TopToBottom
        )

    def _render_preview(self, *_args) -> None:
        atoms = (
            _host_atoms(self._host)
            if self.host_radio.isChecked() and self._host is not None
            else self._atoms
        )
        if atoms is None:
            self.preview.set_points([], [], [], cell_corners=np.empty((0, 3)))
            return

        positions = np.asarray(atoms.get_positions(), dtype=float)
        atomic_numbers = np.asarray(atoms.get_atomic_numbers(), dtype=int)
        potential = (
            self._host if self.host_radio.isChecked()
            and hasattr(self._host, 'SCF_INFO') else None
        )
        sizes = marker_areas(atoms, 48, potential=potential)
        if len(positions) > _MAX_PREVIEW_SITES:
            keep = np.linspace(0, len(positions) - 1, _MAX_PREVIEW_SITES, dtype=int)
            positions = positions[keep]
            atomic_numbers = atomic_numbers[keep]
            sizes = sizes[keep]
        colors = [
            jmol_colors[int(number)] if 0 <= number < len(jmol_colors)
            else (0.55, 0.55, 0.55)
            for number in atomic_numbers
        ]
        corners = (
            _CELL_CORNERS @ np.asarray(atoms.cell, dtype=float)
            if any(atoms.get_pbc()) else np.empty((0, 3))
        )
        self.preview.set_points(positions, colors, sizes, cell_corners=corners)
