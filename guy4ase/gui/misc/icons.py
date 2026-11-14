"""Common user-facing icons, with a bundled fallback for minimal Qt themes."""
from __future__ import annotations

from PyQt6.QtGui import QIcon

from guy4ase.gui.misc.resources import icon_path


def settings_icon() -> QIcon:
    """Use the system settings symbol, never a file-view icon as fallback."""
    return QIcon.fromTheme(
        "preferences-system", QIcon(str(icon_path("settings-cog.svg")))
    )


def application_icon() -> QIcon:
    """Load the packaged SPR-KKR icon for the application's top-level windows."""
    return QIcon(str(icon_path("sprkkr.svg")))
