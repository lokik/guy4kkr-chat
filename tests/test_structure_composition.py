"""Tests for site-aware human-readable structure formulas."""
from __future__ import annotations

import numpy as np
from ase import Atoms
from ase2sprkkr.sprkkr.atomic_types import AtomicType

from ase2sprkkr_gui.physics.composition import site_composition, structure_formula


def _with_occupancy(symbols, kinds, occupancy):
    atoms = Atoms(symbols)
    atoms.set_array("spacegroup_kinds", np.asarray(kinds, dtype=int))
    atoms.info["occupancy"] = occupancy
    return atoms


def test_plain_atoms_use_standard_ase_formula():
    atoms = Atoms("HHO")

    assert structure_formula(atoms) == atoms.get_chemical_formula()


def test_integer_stoichiometry_is_not_normalized_by_smallest_count():
    atoms = _with_occupancy(
        "Fe2O3",
        [0, 0, 1, 1, 1],
        {"0": {"Fe": 1.0}, "1": {"O": 1.0}},
    )

    assert structure_formula(atoms) == "Fe2O3"
    assert structure_formula(atoms) != "FeO1.50"


def test_single_mixed_site_preserves_shared_site_identity():
    atoms = _with_occupancy(
        "Fe",
        [0],
        {"0": {"Fe": 0.5, "Co": 0.5}},
    )

    assert structure_formula(atoms) == "(Fe|Co)"


def test_structure_formula_combines_pure_mixed_and_repeated_sites():
    atoms = _with_occupancy(
        "TeFeOO",
        [0, 1, 2, 2],
        {
            "0": {"Te": 1.0},
            "1": {"Fe": 0.5, "Co": 0.5},
            "2": {"O": 1.0},
        },
    )

    assert "occupancy" not in atoms.arrays
    assert structure_formula(atoms) == "Te(Fe|Co)O2"


def test_equivalent_mixed_sites_use_a_multiplicity_suffix():
    atoms = _with_occupancy(
        "FeFe",
        [4, 4],
        {"4": {"Fe": 0.5, "Co": 0.5}},
    )

    assert structure_formula(atoms) == "(Fe|Co)2"


def test_uneven_partial_occupancy_keeps_concentrations():
    atoms = _with_occupancy(
        "Fe",
        [0],
        {"0": {"Fe": 0.7, "Co": 0.3}},
    )

    assert structure_formula(atoms) == "(Fe:0.7|Co:0.3)"


def test_underfilled_equal_occupancy_keeps_concentrations():
    atoms = _with_occupancy(
        "Fe",
        [0],
        {"0": {"Fe": 0.4, "Co": 0.4}},
    )

    assert structure_formula(atoms) == "(Fe:0.4|Co:0.4)"


def test_missing_occupancy_metadata_uses_standard_formula():
    atoms = Atoms("Fe2O3")
    atoms.set_array(
        "spacegroup_kinds",
        np.asarray([0, 0, 1, 1, 1], dtype=int),
    )

    assert structure_formula(atoms) == atoms.get_chemical_formula()


def test_incomplete_occupancy_metadata_uses_standard_formula():
    atoms = _with_occupancy(
        "Fe2O3",
        [0, 0, 1, 1, 1],
        {"0": {"Fe": 1.0}},
    )

    assert structure_formula(atoms) == atoms.get_chemical_formula()


def test_formula_order_follows_sites_and_species_not_mapping_keys():
    atoms = _with_occupancy(
        "TeFeFeO",
        [5, 8, 8, 1],
        {
            "1": {"O": 1.0},
            "8": {"Co": 0.5, "Fe": 0.5},
            "5": {"Te": 1.0},
        },
    )

    assert structure_formula(atoms) == "Te(Co|Fe)2O"
    assert structure_formula(atoms) == "Te(Co|Fe)2O"


def test_atomic_type_keys_are_displayed_as_chemical_symbols():
    atoms = _with_occupancy(
        "Fe",
        [0],
        {"0": {AtomicType("Fe"): 0.5, "Co": 0.5}},
    )

    assert structure_formula(atoms) == "(Fe|Co)"
    assert site_composition(atoms, 0) == "Fe:0.50, Co:0.50"
