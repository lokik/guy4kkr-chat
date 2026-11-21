"""Small Qt-independent presentation vocabulary shared by GUI views."""
from __future__ import annotations

from typing import Literal

from ase2sprkkr_gui.gui.workspace_semantics import EmptySpheresAction as _EmptySpheresAction
from ase2sprkkr_gui.physics.lattice import StructureKind

def structure_kind_label(kind: StructureKind | None) -> str | None:
    """Human-readable structure classification shared by Guided windows."""
    return {
        "3d": "Bulk (3D)",
        "2d": "2D structure",
        "0d": "Embedded cluster",
        "unknown": "Unknown structure",
        None: None,
    }[kind]


ActionCategory = Literal[
    "structure", "load", "calculation", "destructive", "results", "neutral"
]


def empty_spheres_action_title(action: _EmptySpheresAction) -> str:
    """Return the shared user-facing label for an empty-sphere recommendation."""
    return {
        _EmptySpheresAction.ADD: "Add Empty Spheres",
        _EmptySpheresAction.RECALCULATE: "Recalculate Empty Spheres",
    }[action]
