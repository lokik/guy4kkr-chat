"""Marker area and eligibility regression tests."""
from types import SimpleNamespace

import numpy as np
from ase import Atoms

from ase2sprkkr_gui.gui.plots.atom_sizes import (
    AtomAppearance, marker_areas, marker_area_factors_for_occupations,
    marker_area_scale, set_atom_appearance,
)


def _with_meshes(atoms, radii, status):
    sites = [
        SimpleNamespace(site_type=SimpleNamespace(
            mesh=SimpleNamespace(rws=radius), occupation={},
        ))
        for radius in radii
    ]
    atoms.set_array("sprkkr_sites_data", np.asarray(sites, dtype=object))
    atoms._potential = SimpleNamespace(
        SCF_INFO=SimpleNamespace(SCFSTATUS=lambda: status)
    )
    return atoms


def test_static_wsr_and_quadratic_scale():
    atoms = Atoms("CAu")
    sizes = marker_areas(atoms, appearance=AtomAppearance())
    assert np.isclose(sizes[1] / sizes[0], (2.98 / 1.66) ** 2)
    assert np.allclose(
        marker_areas(atoms, appearance=AtomAppearance(size_percent=200)),
        sizes * 4,
    )
    assert np.allclose(
        marker_areas(atoms, appearance=AtomAppearance(relative_sizes=False)),
        [48, 48],
    )


def test_potential_requires_post_start_state_and_enabled_checkbox():
    atoms = _with_meshes(Atoms("CAu"), [1.0, 4.0], "START")
    static = marker_areas(atoms)
    assert np.isclose(static[1] / static[0], (2.98 / 1.66) ** 2)
    atoms._potential.SCF_INFO.SCFSTATUS = lambda: "ITERATING"
    from_potential = marker_areas(atoms)
    assert np.isclose(from_potential[1] / from_potential[0], 16)
    assert np.allclose(
        marker_areas(atoms, appearance=AtomAppearance(potential_radii=False)),
        static,
    )
    atoms._potential.SCF_INFO.SCFSTATUS = lambda: "CONVERGED"
    assert np.allclose(marker_areas(atoms), from_potential)


def test_invalid_mesh_radius_falls_back_per_site():
    atoms = _with_meshes(Atoms("CAu"), [0.0, float("nan")], "CONVERGED")
    sizes = marker_areas(atoms)
    assert np.isclose(sizes[1] / sizes[0], (2.98 / 1.66) ** 2)


def test_incomplete_site_metadata_falls_back_to_static():
    atoms = _with_meshes(Atoms("CAu"), [1.0, 4.0], "CONVERGED")
    atoms.arrays["sprkkr_sites_data"][1] = None
    sizes = marker_areas(atoms)
    assert len(sizes) == 2
    assert np.all(np.isfinite(sizes))


def test_shared_preference_does_not_modify_structure():
    atoms = Atoms("CAu")
    try:
        set_atom_appearance(75, False, True)
        assert np.allclose(marker_areas(atoms, 40), [22.5, 22.5])
    finally:
        set_atom_appearance()


def test_geometry_only_plot_respects_global_size_and_no_double_scaling():
    from ase2sprkkr_gui.gui.plots.lattice import plot_sites_in_lattice

    class Axes:
        def __init__(self):
            self.sizes = []

        def scatter(self, *_points, **kwargs):
            self.sizes.append(np.asarray(kwargs["s"], dtype=float))

    axes = Axes()
    points = np.zeros((2, 3))
    try:
        set_atom_appearance(150, True)
        assert np.isclose(marker_area_scale(), 2.25)
        plot_sites_in_lattice(axes, False, points, role="inactive")
        assert np.allclose(axes.sizes[-1], 42 * 2.25)
        already_scaled = np.array([25.0, 49.0])
        plot_sites_in_lattice(
            axes, False, points, marker_sizes_scaled=True, s=already_scaled
        )
        assert np.allclose(axes.sizes[-1], already_scaled)
    finally:
        set_atom_appearance()


def test_element_assignment_relative_radii_keep_a_global_reference():
    occupations = [[("C", 1.0)], [("Au", 1.0)], [("C", .5), ("Au", .5)]]
    sizes = marker_area_factors_for_occupations(occupations)
    assert np.isclose(sizes[1] / sizes[0], (2.98 / 1.66) ** 2)
    assert sizes[0] < sizes[2] < sizes[1]
    assert np.allclose(
        marker_area_factors_for_occupations(
            occupations, appearance=AtomAppearance(relative_sizes=False)
        ),
        np.ones(3),
    )


def test_expanded_atom_size_range_is_applied_quadratically():
    atoms = Atoms("Fe")
    for percent in (5, 10, 100, 1000, 2000):
        value = marker_areas(
            atoms, 48, appearance=AtomAppearance(
                size_percent=percent, relative_sizes=False
            )
        )
        assert np.allclose(value, [48 * (percent / 100) ** 2])
    try:
        set_atom_appearance(1)
        assert np.isclose(marker_area_scale(), 0.0025)
        set_atom_appearance(5)
        assert np.isclose(marker_area_scale(), 0.0025)
        set_atom_appearance(2000)
        assert np.isclose(marker_area_scale(), 400.0)
        set_atom_appearance(3000)
        assert np.isclose(marker_area_scale(), 400.0)
    finally:
        set_atom_appearance()
