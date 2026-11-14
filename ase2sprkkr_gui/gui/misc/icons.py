"""Common user-facing icons, with a bundled fallback for minimal Qt themes."""
from __future__ import annotations

from PyQt6.QtGui import QIcon

from ase2sprkkr_gui.gui.misc.resources import icon_path


def settings_icon() -> QIcon:
    """Use the system settings symbol, never a file-view icon as fallback."""
    return QIcon.fromTheme(
        "preferences-system", QIcon(str(icon_path("settings-cog.svg")))
    )

def application_icon() -> QIcon:
    """Return the bundled, platform-independent SPR-KKR application icon."""
    return QIcon(str(icon_path("sprkkr-orbital.svg")))
