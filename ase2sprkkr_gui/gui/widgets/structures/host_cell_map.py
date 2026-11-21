"""Clickable lattice-cell map with real projected lengths and angles."""
from __future__ import annotations

import numpy as np
from matplotlib.collections import PatchCollection
from matplotlib.figure import Figure
from matplotlib.patches import Polygon
from matplotlib.path import Path
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ase2sprkkr_gui.gui.widgets.matplotlib_preview import PreviewFigureCanvas as FigureCanvas

# Shared across the cell map and atom previews: selected and actively linked
# symmetry counterparts belong to one orange visual family.
SELECTED_COLOR = "#f59e0b"
SYMMETRY_APPLY_COLOR = "#a65e13"
SYMMETRY_PREVIEW_COLOR = "#7024a5"


class HostCellMap(QWidget):
    cellSelected = pyqtSignal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure(figsize=(3.2, 3.2), layout="constrained")
        self.canvas = FigureCanvas(self.figure)
        self.axes = self.figure.add_subplot(111)
        self._cells = []
        self._polygons = np.empty((0, 4, 2))
        self._press = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.canvas.mpl_connect("button_press_event", self._mouse_press)
        self.canvas.mpl_connect("button_release_event", self._mouse_release)

    def set_cells(self, cells, *, cell, origin, axes, projection, axis_labels,
                  selected, counts, modified, equivalents, apply_equivalents=False):
        """Display one translated lattice plane; signal full cell identities.

        ``axes`` are the two changing lattice indices. ``projection`` is a
        Cartesian XY/XZ/YZ projection in 3D, or an orthonormal surface basis
        in 2D. A common scale sets the longer projected vector to length one.
        """
        # Selection changes must not reset a zoomed viewport.
        previous_polygons = self._polygons
        previous_limits = self.axes.get_xlim(), self.axes.get_ylim()
        self._cells = list(cells)
        vectors = np.asarray(cell)[list(axes)] @ projection
        scale = max(np.linalg.norm(vectors, axis=1).max(), 1e-12)
        vectors /= scale
        self.axes.clear()
        self.axes.set_aspect("equal", adjustable="box")
        self.axes.set_xlabel(f"{axis_labels[0]} (relative)")
        self.axes.set_ylabel(f"{axis_labels[1]} (relative)")
        corners = np.array([[0, 0], vectors[0], vectors.sum(axis=0), vectors[1]])
        shifts = (np.asarray(self._cells) @ cell[:len(self._cells[0])] + origin) @ projection / scale
        self._polygons = shifts[:, None, :] + corners
        same_geometry = (
            self._polygons.shape == previous_polygons.shape
            and np.allclose(self._polygons, previous_polygons, rtol=0, atol=1e-10)
        )
        if abs(np.linalg.det(vectors)) < 1e-10:
            self.axes.text(.5, .5, "Cell plane is edge-on. Choose another projection.",
                           ha="center", va="center", transform=self.axes.transAxes)
            self._polygons = np.empty((0, 4, 2))
            self.canvas.draw_idle()
            return
        colors = []
        for index, polygon in zip(self._cells, self._polygons):
            colors.append(
                "#f3bd81" if index in modified else "#a2c9ed" if counts.get(index) else "#f5f6f7"
            )
            if len(self._cells) <= 81:
                centre = polygon.mean(axis=0)
                label = ",".join(str(index[i]) for i in axes)
                if counts.get(index):
                    label += f"\n{counts[index]} sites"
                self.axes.text(*centre, label, ha="center", va="center", fontsize=8)

        # Paint all ordinary cells first. When fills and highlight borders
        # share a PatchCollection, a later neighbour can cover an earlier
        # selected/symmetric edge (especially along shared boundaries).
        self.axes.add_collection(PatchCollection(
            [Polygon(p) for p in self._polygons], facecolors=colors,
            edgecolors="#8c969f", linewidths=.7, zorder=1,
        ))
        symmetry_color = (SYMMETRY_APPLY_COLOR if apply_equivalents
                          else SYMMETRY_PREVIEW_COLOR)
        for index, polygon in zip(self._cells, self._polygons):
            if index in equivalents and index != selected:
                self.axes.add_patch(Polygon(
                    polygon, fill=False, edgecolor=symmetry_color,
                    linewidth=2.2, linestyle="--", joinstyle="miter", zorder=4,
                ))
        for index, polygon in zip(self._cells, self._polygons):
            if index == selected:
                self.axes.add_patch(Polygon(
                    polygon, fill=False, edgecolor=SELECTED_COLOR,
                    linewidth=2.8, joinstyle="miter", zorder=5,
                ))

        if same_geometry:
            self.axes.set_xlim(previous_limits[0])
            self.axes.set_ylim(previous_limits[1])
        else:
            self.axes.margins(.06)
            self.axes.autoscale_view()
        self.canvas.draw_idle()

    def _mouse_press(self, event):
        self._press = ((event.x, event.y)
                       if event.inaxes is self.axes and event.button == 1 else None)

    def _mouse_release(self, event):
        press, self._press = self._press, None
        if (press is None or event.inaxes is not self.axes or event.button != 1
                or np.hypot(event.x - press[0], event.y - press[1]) > 5):
            return
        point = (event.xdata, event.ydata)
        hits = [i for i, polygon in enumerate(self._polygons)
                if Path(polygon).contains_point(point, radius=1e-9)]
        if hits:
            index = min(hits, key=lambda i: np.linalg.norm(self._polygons[i].mean(axis=0) - point))
            self.cellSelected.emit(self._cells[index])
