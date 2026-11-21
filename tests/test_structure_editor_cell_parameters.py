"""Geometry checks for interactive lattice lengths/angles editing."""
from __future__ import annotations

import numpy as np
import pytest

from ase2sprkkr_gui.physics.cell_parameters import (
    cell_from_lengths_angles,
    lengths_and_angles,
)


def test_length_change_preserves_basis_directions():
    cell = np.array([[2., 0, 0], [0, 3, 0], [0, 0, 4]])
    new = cell_from_lengths_angles(cell, [5, 3, 4, 90, 90, 90])
    np.testing.assert_allclose(new, np.diag([5, 3, 4]), atol=1e-12)
    np.testing.assert_allclose(lengths_and_angles(new), [5, 3, 4, 90, 90, 90])


def test_angle_changes_keep_reference_orientation_and_handedness():
    reference = np.array([[2, 0, 0], [1, 3, 0], [0, 0, -5.]])
    target = [4, 5, 6, 83, 104, 117]
    result = cell_from_lengths_angles(reference, target)
    np.testing.assert_allclose(lengths_and_angles(result), target, atol=1e-9)
    np.testing.assert_allclose(
        result[0] / np.linalg.norm(result[0]),
        reference[0] / np.linalg.norm(reference[0]),
    )
    assert np.sign(np.linalg.det(result)) == np.sign(np.linalg.det(reference))


@pytest.mark.parametrize("angles", [
    (0, 90, 90), (180, 90, 90), (90, 90, 0),
    (10, 10, 170), (90, 90, 180),
])
def test_reject_invalid_angles(angles):
    reference = np.diag([2, 3, 4])
    with pytest.raises(ValueError):
        cell_from_lengths_angles(reference, [2, 3, 4, *angles])


def test_reject_flat_reference():
    reference = np.array([[2., 0, 0], [0, 2, 0], [1, 1, 0]])
    with pytest.raises(ValueError, match="singular"):
        cell_from_lengths_angles(reference, [2, 2, 2, 90, 90, 90])
