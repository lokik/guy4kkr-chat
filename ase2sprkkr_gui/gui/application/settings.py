"""Persistent application-wide user preferences."""
from __future__ import annotations

import json
from pathlib import Path

from ase2sprkkr_gui.gui.application.atomic_io import atomic_write_json
from ase2sprkkr_gui.gui.application.config import config_home


DATASET_DEFAULT_MODES = ("empty", "datetime", "uuid")
DEFAULT_DATASET_MODE = "datetime"


def default_settings_path() -> Path:
    """Return the per-user application settings path."""
    return config_home() / "settings.json"


class ApplicationSettings:
    """Load and persist application-wide user preferences."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()
        self.viewer = "ase"
        self.dataset_default_mode = DEFAULT_DATASET_MODE
        self.share_python_shell_history = True

    def load(self) -> None:
        """Load settings; corrupt or unreadable files keep defaults."""
        self.viewer = "ase"
        self.dataset_default_mode = DEFAULT_DATASET_MODE
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (
            FileNotFoundError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return
        if not isinstance(data, dict):
            return
        viewer = data.get("viewer")
        if isinstance(viewer, str) and viewer.strip():
            self.viewer = viewer.strip()
        dataset_mode = data.get("dataset_default_mode")
        if dataset_mode in DATASET_DEFAULT_MODES:
            self.dataset_default_mode = dataset_mode
        enabled = data.get("share_python_shell_history")
        if isinstance(enabled, bool):
            self.share_python_shell_history = enabled

    def save(self) -> bool:
        """Persist settings, returning false when the file is not writable."""
        try:
            atomic_write_json(
                self.path,
                {
                    "viewer": self.viewer,
                    "dataset_default_mode": self.dataset_default_mode,
                    "share_python_shell_history": self.share_python_shell_history,
                },
            )
        except OSError:
            return False
        return True
