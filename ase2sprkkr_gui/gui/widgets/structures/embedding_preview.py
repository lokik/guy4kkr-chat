"""Geometry-only preview for the embedding editor.

The dialog chooses which host identities are visible. This widget draws their
Cartesian positions and reports a clicked point's index, without editing atoms.
"""
from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.colors import to_rgba_array
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.widgets.matplotlib_preview import PreviewFigureCanvas as FigureCanvas
from ase2sprkkr_gui.gui.plots.lattice import edge_indices


class EmbeddingPreview(QWidget):
    pointSelected = pyqtSignal(int)

    def __init__(self, parent=None, *, selectable=False, controls_on_right=False,
                 controls_header: QWidget | None = None,
                 controls_footer: QWidget | None = None, compact=False,
                 show_bulk_opacity=False):
        super().__init__(parent)
        self._press = None
        self._positions = np.empty((0, 3))
        self._selectable = selectable
        self._corners = np.empty((0, 3))
        self._colors = []
        self._sizes = []
        self._outlines = []
        self._widths = []
        self._bulk_mask = np.empty(0, dtype=bool)
        self._labels = ()
        self._angles = (25., -60.)
        self._zoom_factor = 1.
        self._pan = np.zeros(2)
        self._extent = np.empty((0, 2))
        self._scatter = None
        self._label_artists = []
        self._label_index = None
        # Compact previews normally stack their controls above the canvas.
        # The Guided structure overview instead uses a narrow vertical rail
        # to the right without changing the embedding editor's layout.
        layout = (
            QVBoxLayout(self) if compact and not controls_on_right
            else QHBoxLayout(self)
        )
        layout.setContentsMargins(0, 0, 0, 0)
        controls = (
            QHBoxLayout() if compact and not controls_on_right
            else QVBoxLayout()
        )
        if controls_header is not None:
            controls.addWidget(controls_header)
        self.projection = QComboBox()
        for label, angles in (
            ("3D", (25, -60)), ("XY", (90, -90)),
            ("XZ", (0, -90)), ("YZ", (0, 0)),
        ):
            self.projection.addItem(label, angles)
        self.projection.setToolTip(
            "Cartesian projections; left drag to rotate, middle drag to pan, wheel to zoom"
        )
        self.projection.currentIndexChanged.connect(self._change_projection)
        controls.addWidget(self.projection)
        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self._fit)
        controls.addWidget(self.fit_button)
        if controls_footer is not None:
            controls.addWidget(controls_footer)
        self.bulk_opacity_slider = None
        self.bulk_opacity_label = None
        if show_bulk_opacity:
            self.bulk_opacity_label = QLabel("Bulk opacity: 100%")
            controls.addWidget(self.bulk_opacity_label)
            self.bulk_opacity_slider = QSlider(Qt.Orientation.Horizontal)
            self.bulk_opacity_slider.setRange(0, 100)
            self.bulk_opacity_slider.setValue(100)
            self.bulk_opacity_slider.setToolTip(
                "Opacity of the surrounding host (bulk) atoms; cluster and highlighted sites stay opaque"
            )
            controls.addWidget(self.bulk_opacity_slider)

        # Keep the scope selector, projection selector, and Fit button aligned.
        # Each preview computes its own width from its longest control label.
        width_controls = [self.projection, self.fit_button]
        if controls_header is not None:
            width_controls.insert(0, controls_header)
        if self.bulk_opacity_label is not None:
            width_controls.append(self.bulk_opacity_label)
        control_width = max(control.sizeHint().width() for control in width_controls)
        for control in width_controls:
            control.setFixedWidth(control_width)
        if self.bulk_opacity_slider is not None:
            self.bulk_opacity_slider.setFixedWidth(control_width)
        if controls_footer is not None:
            controls_footer.setFixedWidth(control_width)

        self.site_numbers = None
        if selectable:
            self.site_numbers = QCheckBox("All site\nnumbers")
            self.site_numbers.setToolTip("The selected site's number is always visible")
            self.site_numbers.toggled.connect(self._update_labels)
            controls.addWidget(self.site_numbers)
        if not compact or controls_on_right:
            controls.addStretch(1)
        self.figure = Figure(figsize=(4.5, 3))
        self.figure.subplots_adjust(left=0, right=1, bottom=0, top=1)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.fullscreen_factory = self._fullscreen_copy
        self.canvas.setMinimumHeight(120)
        self.axes = self.figure.add_axes((0, 0, 1, 1))
        self.axes.set_axis_off()
        if self.bulk_opacity_slider is not None:
            self.bulk_opacity_slider.valueChanged.connect(self._set_bulk_opacity)
        self._change_projection()
        if not controls_on_right:
            layout.addLayout(controls)
        layout.addWidget(self.canvas, 1)
        if controls_on_right:
            layout.addLayout(controls)
        self.canvas.mpl_connect("scroll_event", self._zoom)
        self.canvas.mpl_connect("resize_event", self._apply_limits)
        self.canvas.mpl_connect("button_press_event", self._mouse_press)
        self.canvas.mpl_connect("motion_notify_event", self._mouse_move)
        self.canvas.mpl_connect("button_release_event", self._mouse_release)

    def _fullscreen_copy(self):
        """Give fullscreen its own live mouse handlers and independent camera.

        Copying a Matplotlib Figure alone drops the EmbeddingPreview rotation,
        drag-pan and wheel-zoom callbacks, which live on this widget.
        """
        preview = EmbeddingPreview(
            selectable=self._selectable, controls_on_right=True,
            show_bulk_opacity=self.bulk_opacity_slider is not None,
        )
        preview.set_points(
            self._positions, self._colors, self._sizes,
            cell_corners=self._corners, labels=self._labels,
            label_index=self._label_index,
            outlines=self._outlines, widths=self._widths,
            bulk_mask=self._bulk_mask,
        )
        if self.bulk_opacity_slider is not None:
            preview.bulk_opacity_slider.setValue(self.bulk_opacity_slider.value())
        preview.projection.blockSignals(True)
        preview.projection.setCurrentIndex(self.projection.currentIndex())
        preview.projection.blockSignals(False)
        preview._angles = self._angles
        preview._zoom_factor = self._zoom_factor
        preview._pan[:] = self._pan
        if self.site_numbers is not None:
            preview.site_numbers.setChecked(self.site_numbers.isChecked())
        preview._draw_scene()
        preview.canvas.set_fullscreen_enabled(False)
        return preview

    @property
    def view_angles(self):
        return self._angles

    def set_view(self, elev, azim):
        self._angles = (float(elev), float(azim))
        self._pan[:] = 0
        self._draw_scene()

    def project(self, positions):
        """Orthographic Cartesian projection, with depth increasing towards us."""
        elev, azim = np.radians(self._angles)
        right = np.array([-np.sin(azim), np.cos(azim), 0])
        up = np.array([-np.sin(elev) * np.cos(azim),
                       -np.sin(elev) * np.sin(azim), np.cos(elev)])
        direction = np.cross(right, up)
        positions = np.asarray(positions, dtype=float).reshape(-1, 3)
        return positions @ np.column_stack((right, up)), positions @ direction

    def _set_bulk_opacity(self, value):
        self.bulk_opacity_label.setText(f"Bulk opacity: {value}%")
        self._draw_scene()

    def _change_projection(self, *_):
        self._zoom_factor = 1.
        self.set_view(*self.projection.currentData())

    def set_points(self, positions, colors, sizes, *, cell_corners, labels=(), label_index=None,
                   outlines="#515961", widths=.4, bulk_mask=None):
        """Replace geometry; keep the camera when only editing styles/labels."""
        positions = np.asarray(positions, dtype=float).reshape(-1, 3)
        corners = np.asarray(cell_corners, dtype=float)
        if not (np.array_equal(positions, self._positions)
                and np.array_equal(corners, self._corners)):
            self._zoom_factor = 1.
            self._pan[:] = 0
        self._positions, self._corners = positions, corners
        self._colors, self._sizes = np.asarray(colors), np.asarray(sizes)
        self._outlines = np.broadcast_to(outlines, (len(positions),))
        self._widths = np.broadcast_to(widths, (len(positions),))
        self._bulk_mask = np.broadcast_to(
            False if bulk_mask is None else bulk_mask, (len(positions),)
        ).copy()
        self._labels, self._label_index = labels, label_index
        self._draw_scene()

    def _draw_scene(self):
        ax = self.axes
        ax.clear()
        ax.set_axis_off()
        ax.set_aspect("equal", adjustable="datalim")
        self._scatter = None
        self._label_artists = []
        points, depth = self.project(self._positions)
        corners, _ = self.project(self._corners)
        self._extent = np.concatenate((points, corners))
        if len(corners):
            for edge in corners[edge_indices]:
                ax.plot(*edge.T, color="#9c8a60", linewidth=.8, alpha=.75, zorder=3)
        if len(points):
            self._point_order = np.argsort(depth, kind="stable")
            order = self._point_order
            bulk_opacity = (self.bulk_opacity_slider.value() / 100.
                            if self.bulk_opacity_slider is not None else 1.)
            alphas = np.where(self._bulk_mask[order], bulk_opacity, 1.)
            faces = to_rgba_array(self._colors[order])
            edges = to_rgba_array(self._outlines[order])
            faces[:, 3] *= alphas
            edges[:, 3] *= alphas
            self._scatter = ax.scatter(
                *points[order].T, c=faces, s=self._sizes[order],
                edgecolors=edges, linewidths=self._widths[order], zorder=2,
            )
            # Draw all marker outlines in this single, depth-sorted collection.
            # A separate high-zorder selection ring would incorrectly appear
            # through atoms that are closer to the viewer.
            for point, label in zip(points, self._labels):
                self._label_artists.append(ax.annotate(
                    label, point, xytext=(6, 0), textcoords="offset points", fontsize=8,
                    annotation_clip=True, zorder=5,
                ))
        self._update_labels()
        self._apply_limits()

    def _fit_padding(self):
        """Logical pixels reserved for the largest scatter marker and its rim.

        Scatter sizes are areas in points squared (independent of camera zoom).
        Convert the marker radius and half its edge linewidth into canvas pixels;
        the former fixed 28px margin could clip atoms at larger size settings.
        """
        if not len(self._sizes):
            return 28.
        areas = np.asarray(self._sizes, dtype=float)
        outlines = np.asarray(self._widths, dtype=float)
        radii = (np.sqrt(np.maximum(areas, 0)) + np.maximum(outlines, 0)) / 2
        radii = radii[np.isfinite(radii)]
        if not len(radii):
            return 28.
        # Qt widget dimensions are logical pixels; Matplotlib's DPI can be
        # scaled for high-DPI screens, so undo the device-pixel ratio here.
        px_per_point = self.figure.dpi / (
            72. * max(self.canvas.devicePixelRatioF(), 1.)
        )
        return max(28., float(radii.max()) * px_per_point + 8.)

    def _apply_limits(self, *_):
        if not len(self._extent):
            return
        width, height = max(self.canvas.width(), 1), max(self.canvas.height(), 1)
        span = np.ptp(self._extent, axis=0)
        # Fit projected positions and cell corners, including visible marker
        # diameters. Leave a small extra gap beyond the outermost atom.
        padding = self._fit_padding()
        units = max(span[0] / max(width - 2 * padding, 1),
                    span[1] / max(height - 2 * padding, 1), 1e-6)
        centre = (self._extent.min(axis=0) + self._extent.max(axis=0)) / 2 + self._pan
        half = np.array([width, height]) * units / (2 * self._zoom_factor)
        self.axes.set_xlim(centre[0] - half[0], centre[0] + half[0])
        self.axes.set_ylim(centre[1] - half[1], centre[1] + half[1])
        self.canvas.draw_idle()

    def _fit(self):
        self._zoom_factor = 1.
        self._pan[:] = 0
        self._apply_limits()

    def _zoom(self, event):
        if event.inaxes is self.axes:
            self._zoom_factor = np.clip(self._zoom_factor * 1.2 ** event.step, .05, 1000)
            self._apply_limits()

    def _update_labels(self, *_):
        show_all = self.site_numbers is not None and self.site_numbers.isChecked()
        for index, text in enumerate(self._label_artists):
            text.set_visible(show_all or index == self._label_index)
        self.canvas.draw_idle()

    def _mouse_press(self, event):
        self._press = None
        if event.button in (1, 2) and event.inaxes is self.axes:
            self._press = (event.x, event.y, event.button, self._angles, self._pan.copy(),
                           np.ptp(self.axes.get_xlim()), np.ptp(self.axes.get_ylim()))

    def _mouse_move(self, event):
        if self._press is None:
            return
        x, y, button, angles, pan, xspan, yspan = self._press
        dx, dy = event.x - x, event.y - y
        if np.hypot(dx, dy) <= 5:
            return
        if button == 1:
            self.set_view(angles[0] + dy * .5, angles[1] - dx * .5)
            self.projection.blockSignals(True)
            self.projection.setCurrentIndex(0)
            self.projection.blockSignals(False)
        else:
            self._pan = pan - np.array([dx * xspan / self.canvas.width(),
                                        dy * yspan / self.canvas.height()])
            self._apply_limits()

    def _mouse_release(self, event):
        press, self._press = self._press, None
        if (press is None or not self._selectable or event.button != 1
                or event.inaxes is not self.axes or self._scatter is None
                or np.hypot(event.x - press[0], event.y - press[1]) > 5):
            return
        hit, details = self._scatter.contains(event)
        if not hit:
            return
        indices = self._point_order[np.asarray(details["ind"], dtype=int)]
        points, depth = self.project(self._positions[indices])
        screen = self.axes.transData.transform(points)
        distance = np.linalg.norm(screen - [event.x, event.y], axis=1)
        nearest = distance <= distance.min() + 1.
        candidates = np.flatnonzero(nearest)
        index = candidates[np.argmax(depth[nearest])]
        self.pointSelected.emit(int(indices[index]))
