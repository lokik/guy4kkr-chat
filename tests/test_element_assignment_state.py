"""Qt-independent tests for the element-assignment working model."""
from __future__ import annotations

import numpy as np
import pytest
from ase import Atoms
from ase2sprkkr import SPRKKRAtoms

from ase2sprkkr_gui.ase.element_assignment import ElementAssignmentDraft


def _atoms(
    positions=((0.0, 0.0, 0.0), (0.5, 0.5, 0.5)),
    kinds=(0, 0),
    labels=("a.1", "a.2"),
) -> Atoms:
    atoms = Atoms(
        "Fe" * len(positions),
        scaled_positions=positions,
        cell=np.eye(3),
        pbc=True,
    )
    atoms.set_array("spacegroup_kinds", np.asarray(kinds, dtype=int))
    atoms.set_array("labels", np.asarray(labels, dtype=object))
    atoms.info["occupancy"] = {
        str(kind): {"Fe": 1.0} for kind in set(kinds)
    }
    return atoms


def test_split_equivalent_site_creates_independent_sites():
    state = ElementAssignmentDraft(_atoms())

    split = state.split_site(state.sites[0])

    assert [site.label for site in split] == ["a.1", "a.2"]
    assert [len(site.positions) for site in split] == [1, 1]
    np.testing.assert_allclose(split[0].positions, [[0.0, 0.0, 0.0]])
    np.testing.assert_allclose(split[1].positions, [[0.5, 0.5, 0.5]])


def test_split_preserves_each_positions_origin_and_output_order():
    atoms = _atoms(
        positions=((0.0, 0.0, 0.0), (0.25, 0.25, 0.25), (0.5, 0.5, 0.5)),
        kinds=(0, 0, 0),
        labels=("a.1", "a.2", "a.3"),
    )
    state = ElementAssignmentDraft(atoms)

    split = state.split_site(state.sites[0])
    result = state.apply()

    assert [site.origins for site in split] == [[0], [1], [2]]
    np.testing.assert_allclose(
        result.get_scaled_positions(), atoms.get_scaled_positions()
    )
    np.testing.assert_array_equal(result.get_array("spacegroup_kinds"), [0, 1, 2])


def test_to_atoms_preserves_public_assignment_format():
    atoms = _atoms()
    state = ElementAssignmentDraft(atoms)

    result = state.apply()

    assert result is not atoms
    np.testing.assert_array_equal(
        result.get_array("spacegroup_kinds"), (0, 0)
    )
    np.testing.assert_array_equal(
        result.get_array("labels"), ("a.1", "a.2")
    )
    assert result.info["occupancy"] == {"0": {"Fe": 1.0}}


def test_split_generates_unique_labels_when_candidates_collide():
    atoms = _atoms(
        positions=((0, 0, 0), (0.5, 0.5, 0.5), (0.25, 0.25, 0.25)),
        kinds=(0, 0, 1),
        labels=("a.1", "a.2", "a.1"),
    )
    state = ElementAssignmentDraft(atoms)
    assert [site.label for site in state.sites] == ["a", "a_1"]
    state.sites[1].label = "a.1"

    split = state.split_site(state.sites[0])

    assert [site.label for site in split] == ["a.1.1", "a.2"]


def test_position_edits_keep_origins_aligned():
    state = ElementAssignmentDraft(_atoms())
    site = state.sites[0]

    added = state.add_position(site)
    state.set_position_component(site, added, 0, 0.75)
    assert site.origins == [0, 1, None]
    assert site.positions[added, 0] == pytest.approx(0.75)

    assert state.remove_position(site, 1)
    assert site.origins == [0, None]
    single_state = ElementAssignmentDraft(
        _atoms(((0, 0, 0),), (0,), ("a",))
    )
    assert not single_state.remove_position(single_state.sites[0], 0)


def test_occupancy_changes_and_normalization_are_model_operations():
    state = ElementAssignmentDraft(_atoms())
    site = state.sites[0]
    first = site.occupancies[0]
    state.set_occupancy_value(site, first, 0.25)
    second = state.add_occupancy(site, "Ni", 0.25)

    assert state.occupancy_total(site) == pytest.approx(0.5)
    state.normalize_occupancy(site)
    assert first.value == pytest.approx(0.5)
    assert second.value == pytest.approx(0.5)
    assert state.is_site_valid(site)


@pytest.mark.parametrize(
    ("symbol", "value", "valid"),
    (
        ("Fe", 1.0, True),
        ("Fe", 0.4, True),
        ("Fe", 1.1, False),
        ("Fe", -0.1, False),
        ("", 1.0, False),
        ("NoSuch", 1.0, False),
        ("Fe", 0.0, False),
    ),
)
def test_occupancy_validation(symbol, value, valid):
    state = ElementAssignmentDraft(_atoms())
    site = state.sites[0]
    entry = site.occupancies[0]
    state.set_occupancy_symbol(site, entry, symbol)
    state.set_occupancy_value(site, entry, value)

    assert state.is_site_valid(site) is valid
    assert bool(state.validation_errors(site)) is not valid


def test_cancel_state_does_not_modify_source_atoms():
    atoms = _atoms()
    original_positions = atoms.positions.copy()
    original_occupancy = atoms.info["occupancy"].copy()
    state = ElementAssignmentDraft(atoms)

    state.split_site(state.sites[0])
    state.set_cell_component(0, 0, 2.0)

    np.testing.assert_array_equal(atoms.positions, original_positions)
    assert atoms.info["occupancy"] == original_occupancy


def test_apply_split_preserves_sprkkr_site_type_data():
    atoms = SPRKKRAtoms.promote_ase_atoms(_atoms(), symmetry=False)
    sites = atoms.sites
    sites[1].site_type = sites[0].site_type
    sites[0].site_type.reference_system.vref = 9.0
    sites[0].site_type.reference_system.rmtref = 2.0
    draft = ElementAssignmentDraft(atoms)
    draft.split_site(draft.sites[0])

    result = draft.apply()

    assert isinstance(result, SPRKKRAtoms)
    assert result.sites[0].site_type is not result.sites[1].site_type
    assert result.sites[0].site_type.reference_system.to_tuple() == (9.0, 2.0)
    assert result.sites[1].site_type.reference_system.to_tuple() == (9.0, 2.0)


def test_apply_without_split_preserves_sprkkr_site_type_data():
    atoms = SPRKKRAtoms.promote_ase_atoms(_atoms(), symmetry=False)
    sites = atoms.sites
    sites[1].site_type = sites[0].site_type
    sites[0].site_type.reference_system.vref = 8.0
    draft = ElementAssignmentDraft(atoms)

    result = draft.apply()

    assert result is not atoms
    assert result.sites[0].site_type is result.sites[1].site_type
    assert result.sites[0].site_type.reference_system.vref == 8.0
