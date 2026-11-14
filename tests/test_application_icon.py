"""Rendering and inheritance of the packaged SPR-KKR application icon."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.misc.icons import application_icon
from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.main import GuiApplication


def test_orbital_application_icon_renders_at_window_sizes():
    assert icon_path("sprkkr-orbital.svg").is_file()
    icon = application_icon()
    assert not icon.isNull()
    for size in (16, 32, 64, 128):
        image = icon.pixmap(size, size)
        assert not image.isNull()
        assert image.width() == size and image.height() == size


def test_gui_application_icon_is_inherited_by_both_primary_windows(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous_icon = app.windowIcon()
    previous_name = app.applicationName()
    app.setWindowIcon(QIcon())
    try:
        gui = GuiApplication(recent_files_path=tmp_path / "recent.json")
        assert app.applicationName() == "Ase2sprkkr"
        assert not app.windowIcon().isNull()
        for window in (gui.create_workflow_window(), gui.create_main_window()):
            icon = window.windowIcon()
            assert not icon.isNull()
            assert not icon.pixmap(32, 32).isNull()
    finally:
        app.setWindowIcon(previous_icon)
        app.setApplicationName(previous_name)


def test_icon_is_genuine_vector():
    """The app icon contains shapes, not an embedded raster or image reference."""
    source = icon_path("sprkkr-orbital.svg").read_text(encoding="utf-8")
    assert "<image" not in source
    assert "data:image/" not in source
    assert "<path " in source
    assert source.count('<circle ') >= 114


def test_icon_uses_soft_glow_and_muted_electrons():
    """Lettering stays prominent while electron markers blend with the background."""
    source = icon_path("sprkkr-orbital.svg").read_text(encoding="utf-8")
    assert 'id="letterBlur"' in source
    assert 'id="electronBlur"' in source
    assert source.count('filter="url(#letterBlur)"') == 114
    assert source.count('filter="url(#electronBlur)"') == 3
