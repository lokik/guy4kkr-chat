"""Pure lattice queries and transformations."""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
from ase2sprkkr import SPRKKRAtoms

StructureKind = Literal["2d", "3d", "unknown"]


def detect_structure_kind(atoms: Any | None) -> StructureKind | None:
    """Classify structures supported by the bulk and layered workflows."""
    if atoms is None:
        return None
    periodic = sum(atoms.get_pbc())
    if periodic == 3:
        return "3d"
    if (
        periodic == 2
        and isinstance(atoms, SPRKKRAtoms)
        and {"left", "central", "right"}.issubset(atoms.regions)
    ):
        return "2d"
    return "unknown"


def scale_lattice_to_lengths(lattice, lengths):
    lattice_array = np.asarray(lattice, dtype=float)
    if lattice_array.shape != (3, 3):
        raise ValueError("Lattice must be a 3x3 matrix of row vectors.")

    target_lengths = np.asarray(lengths, dtype=float)
    if target_lengths.shape != (3,):
        raise ValueError("Lengths must contain exactly three values: a, b, c.")
    if (target_lengths <= 0).any():
        raise ValueError("Lattice constants must be positive numbers.")

    original_lengths = np.linalg.norm(lattice_array, axis=1)
    if np.isclose(original_lengths, 0.0).any():
        raise ValueError("Cannot scale structure with zero lattice constant.")

    factors = target_lengths / original_lengths
    scaled_lattice = lattice_array.copy()
    for axis in range(3):
        scaled_lattice[axis] = lattice_array[axis] * factors[axis]
    return scaled_lattice


def match_structure_axis_length(source, target, axis):
    """Return a copy of ``source`` with one cell-vector length matching ``target``.

    The source vector keeps its direction. Atomic positions are scaled with
    the changed cell, matching the behavior of an ordinary lattice stretch.
    """
    if not isinstance(axis, (int, np.integer)) or not 0 <= int(axis) < 3:
        raise ValueError("Axis must be one of 0, 1 or 2.")
    axis = int(axis)
    source_cell = np.asarray(source.get_cell(), dtype=float).copy()
    target_cell = np.asarray(target.get_cell(), dtype=float)
    if source_cell.shape != (3, 3) or target_cell.shape != (3, 3):
        raise ValueError("Source and target cells must be 3x3 matrices.")

    source_vector = source_cell[axis]
    target_vector = target_cell[axis]
    source_length = float(np.linalg.norm(source_vector))
    target_length = float(np.linalg.norm(target_vector))
    if source_length <= 1e-12 or target_length <= 1e-12:
        raise ValueError(
            "Selected axis has near-zero length and cannot be stretched."
        )

    source_cell[axis] = source_vector / source_length * target_length
    result = source.copy()
    result.set_cell(source_cell, scale_atoms=True)
    return result
