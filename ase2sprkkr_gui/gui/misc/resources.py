"""Locations of the package's installed graphical assets."""
from pathlib import Path

_ASSETS = Path(__file__).resolve().parents[2] / "assets"


def icon_path(name: str) -> Path:
    return _ASSETS / "icons" / name
