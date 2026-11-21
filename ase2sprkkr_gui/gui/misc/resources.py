"""Locations of the package's installed graphical assets."""
from __future__ import annotations
from pathlib import Path

_ASSETS = Path(__file__).resolve().parents[2] / "assets"


def icon_path(name: str) -> Path:
    return _ASSETS / "icons" / name


def task_icon_path(task: str) -> Path | None:
    """Find assets/task-icons/scf.svg (or png), using lowercase task names."""
    import re

    name = str(task).lower()
    if not re.fullmatch(r"[a-z0-9_]+", name):
        return None
    for extension in ("svg", "png"):
        path = _ASSETS / "task-icons" / f"{name}.{extension}"
        if path.is_file():
            return path
    return None
