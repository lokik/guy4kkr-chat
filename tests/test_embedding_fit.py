"""Fit must include the on-screen diameters of atom markers, not only centres."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import numpy as np
import pytest

from ase2sprkkr_gui.gui.widgets.structures.embedding_preview import EmbeddingPreview


def _set_atoms(preview, sizes, widths):
    preview.set_points(
        [[0., 0., 0.], [10., 0., 0.]],
        ["red", "blue"], sizes,
        cell_corners=np.empty((0, 3)),
        widths=widths,
    )


def _assert_markers_inside_canvas(preview):
    """Marker radius includes half the scatter linewidth."""
    preview.canvas.draw()
    projected, _ = preview.project(preview._positions)
    centres = preview.axes.transData.transform(projected)
    radii = (
        np.sqrt(preview._sizes) + preview._widths
    ) / 2 * preview.figure.dpi / 72.
    bbox = preview.axes.bbox
    assert np.all(centres[:, 0] - radii >= bbox.x0 - 1)
    assert np.all(centres[:, 0] + radii <= bbox.x1 + 1)
    assert np.all(centres[:, 1] - radii >= bbox.y0 - 1)
    assert np.all(centres[:, 1] + radii <= bbox.y1 + 1)


def test_fit_includes_large_atom_diameters_and_selected_outlines():
    preview = EmbeddingPreview()
    preview.canvas.resize(400, 280)
    preview.set_view(90, -90)  # project the two atoms along the x axis

    _set_atoms(preview, [36., 36.], [0.5, 0.5])
    small_span = np.ptp(preview.axes.get_xlim())
    assert preview._fit_padding() == 28.

    _set_atoms(preview, [36., 6400.], [0.5, 5.])
    large_span = np.ptp(preview.axes.get_xlim())
    assert large_span > small_span
    px_per_point = preview.figure.dpi / (
        72. * max(preview.canvas.devicePixelRatioF(), 1.)
    )
    assert preview._fit_padding() == pytest.approx(
        max(28., (80. + 5.) / 2 * px_per_point + 8.)
    )
    _assert_markers_inside_canvas(preview)

    # Fit restores visibility after a zoom/pan without altering the view angle.
    preview._zoom_factor = 2.
    preview._pan[:] = [2., 1.]
    preview._apply_limits()
    preview.fit_button.click()
    assert preview._zoom_factor == 1.
    np.testing.assert_array_equal(preview._pan, [0., 0.])
    _assert_markers_inside_canvas(preview)
    preview.close()


def test_fullscreen_copy_refits_the_same_marker_diameters_on_resize():
    preview = EmbeddingPreview()
    preview.set_view(90, -90)
    _set_atoms(preview, [2500., 4900.], [1., 3.])

    fullscreen = preview._fullscreen_copy()
    fullscreen.canvas.resize(440, 260)
    fullscreen._fit()
    assert fullscreen._fit_padding() == pytest.approx(preview._fit_padding())
    _assert_markers_inside_canvas(fullscreen)
    fullscreen.close()
    preview.close()
