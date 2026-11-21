"""Pure lattice-transformation regressions."""
import numpy as np
import pytest
from ase import Atoms
from ase.build import bulk
from ase2sprkkr.sprkkr.build import semiinfinite_system

from ase2sprkkr_gui.physics.lattice import (
    detect_structure_kind,
    match_structure_axis_length,
)


@pytest.mark.parametrize("operation,selector,values", [
    ("scale_atoms", "select_scale_lengths", (2.0, 2.0, 2.0)),
    ("repeat_atoms", "select_repeat_factors", (1.0, 1.0, 1.0)),
])
def test_unchanged_transform_retains_structure(monkeypatch, operation, selector, values):
    from ase2sprkkr_gui.gui.dialogs.structures import transforms

    atoms = Atoms("Fe", cell=[2.0, 2.0, 2.0], pbc=True)
    monkeypatch.setattr(transforms, selector, lambda **_kwargs: values)

    def forbid_copy():
        raise AssertionError("An unchanged dialog must retain the original structure")

    monkeypatch.setattr(atoms, "copy", forbid_copy)
    assert getattr(transforms, operation)(atoms) is atoms


@pytest.mark.parametrize(
    'pbc, expected',
    [
        ((False, False, False), 'unknown'),
        ((True, False, False), 'unknown'),
        ((True, True, False), 'unknown'),
        ((True, True, True), '3d'),
    ],
)
def test_structure_kind_is_derived_from_periodicity(pbc, expected):
    atoms = Atoms('H', cell=[1.0, 1.0, 1.0], pbc=pbc)

    assert detect_structure_kind(atoms) == expected


def test_structure_kind_recognizes_sprkkr_layered_regions():
    atoms = semiinfinite_system(bulk("Cu", "sc", a=2.0), (0, 0))

    assert detect_structure_kind(atoms) == "2d"


def test_structure_kind_handles_missing_structure():
    assert detect_structure_kind(None) is None


def test_match_structure_axis_length_preserves_direction_and_inputs():
    source = Atoms(
        "H",
        scaled_positions=[[0.5, 0.5, 0.5]],
        cell=[[2.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 4.0]],
    )
    target = Atoms("He", cell=[1.0, 6.0, 1.0])
    source_cell = source.cell.array.copy()
    source_position = source.positions.copy()

    result = match_structure_axis_length(source, target, 1)

    assert result is not source
    assert np.allclose(result.cell[1], [0.0, 6.0, 0.0])
    assert np.allclose(result.get_scaled_positions(), [[0.5, 0.5, 0.5]])
    assert np.allclose(source.cell.array, source_cell)
    assert np.allclose(source.positions, source_position)


@pytest.mark.parametrize("axis", [-1, 3, 1.5])
def test_match_structure_axis_length_rejects_invalid_axis(axis):
    atoms = Atoms("H", cell=[1.0, 1.0, 1.0])

    with pytest.raises(ValueError, match="Axis must"):
        match_structure_axis_length(atoms, atoms, axis)


def test_match_structure_axis_length_rejects_zero_length_vector():
    source = Atoms("H", cell=[[1, 0, 0], [0, 0, 0], [0, 0, 1]])
    target = Atoms("He", cell=[1.0, 2.0, 1.0])

    with pytest.raises(ValueError, match="near-zero length"):
        match_structure_axis_length(source, target, 1)
