"""Per-user configuration paths shared by GUI persistence services."""
from __future__ import annotations

from pathlib import Path

import platformdirs


def config_home() -> Path:
    """Return the GUI configuration directory within Ase2sprkkr's settings."""
    return Path(platformdirs.user_config_dir("ase2sprkkr", appauthor="ase2sprkkr")) / "gui"
