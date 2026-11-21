"""Fullscreen Matplotlib previews must not steal the original figure."""
from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.widgets import matplotlib_preview as previews
from ase2sprkkr_gui.gui.widgets.structures.embedding_preview import EmbeddingPreview


def test_double_click_opens_fullscreen_and_other_buttons_do_not(monkeypatch):
    canvas = previews.PreviewFigureCanvas(Figure())
    calls = []
    monkeypatch.setattr(previews.PreviewFigureCanvas, "open_fullscreen",
                        lambda self: calls.append(self))
    canvas.show()
    QApplication.processEvents()
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton)
    assert calls == [canvas]

    QTest.mouseDClick(canvas, Qt.MouseButton.RightButton)
    assert calls == [canvas]
    canvas.close()


def test_fullscreen_is_modal_and_uses_an_independent_3d_figure(monkeypatch):
    figure = Figure()
    axes = figure.add_subplot(111, projection="3d")
    axes.scatter([0, 1], [0, 1], [0, 1])
    original_xlim = axes.get_xlim()
    canvas = previews.PreviewFigureCanvas(figure)
    seen = []

    def fake_show_fullscreen(dialog):
        seen.append("fullscreen")

    def fake_exec(dialog):
        assert dialog.isModal()
        assert dialog.canvas.figure is not figure
        assert dialog.canvas.figure.axes[0].name == "3d"
        dialog.canvas.figure.axes[0].set_xlim(10, 20)
        seen.append("modal")
        return 0

    monkeypatch.setattr(previews._FullscreenFigureDialog, "showFullScreen",
                        fake_show_fullscreen)
    monkeypatch.setattr(previews._FullscreenFigureDialog, "exec", fake_exec)
    canvas.open_fullscreen()

    assert seen == ["fullscreen", "modal"]
    assert canvas.figure is figure
    assert axes.get_xlim() == original_xlim
    canvas.close()


def test_non_pickleable_plot_still_expands_as_a_snapshot(monkeypatch):
    figure = Figure()
    figure.add_subplot(111).plot([0, 1], [1, 0])

    def cannot_pickle(*args, **kwargs):
        raise TypeError("custom artist cannot be pickled")

    monkeypatch.setattr(previews.pickle, "dumps", cannot_pickle)
    snapshot = previews._fullscreen_figure(figure)
    assert snapshot is not figure
    assert len(snapshot.axes) == 1
    assert len(snapshot.axes[0].images) == 1


def test_fullscreen_corner_button_uses_the_double_click_action(monkeypatch):
    canvas = previews.PreviewFigureCanvas(Figure())
    calls = []
    monkeypatch.setattr(previews.PreviewFigureCanvas, "open_fullscreen",
                        lambda self: calls.append(self))
    canvas.resize(320, 240)
    canvas.show()
    QApplication.processEvents()

    button = canvas.fullscreen_button
    assert button.isVisible()
    assert button.x() < 30 and button.y() < 30
    assert button.toolTip() == "Open fullscreen preview"
    assert "border: none" in button.styleSheet()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton)
    assert calls == [canvas, canvas]
    canvas.close()


def test_embedding_fullscreen_retains_live_navigation_and_independent_state(monkeypatch):
    original = EmbeddingPreview(selectable=True)
    original.set_points(
        [[0, 0, 0], [1, 1, 1]], ["red", "blue"], [60, 70],
        cell_corners=np.empty((0, 3)),
    )
    original.set_view(15, 30)
    original._zoom_factor = 1.4
    saved_angles = original.view_angles
    saved_zoom = original._zoom_factor
    seen = []

    def inspect_fullscreen(dialog):
        viewer = dialog.layout().itemAt(1).widget()
        assert isinstance(viewer, EmbeddingPreview)
        assert viewer is not original
        assert viewer.axes is not original.axes
        assert viewer.view_angles == saved_angles
        assert viewer._zoom_factor == saved_zoom
        assert not viewer.canvas.fullscreen_button.isVisible()

        viewer._zoom(SimpleNamespace(inaxes=viewer.axes, step=1))
        assert viewer._zoom_factor > saved_zoom

        viewer._mouse_press(SimpleNamespace(
            x=100, y=100, button=1, inaxes=viewer.axes))
        viewer._mouse_move(SimpleNamespace(x=125, y=115))
        assert viewer.view_angles != saved_angles

        viewer._mouse_press(SimpleNamespace(
            x=100, y=100, button=2, inaxes=viewer.axes))
        viewer._mouse_move(SimpleNamespace(x=125, y=115))
        assert np.any(viewer._pan != 0)
        seen.append(True)
        return 0

    monkeypatch.setattr(previews._FullscreenWidgetDialog, "showFullScreen",
                        lambda self: None)
    monkeypatch.setattr(previews._FullscreenWidgetDialog, "exec",
                        inspect_fullscreen)
    original.canvas.open_fullscreen()
    assert seen == [True]
    assert original.view_angles == saved_angles
    assert original._zoom_factor == saved_zoom
    assert np.all(original._pan == 0)
    original.close()
