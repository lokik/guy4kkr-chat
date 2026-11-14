"""Regression tests for the bundled SPR-KKR application icon."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.misc.icons import application_icon
from guy4ase.gui.misc.resources import icon_path
from guy4ase.main import GuiApplication


def test_application_icon_is_packaged_and_renders_at_multiple_sizes():
    assert icon_path("sprkkr.svg").is_file()
    icon = application_icon()
    assert not icon.isNull()
    for size in (16, 32, 128):
        assert not icon.pixmap(size, size).isNull()


def test_gui_assigns_icon_to_application_and_top_level_windows(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous_icon = app.windowIcon()
    app.setWindowIcon(QIcon())
    try:
        gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
        assert not app.windowIcon().isNull()
        for window in (gui.create_workflow_window(), gui.create_main_window()):
            assert not window.windowIcon().isNull()
            assert not window.windowIcon().pixmap(32, 32).isNull()
    finally:
        app.setWindowIcon(previous_icon)
