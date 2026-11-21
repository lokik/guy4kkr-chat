"""Persistent application-wide user preferences."""
from __future__ import annotations

import json
from pathlib import Path

from ase2sprkkr_gui.gui.application.atomic_io import atomic_write_json
from ase2sprkkr_gui.gui.application.config import config_home
from ase2sprkkr_gui.gui.input_parameters.task_preferences import (
    default_preferred_task_names, effective_preferred, task_ui_name,
)
from ase2sprkkr_gui.gui.plots.atom_sizes import (
    MAX_ATOM_SIZE_PERCENT, MIN_ATOM_SIZE_PERCENT, set_atom_appearance,
)


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
        self.atom_size_percent = 100
        self.atom_relative_sizes = True
        self.atom_potential_radii = True
        self.show_embedded_cluster_hint = True
        # None means follow GUI-supported tasks automatically, without a
        # persisted preference list. An empty tuple is an explicit selection.
        self.preferred_tasks: tuple[str, ...] | None = None
        self.preferred_supported_snapshot: tuple[str, ...] | None = None

    def effective_preferred_tasks(self) -> tuple[str, ...]:
        return effective_preferred(
            self.preferred_tasks, self.preferred_supported_snapshot,
        )

    def newly_supported_tasks(self) -> tuple[str, ...]:
        """New GUI editors since a customized task selection was saved."""
        if self.preferred_tasks is None or self.preferred_supported_snapshot is None:
            return ()
        previous = {task_ui_name(name) for name in self.preferred_supported_snapshot}
        return tuple(
            name for name in default_preferred_task_names() if name not in previous
        )

    def acknowledge_supported_tasks(self, *, add: bool) -> None:
        """Record a user's decision, retaining task order and explicit removals."""
        if self.preferred_tasks is None or self.preferred_supported_snapshot is None:
            return
        new = self.newly_supported_tasks()
        if add:
            self.preferred_tasks = tuple(dict.fromkeys(
                (*effective_preferred(self.preferred_tasks), *new)
            ))
        self.preferred_supported_snapshot = default_preferred_task_names()

    def load(self) -> None:
        """Load settings; corrupt or unreadable files keep defaults."""
        self.viewer = "ase"
        self.dataset_default_mode = DEFAULT_DATASET_MODE
        self.atom_size_percent = 100
        self.atom_relative_sizes = True
        self.atom_potential_radii = True
        self.show_embedded_cluster_hint = True
        self.preferred_tasks = None
        self.preferred_supported_snapshot = None
        self._apply_atom_appearance()
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
        size = data.get("atom_size_percent")
        if type(size) is int and MIN_ATOM_SIZE_PERCENT <= size <= MAX_ATOM_SIZE_PERCENT:
            self.atom_size_percent = size
        relative = data.get("atom_relative_sizes")
        if isinstance(relative, bool):
            self.atom_relative_sizes = relative
        potential = data.get("atom_potential_radii")
        if isinstance(potential, bool):
            self.atom_potential_radii = potential
        hint = data.get("show_embedded_cluster_hint")
        if isinstance(hint, bool):
            self.show_embedded_cluster_hint = hint

        def task_names(key):
            value = data.get(key)
            if (not isinstance(value, list)
                    or any(not isinstance(name, str) or not name.strip() for name in value)):
                return None
            return tuple(dict.fromkeys(task_ui_name(name.strip()) for name in value))

        selected = task_names("preferred_tasks")
        baseline = task_names("preferred_supported_tasks")
        # A customized list must have its supported-task baseline. The
        # application never writes one without the other.
        if selected is not None and baseline is not None:
            self.preferred_tasks = tuple(name for name in selected if name != "SCF")
            self.preferred_supported_snapshot = tuple(
                name for name in baseline if name != "SCF"
            )
        self._apply_atom_appearance()

    def _apply_atom_appearance(self) -> None:
        set_atom_appearance(
            self.atom_size_percent, self.atom_relative_sizes,
            self.atom_potential_radii,
        )

    def save(self) -> bool:
        """Persist settings, returning false when the file is not writable."""
        data = {
            "viewer": self.viewer,
            "dataset_default_mode": self.dataset_default_mode,
            "share_python_shell_history": self.share_python_shell_history,
            "atom_size_percent": self.atom_size_percent,
            "atom_relative_sizes": self.atom_relative_sizes,
            "atom_potential_radii": self.atom_potential_radii,
            "show_embedded_cluster_hint": self.show_embedded_cluster_hint,
        }
        if self.preferred_tasks is not None:
            data["preferred_tasks"] = list(effective_preferred(self.preferred_tasks))
            data["preferred_supported_tasks"] = list(dict.fromkeys(
                task_ui_name(name) for name in (
                    self.preferred_supported_snapshot
                    if self.preferred_supported_snapshot is not None
                    else default_preferred_task_names()
                )
                if task_ui_name(name) != "SCF"
            ))
        try:
            atomic_write_json(self.path, data)
        except OSError:
            return False
        self._apply_atom_appearance()
        return True
