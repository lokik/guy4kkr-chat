"""Scientific grouping and host-to-cluster index mapping in editor previews."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from ase2sprkkr_gui.gui.widgets.structures.editor_preview import (
    cluster_preview_style,
    host_site_cluster_indices,
    site_type_colors,
    species_colors,
    atom_colors,
    site_type_group_keys,
)


class _Atoms:
    def __init__(self):
        shared = SimpleNamespace()
        independent = SimpleNamespace()
        sites = np.asarray([
            SimpleNamespace(site_type=shared),
            SimpleNamespace(site_type=shared),
            SimpleNamespace(site_type=independent),
        ], dtype=object)
        self.arrays = {"sprkkr_sites_data": sites}
        self._symbols = ["Fe", "Fe", "Fe"]

    def __len__(self):
        return len(self._symbols)

    def get_chemical_symbols(self):
        return self._symbols

    def get_atomic_numbers(self):
        return np.asarray([26, 26, 26])


def test_grouping_uses_site_type_identity_and_not_element():
    atoms = _Atoms()
    keys = site_type_group_keys(atoms)
    assert keys[0] == keys[1]
    assert keys[0] != keys[2]
    colors = site_type_colors(atoms)
    assert colors[0] == colors[1]
    assert colors[0] != colors[2]
    species = species_colors(atoms)
    assert species[0] == species[1] == species[2]
    np.testing.assert_array_equal(atom_colors(atoms, "species"), species)
    np.testing.assert_array_equal(atom_colors(atoms, "site_type"), colors)
    _, sizes, outlines, widths = cluster_preview_style(atoms, (1,))
    assert widths[1] > widths[0]
    assert sizes[1] > sizes[2]
    assert outlines[1] != outlines[0]
    selected_species_colors, _, _, _ = cluster_preview_style(
        atoms, (1,), color_mode="species",
    )
    np.testing.assert_array_equal(selected_species_colors, species)


def test_host_site_selects_all_cluster_periodic_images():
    class Cluster:
        arrays = {
            "sprkkr_embedding": np.asarray([
                [0, 0, 0, 0, 0, 0],
                [0, 1, 0, 0, 0, 0],
                [1, 0, 0, 0, 0, 0],
            ], dtype=int),
        }

        def __len__(self):
            return len(self.arrays["sprkkr_embedding"])

    cluster = Cluster()
    assert host_site_cluster_indices(cluster, 0) == (0, 1)
    assert host_site_cluster_indices(cluster, 1) == (2,)
    assert host_site_cluster_indices(cluster, -1) == ()
