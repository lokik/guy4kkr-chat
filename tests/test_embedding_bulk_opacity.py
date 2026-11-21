"""Bulk host opacity in the embedded-cluster structure preview."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
import pytest

from ase2sprkkr_gui.gui.widgets.structures.embedding_preview import EmbeddingPreview


def test_bulk_opacity_slider_fades_only_marked_sites():
    preview = EmbeddingPreview(controls_on_right=True, show_bulk_opacity=True)
    slider = preview.bulk_opacity_slider
    assert slider is not None
    assert slider.value() == 100
    controls = preview.layout().itemAt(1).layout()
    assert controls.indexOf(slider) > controls.indexOf(preview.fit_button)
    preview.set_points(
        [[0, 0, 0], [1, 0, 0], [2, 0, 0]],
        ["#a6aeb6", "#4b92cf", "#d88c49"],
        [15, 55, 65], cell_corners=np.empty((0, 3)),
        outlines=["#515961"] * 3, widths=[.4, 1.5, .4],
        bulk_mask=[True, False, False],
    )
    preview._zoom_factor = 1.75
    slider.setValue(30)
    assert preview.bulk_opacity_label.text() == "Bulk opacity: 30%"
    assert preview._zoom_factor == 1.75
    expected = np.array([.30, 1., 1.])[preview._point_order]
    np.testing.assert_allclose(preview._scatter.get_facecolors()[:, 3], expected)
    np.testing.assert_allclose(preview._scatter.get_edgecolors()[:, 3], expected)
    slider.setValue(0)
    np.testing.assert_allclose(
        preview._scatter.get_facecolors()[:, 3],
        np.array([0., 1., 1.])[preview._point_order],
    )
    preview.close()


def test_embedding_dialog_fades_host_but_not_cluster_or_selection():
    pytest.importorskip("ase2sprkkr.sprkkr.embedding_geometry")
    from ase import Atoms
    from ase2sprkkr_gui.gui.dialogs.structures.embedding import BuildEmbeddingDialog

    host = Atoms("Cu", cell=[2., 2., 2.], positions=[[0, 0, 0]], pbc=True)
    dialog = BuildEmbeddingDialog(host)
    centre = dialog.draft.center
    dialog.draft.include([centre])
    dialog._render()

    preview = dialog.global_preview
    assert preview.bulk_opacity_slider is not None
    mask = preview._bulk_mask
    assert len(mask) == len(dialog._rendered_sites)
    assert np.any(mask)
    assert not mask[dialog._rendered_sites.index(centre)]
    preview.bulk_opacity_slider.setValue(25)
    expected = np.where(mask, .25, 1.)[preview._point_order]
    np.testing.assert_allclose(preview._scatter.get_facecolors()[:, 3], expected)
    assert dialog.local_preview.bulk_opacity_slider is None
    dialog.close()


def test_selected_outline_is_occluded_by_nearer_atoms():
    preview = EmbeddingPreview()
    preview.set_view(90, 0)  # Positive z is towards the viewer.
    preview.set_points(
        [[0, 0, 0], [0, 0, 1]],
        ["#b0b0b0", "#a6aeb6"], [100, 400],
        cell_corners=np.empty((0, 3)),
        outlines=["#ffcf4f", "#333a42"], widths=[3.0, 0.65],
    )
    np.testing.assert_array_equal(preview._point_order, [0, 1])
    # A selected atom behind another atom must not get a separate
    # high-zorder highlight collection drawn over the foreground atom.
    assert len(preview.axes.collections) == 1
    assert preview.axes.collections[0] is preview._scatter
    np.testing.assert_allclose(preview._scatter.get_linewidths(), [3.0, 0.65])
    preview.close()


def test_fullscreen_preserves_bulk_opacity_mask_and_independent_slider():
    preview = EmbeddingPreview(show_bulk_opacity=True)
    preview.set_points(
        [[0, 0, 0], [1, 0, 0]],
        ["#a6aeb6", "#4b92cf"], [55, 70],
        cell_corners=np.empty((0, 3)), bulk_mask=[True, False],
    )
    preview.bulk_opacity_slider.setValue(35)

    fullscreen = preview._fullscreen_copy()
    assert fullscreen.bulk_opacity_slider is not None
    assert fullscreen.bulk_opacity_slider.value() == 35
    assert fullscreen.bulk_opacity_label.text() == "Bulk opacity: 35%"
    np.testing.assert_array_equal(fullscreen._bulk_mask, [True, False])
    expected = np.where(fullscreen._bulk_mask[fullscreen._point_order], 0.35, 1.)
    np.testing.assert_allclose(fullscreen._scatter.get_facecolors()[:, 3], expected)
    np.testing.assert_allclose(fullscreen._scatter.get_edgecolors()[:, 3], expected)
    assert not fullscreen.canvas._fullscreen_enabled

    fullscreen.bulk_opacity_slider.setValue(10)
    assert preview.bulk_opacity_slider.value() == 35
    fullscreen.close()
    preview.close()
