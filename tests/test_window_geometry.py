from __future__ import annotations

import json

from PyQt6.QtCore import QRect, QSize
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.application.window_geometry import (
    WindowGeometryStore,
    adjust_window_geometry,
    restore_window_geometry,
    window_geometry_store,
)


def test_adjust_window_geometry_clamps_size_and_position() -> None:
    available = QRect(0, 0, 1280, 720)
    assert adjust_window_geometry(QRect(1100, 650, 600, 500), available) == QRect(
        680, 220, 600, 500
    )
    assert adjust_window_geometry(QRect(-100, -50, 1800, 900), available) == QRect(
        0, 0, 1280, 720
    )


def test_adjust_window_geometry_centers_disconnected_window() -> None:
    available = QRect(0, 0, 1920, 1040)
    restored = adjust_window_geometry(
        QRect(3000, 100, 1000, 700),
        available,
        center_if_outside=True,
    )
    assert restored == QRect(460, 170, 1000, 700)


def test_restore_window_geometry_replaces_too_small_saved_size() -> None:
    available = QRect(0, 0, 1920, 1040)
    default_size = QSize(1120, 700)

    # Full-HD-like available area gives a 480 x 260 sentinel.
    restored = restore_window_geometry(
        QRect(100, 120, 479, 500),
        available,
        default_size=default_size,
    )
    assert restored == QRect(100, 120, 1120, 700)

    # The sentinel itself is still a legitimate saved size.
    restored = restore_window_geometry(
        QRect(100, 120, 480, 260),
        available,
        default_size=default_size,
    )
    assert restored == QRect(100, 120, 480, 260)

    # If the tiny saved window came from a disconnected screen, restore the
    # default size centered on the current one rather than pinning it to an edge.
    restored = restore_window_geometry(
        QRect(3000, 100, 100, 100),
        available,
        default_size=default_size,
        center_if_outside=True,
    )
    assert restored == QRect(400, 170, 1120, 700)


def test_restore_window_geometry_caps_sentinel_by_half_default_size() -> None:
    available = QRect(0, 0, 3840, 2080)
    default_size = QSize(1120, 700)

    # On a large screen, the sentinel stops growing at half the default size.
    restored = restore_window_geometry(
        QRect(100, 120, 700, 349),
        available,
        default_size=default_size,
    )
    assert restored == QRect(100, 120, 1120, 700)

    restored = restore_window_geometry(
        QRect(100, 120, 560, 350),
        available,
        default_size=default_size,
    )
    assert restored == QRect(100, 120, 560, 350)


def test_window_geometry_store_ignores_corrupt_entries(tmp_path) -> None:
    path = tmp_path / "window_geometry.json"
    path.write_text(
        json.dumps(
            {
                "windows": {
                    "good": {
                        "x": 10,
                        "y": 20,
                        "width": 800,
                        "height": 600,
                        "maximized": True,
                        "screen": "screen-1",
                    },
                    "bad": {"x": 0, "y": 0, "width": -1, "height": 20},
                }
            }
        ),
        encoding="utf-8",
    )
    store = WindowGeometryStore(path)
    assert set(store._states) == {"good"}
    assert store._states["good"].maximized is True
    assert store._states["good"].screen == "screen-1"


def test_default_window_geometry_store_is_owned_by_application() -> None:
    application = QApplication.instance() or QApplication([])

    store = window_geometry_store()

    assert store.parent() is application
    assert window_geometry_store() is store
