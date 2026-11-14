"""Tests for the XBand empty-sphere parameter dialog."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.dialogs.structures.empty_spheres import EmptySpheresDialog


def test_empty_sphere_defaults():
    _application = QApplication.instance() or QApplication([])
    dialog = EmptySpheresDialog()

    assert dialog.parameters() == {
        "min_radius": 0.65,
        "max_radius": 2.0,
        "max_spheres": 256,
        "mesh": (24, 24, 24),
    }
    dialog.close()


def test_empty_sphere_initial_values():
    _application = QApplication.instance() or QApplication([])
    dialog = EmptySpheresDialog(
        initial={
            "min_radius": 0.8,
            "max_radius": 1.8,
            "max_spheres": 128,
            "mesh": (20, 22, 24),
        }
    )

    assert dialog.parameters() == {
        "min_radius": 0.8,
        "max_radius": 1.8,
        "max_spheres": 128,
        "mesh": (20, 22, 24),
    }
    dialog.close()
