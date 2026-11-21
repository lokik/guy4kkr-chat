"""Read-only structure-editor cluster/host previews.

Cluster atom identity comes from the native embedding array: its first column
is the host site index. SiteType grouping is intentionally separate for the
cluster and host (substitutions can change the local site symmetry).
"""
from __future__ import annotations

from itertools import product

import numpy as np
from ase.data.colors import jmol_colors
from matplotlib import colormaps
from matplotlib.colors import to_hex
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from ase2sprkkr.sprkkr.embedding import embedding_data, host_atoms
from ase2sprkkr_gui.gui.plots.atom_sizes import marker_areas
from ase2sprkkr_gui.gui.widgets.structures.embedding_preview import EmbeddingPreview


def site_type_group_keys(atoms):
    """Use actual shared SiteType objects, falling back to ASE symmetry kinds."""
    if atoms is None:
        return ()
    sites = getattr(atoms, "arrays", {}).get("sprkkr_sites_data")
    if sites is not None and len(sites) == len(atoms):
        return tuple(("site_type", id(site.site_type)) for site in sites)
    kinds = atoms.arrays.get("spacegroup_kinds")
    if kinds is not None and len(kinds) == len(atoms):
        return tuple(("spacegroup_kind", str(kind)) for kind in kinds)
    return tuple(("symbol", symbol) for symbol in atoms.get_chemical_symbols())


def site_type_colors(atoms):
    """Colors distinguish site types, not merely chemical elements."""
    keys = site_type_group_keys(atoms)
    if not keys:
        return np.empty(0, dtype=object)
    ordered = tuple(dict.fromkeys(keys))
    palette = colormaps.get_cmap("tab20").resampled(max(len(ordered), 1))
    colors = {
        key: to_hex(palette(index))
        for index, key in enumerate(ordered)
    }
    return np.asarray([colors[key] for key in keys])


def species_colors(atoms):
    """Use the same Jmol element palette as the Guided structure preview."""
    numbers = atoms.get_atomic_numbers()
    return np.asarray([
        to_hex(jmol_colors[int(number)])
        if 0 <= int(number) < len(jmol_colors) else "#8c8c8c"
        for number in numbers
    ], dtype=object)


def atom_colors(atoms, mode="site_type"):
    """One source of colors for the site table and both editor previews."""
    if mode == "site_type":
        return site_type_colors(atoms)
    if mode == "species":
        return species_colors(atoms)
    raise ValueError(f"Unknown atom color mode: {mode}")


def cluster_preview_style(atoms, selected=(), *, color_mode="site_type"):
    """Highlighted atoms remain visible with a larger marker and bright ring."""
    count = len(atoms)
    colors = atom_colors(atoms, color_mode)
    sizes = marker_areas(atoms, 55.0)
    outlines = np.full(count, "#333a42", dtype=object)
    widths = np.full(count, 0.65)
    for index in selected:
        if 0 <= int(index) < count:
            sizes[int(index)] *= 145.0 / 55.0
            outlines[int(index)] = "#ffcf4f"
            widths[int(index)] = 3.0
    return colors, sizes, outlines, widths


def host_site_cluster_indices(cluster, host_site):
    """Return *all* periodic-image cluster atoms referring to a host site."""
    if cluster is None or host_site < 0:
        return ()
    rows = embedding_data(cluster)
    return tuple(np.flatnonzero(rows[:, 0] == int(host_site)).tolist())


def _cell_corners(atoms):
    if atoms is None:
        return np.empty((0, 3))
    cell = np.asarray(atoms.cell, dtype=float)
    return np.asarray(list(product((0, 1), repeat=3)), dtype=float) @ cell


class EditorClusterHostPreviews(QWidget):
    """Vertically stacked read-only previews used by the Overview tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cluster = None
        self._host = None
        self._scope = "cluster"
        self._row = -1
        self._color_mode = "site_type"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        cluster_page = QWidget(self.splitter)
        self.cluster_page = cluster_page
        cluster_layout = QVBoxLayout(cluster_page)
        self.cluster_label = QLabel("Embedded cluster", cluster_page)
        label_font = self.cluster_label.font()
        label_font.setBold(True)
        self.cluster_label.setFont(label_font)
        cluster_layout.addWidget(self.cluster_label)
        self.cluster_preview = EmbeddingPreview(
            cluster_page, compact=True, controls_on_right=True,
        )
        cluster_layout.addWidget(self.cluster_preview, 1)
        self.splitter.addWidget(cluster_page)

        host_page = QWidget(self.splitter)
        self.host_page = host_page
        host_layout = QVBoxLayout(host_page)
        self.host_label = QLabel("Host structure", host_page)
        self.host_label.setFont(label_font)
        host_layout.addWidget(self.host_label)
        self.host_preview = EmbeddingPreview(
            host_page, compact=True, controls_on_right=True,
        )
        host_layout.addWidget(self.host_preview, 1)
        self.splitter.addWidget(host_page)
        self.splitter.setSizes([300, 300])

    def set_color_mode(self, mode):
        """Restyle both previews without changing their camera or selection."""
        if mode not in ("site_type", "species"):
            raise ValueError(f"Unknown atom color mode: {mode}")
        if mode == self._color_mode:
            return
        self._color_mode = mode
        self._render_host()
        self.update_selection(self._scope, self._row)

    def _render_host(self):
        if self._host is None:
            return
        self.host_preview.set_points(
            self._host.get_positions(),
            atom_colors(self._host, self._color_mode),
            marker_areas(self._host, 55.0, potential=self._cluster.embedding_host),
            cell_corners=_cell_corners(self._host),
            outlines="#333a42", widths=0.65,
        )

    def set_structure(self, cluster):
        """Show one structure, or a cluster paired with its periodic host."""
        self._cluster = cluster
        embedded = (
            cluster is not None
            and "sprkkr_embedding" in getattr(cluster, "arrays", {})
        )
        self._host = host_atoms(cluster.embedding_host) if embedded else None
        self.cluster_label.setText("Embedded cluster" if embedded else "Structure")
        self.host_page.setVisible(self._host is not None)
        self._render_host()
        self.update_selection(self._scope, self._row)

    def update_selection(self, scope, row):
        self._scope, self._row = scope, int(row)
        if self._cluster is None:
            self.cluster_preview.set_points(
                [], [], [], cell_corners=np.empty((0, 3)),
            )
            return
        if scope == "host" and self._host is not None:
            selected = host_site_cluster_indices(self._cluster, self._row)
        elif scope != "host" and 0 <= self._row < len(self._cluster):
            selected = (self._row,)
        else:
            selected = ()
        colors, sizes, outlines, widths = cluster_preview_style(
            self._cluster, selected, color_mode=self._color_mode,
        )
        self.cluster_preview.set_points(
            self._cluster.get_positions(), colors, sizes,
            cell_corners=(
                _cell_corners(self._cluster)
                if any(self._cluster.pbc) else np.empty((0, 3))
            ),
            outlines=outlines, widths=widths,
        )
