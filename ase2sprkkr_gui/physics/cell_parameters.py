"""Convert lattice lengths/angles while preserving the cell orientation.

Vectors are stored as rows (the ASE convention). Fractional coordinates are
left unchanged by the structure editor when the cell is updated.
"""
from __future__ import annotations

import numpy as np


def lengths_and_angles(cell):
    """Return (a, b, c, alpha, beta, gamma), in Å and degrees."""
    cell = np.asarray(cell, dtype=float)
    if cell.shape != (3, 3) or not np.all(np.isfinite(cell)):
        raise ValueError("Lattice vectors must form a finite 3 × 3 matrix")
    lengths = np.linalg.norm(cell, axis=1)
    if np.any(lengths < 1e-9):
        raise ValueError("All three lattice vectors must have nonzero lengths")

    def angle(u, v, lu, lv):
        cosine = np.clip(np.dot(u, v) / (lu * lv), -1.0, 1.0)
        return float(np.degrees(np.arccos(cosine)))

    return (
        *map(float, lengths),
        angle(cell[1], cell[2], lengths[1], lengths[2]),
        angle(cell[0], cell[2], lengths[0], lengths[2]),
        angle(cell[0], cell[1], lengths[0], lengths[1]),
    )


def cell_from_lengths_angles(reference_cell, parameters):
    """Construct a cell with target lengths/angles and the old handedness.

    Keep the original a direction, the original ab plane, and the sign of
    the cell volume. This avoids arbitrarily rotating or mirroring a cell
    when only its lengths or inter-vector angles change.
    """
    reference = np.asarray(reference_cell, dtype=float)
    old = lengths_and_angles(reference)
    params = np.asarray(parameters, dtype=float)
    if params.shape != (6,) or not np.all(np.isfinite(params)):
        raise ValueError("Six finite lattice parameters are required")
    a, b, c, alpha, beta, gamma = params
    if np.any(params[:3] <= 0):
        raise ValueError("Lattice lengths must be positive")
    if np.any(params[3:] <= 0) or np.any(params[3:] >= 180):
        raise ValueError("Cell angles must be strictly between 0° and 180°")

    norm_a, norm_b, _ = old[:3]
    e1 = reference[0] / norm_a
    in_plane = reference[1] - np.dot(reference[1], e1) * e1
    norm_plane = np.linalg.norm(in_plane)
    if norm_plane <= 1e-10 * norm_b:
        raise ValueError("Cannot edit cell angles when a and b are parallel")
    e2 = in_plane / norm_plane
    normal = np.cross(e1, e2)
    handedness = np.dot(reference[2], normal)
    if abs(handedness) <= 1e-10 * old[2]:
        raise ValueError("Cannot edit cell angles of a flat, singular cell")
    e3 = normal if handedness > 0 else -normal

    alpha, beta, gamma = np.deg2rad([alpha, beta, gamma])
    sin_gamma = np.sin(gamma)
    if abs(sin_gamma) < 1e-9:
        raise ValueError("Gamma angle makes the first two vectors parallel")
    x = np.cos(beta)
    y = (np.cos(alpha) - x * np.cos(gamma)) / sin_gamma
    z_squared = 1.0 - x * x - y * y
    if z_squared <= 1e-12:
        raise ValueError("These angles cannot form a nondegenerate 3D cell")

    result = np.asarray([
        a * e1,
        b * (np.cos(gamma) * e1 + sin_gamma * e2),
        c * (x * e1 + y * e2 + np.sqrt(z_squared) * e3),
    ])
    return result
