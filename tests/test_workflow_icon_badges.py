"""Keep workflow badges recognizable and distinct at toolbar sizes."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.misc.icons import badge_icon
from ase2sprkkr_gui.gui.misc.resources import icon_path


def test_recent_and_scf_badges_have_distinct_drawings():
    _app = QApplication.instance() or QApplication([])
    base = QIcon(str(icon_path("calculation-gear.svg")))
    assert not base.isNull()
    images = {}
    for symbol in ("recent", "reconverge", "new"):
        icon = badge_icon(base, symbol)
        assert not icon.isNull()
        for pixels in (24, 26, 48):
            image = icon.pixmap(pixels, pixels).toImage()
            assert not image.isNull()
            assert image.pixelColor(pixels // 2, pixels // 2).alpha() != 0
        images[symbol] = icon.pixmap(48, 48).toImage()

    assert images["recent"] != images["reconverge"]
    assert images["recent"] != images["new"]
    assert images["reconverge"] != images["new"]


def test_recent_structure_retains_original_crystal_icon():
    _app = QApplication.instance() or QApplication([])
    original = QIcon(str(icon_path("bulk_crystal.png")))
    decorated = badge_icon(original, "recent")
    assert not original.isNull()
    assert not decorated.isNull()
    # The upper-left, away from the lower-right badge, is unmodified.
    original_image = original.pixmap(42, 42).toImage()
    recent_image = decorated.pixmap(48, 48).toImage()
    assert original_image.pixelColor(12, 12) == recent_image.pixelColor(13, 13)
