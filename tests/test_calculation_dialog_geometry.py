from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication, QWidget

from ase2sprkkr_gui.gui.flows import calculation as calculation_flow


def _app():
    return QApplication.instance() or QApplication([])


def test_position_like_window_reuses_saved_top_left_without_copying_size(monkeypatch):
    _application = _app()
    window = QWidget()
    window.resize(650, 330)
    calls = []

    def placement(target, window_id, *, default_size):
        calls.append((target, window_id, default_size))
        return SimpleNamespace(geometry=QRect(240, 160, 1180, 740))

    monkeypatch.setattr(calculation_flow, "window_placement", placement)

    calculation_flow._position_like_window(window, "guided-input")

    assert calls == [(window, "guided-input", (650, 330))]
    assert window.pos() == QPoint(240, 160)
    assert window.size().width() == 650
    assert window.size().height() == 330
    window.close()
