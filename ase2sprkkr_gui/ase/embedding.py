"""Qt-independent editing draft for SPR-KKR embedded clusters.

The finite cluster is separate from the (possibly huge) periodic host.  Only
sites explicitly included in the cluster are materialized as SPRKKRAtoms on OK.
All temporary editor changes stay in this draft.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass

import numpy as np
from ase.data import atomic_numbers
from ase.geometry import minkowski_reduce
from ase2sprkkr import Potential, SPRKKRAtoms

from ase2sprkkr_gui.ase.copy import copy_for_edit
from ase2sprkkr.sprkkr.embedding import embedding_data, host_atoms, host_dimension
from ase2sprkkr.sprkkr.embedding_edits import (
    EmbeddedSiteParameters,
    embedded_edit_discards_radial_data,
    rebuild_embedded_cluster,
)
from ase2sprkkr.sprkkr.embedding_geometry import (
    EmbeddingSymmetry,
    HostSite,
    embedding_host_indices,
    embedding_sites_within_radius,
    embedding_sites_within_shells,
)


# GUI metadata travels with one embedded Atoms object, not with its host or
# the native CLUPOT format (which has no separate centre field).
GUI_CLUSTER_CENTER = "sprkkr_embedding_center"


@dataclass(frozen=True)
class EmbeddingDraftState:
    """Detached editable state; contains no host or original radial data."""

    center: HostSite
    entries: dict[HostSite, EmbeddedSiteParameters]


def cluster_center(host, cluster: SPRKKRAtoms) -> HostSite:
    """Return an explicit GUI centre, or the included site nearest the centroid.

    The native cluster file stores sites but has no independent centre field.
    Selection is deterministic for equidistant sites and independent of file
    ordering. This function never modifies the input cluster or host.
    """
    stored = cluster.info.get(GUI_CLUSTER_CENTER)
    if (isinstance(stored, (tuple, list)) and len(stored) == 6
            and all(isinstance(i, (int, np.integer)) and not isinstance(i, bool)
                    for i in stored)):
        try:
            selected = HostSite(int(stored[0]), tuple(int(i) for i in stored[1:])).canonical(host)
            if selected.original_site in embedding_host_indices(host):
                selected.position(host)
                return selected
        except (ValueError, TypeError, IndexError):
            pass

    rows = embedding_data(cluster)
    if not len(rows):
        raise ValueError("An embedded cluster needs at least one site")
    sites = [
        HostSite(int(row[0]), tuple(int(i) for i in row[1:])).canonical(host)
        for row in rows
    ]
    positions = np.asarray(cluster.positions, dtype=float)
    centroid = positions.mean(axis=0)
    distances = np.linalg.norm(positions - centroid, axis=1)
    nearest = np.flatnonzero(np.isclose(
        distances, distances.min(), rtol=0, atol=1e-9,
    ))
    return min(sites[int(i)] for i in nearest)


def set_cluster_center(cluster: SPRKKRAtoms, site: HostSite) -> None:
    """Store centre on these cluster atoms only; never touch the host."""
    host = cluster.embedding_host
    selected = site.canonical(host)
    if selected.original_site not in embedding_host_indices(host):
        raise ValueError("The centre must belong to an embeddable host site")
    selected.position(host)
    cluster.info[GUI_CLUSTER_CENTER] = (
        selected.original_site, *(int(i) for i in selected.translations(host)),
    )


def reset_cluster_center(cluster: SPRKKRAtoms) -> None:
    """Forget a previous cluster's selection after replacing its geometry."""
    cluster.info.pop(GUI_CLUSTER_CENTER, None)
    set_cluster_center(cluster, cluster_center(cluster.embedding_host, cluster))


def parse_occupation(value: str) -> dict[str, float]:
    """Parse 'Fe' or 'Fe:0.7, Ni:0.3' without silent normalization."""
    parts = [part.strip() for part in value.replace(";", ",").split(",")]
    if not all(parts):
        raise ValueError("Occupation must contain one or more elements")
    if len(parts) == 1 and ":" not in parts[0]:
        parts[0] += ":1"
    occupation = {}
    for part in parts:
        symbol, sep, fraction = part.partition(":")
        symbol = symbol.strip()
        if symbol == "Vc":
            symbol = "X"
        if not sep or symbol not in atomic_numbers and symbol != "X":
            raise ValueError(f"Invalid occupation component {part!r}")
        if symbol in occupation:
            raise ValueError(f"Duplicate element {symbol}")
        try:
            amount = float(fraction)
        except ValueError as exc:
            raise ValueError(f"Invalid concentration {fraction!r}") from exc
        if not np.isfinite(amount) or amount <= 0 or amount > 1:
            raise ValueError("Each concentration must be between 0 and 1")
        occupation[symbol] = amount
    if not np.isclose(sum(occupation.values()), 1.0, atol=1e-6, rtol=0):
        raise ValueError("Occupation concentrations must sum to 1")
    return occupation


def occupation_label(occupation: Mapping[str, float]) -> str:
    if len(occupation) == 1 and abs(next(iter(occupation.values())) - 1.0) < 1e-8:
        return next(iter(occupation))
    return ", ".join(f"{symbol}:{amount:.6g}" for symbol, amount in occupation.items())


def embedding_cell(host):
    """Return the reference origin and vectors used to display one host cell.

    Native 2D cells consist of consecutive left, central and right regions.
    Keep the central region's full third vector, including its lateral shear.
    For an ASE slab without those regions, clip the original cell direction
    to the occupied heights rather than displaying its surrounding vacuum.
    No atom positions or embedding translation indices are changed.
    """
    atoms = host_atoms(host)
    cell = np.asarray(atoms.cell, dtype=float).copy()
    origin = np.zeros(3)
    if host_dimension(host) == 3:
        return origin, cell
    regions = getattr(atoms, "regions", {})
    if all(name in regions for name in ("left", "central", "right")):
        origin = np.asarray(regions["left"].cell[2], dtype=float).copy()
        cell[2] = regions["central"].cell[2]
    else:
        normal = np.cross(cell[0], cell[1])
        norm = np.linalg.norm(normal)
        if norm <= 1e-12:
            raise ValueError("The two periodic lattice vectors must be independent")
        normal /= norm
        heights = np.asarray(atoms.positions)[list(embedding_host_indices(host))] @ normal
        height = np.dot(cell[2], normal)
        direction = cell[2] / height if abs(height) > 1e-12 else normal
        origin = heights.min() * direction
        cell[2] = np.ptp(heights) * direction
    return origin, cell


def cell_ring_offsets(vectors, rings):
    """Cells within ``rings`` Wigner-Seitz adjacency steps of (0, 0).

    Two cells are neighbours when their translation points' Voronoi regions
    share an edge (a shared vertex alone does not count). Distances use the
    two actual 3D translation vectors, independently of the display projection.
    Return indices in the original basis; never change the displayed cells.
    """
    vectors = np.asarray(vectors, dtype=float)
    if vectors.shape != (2, 3) or not np.isfinite(vectors).all():
        raise ValueError("Cell-map vectors must be two finite 3D vectors")
    # Normalize together so the rank check and ASE's reduction tolerances do
    # not depend on the unit of length. Collinear vectors have no 2D cells.
    scale = np.abs(vectors).max()
    if scale == 0 or np.linalg.matrix_rank(vectors / scale) < 2:
        raise ValueError("Cell-map vectors must be independent")
    reduced, transform = minkowski_reduce(
        np.vstack((vectors / scale, np.zeros(3))), pbc=(True, True, False),
    )
    first, second = reduced[:2]
    a, b = transform[:2, :2]
    # In a Gauss-reduced 2D basis the Voronoi neighbours are ±a, ±b
    # and ±(b-sign(a·b)a). For orthogonal vectors the latter cells meet
    # only at a vertex, so exclude them. Snap numerical orthogonality at 1e-10.
    directions = [a, b]
    dot = np.dot(first, second)
    if abs(dot) > 1e-10 * np.linalg.norm(first) * np.linalg.norm(second):
        directions.append(b - (a if dot > 0 else -a))
    steps = [tuple(sign * direction) for direction in directions for sign in (-1, 1)]
    visited = frontier = {(0, 0)}
    for _ in range(rings):
        frontier = {(x + dx, y + dy) for x, y in frontier for dx, dy in steps} - visited
        visited |= frontier
    return tuple(sorted(visited))


def fill_cell_hull(cells, max_cells=10000):
    """Fill gaps in a finite 2D host viewport with complete periodic cells.

    Use the convex hull of cell footprints instead of separate patches around
    symmetry previews. Widely separated groups remain bounded by max_cells.
    """
    cells = set(cells)
    indices = np.asarray(sorted(cells), dtype=int)
    lower, upper = indices.min(axis=0), indices.max(axis=0)
    if np.prod(upper - lower + 1) > max_cells:
        return cells
    vertices = sorted({(x + dx, y + dy) for x, y in cells
                       for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1))})

    def boundary(points):
        result = []
        for point in points:
            while len(result) >= 2:
                a, b = result[-2:]
                cross = ((b[0] - a[0]) * (point[1] - a[1])
                         - (b[1] - a[1]) * (point[0] - a[0]))
                if cross > 0:
                    break
                result.pop()
            result.append(point)
        return result

    hull = np.asarray(boundary(vertices)[:-1] + boundary(reversed(vertices))[:-1])
    candidates = np.array([(x, y) for x in range(lower[0], upper[0] + 1)
                           for y in range(lower[1], upper[1] + 1)])
    relative = candidates[:, None, :] + .5 - hull
    edges = np.roll(hull, -1, axis=0) - hull
    cross = edges[:, 0] * relative[:, :, 1] - edges[:, 1] * relative[:, :, 0]
    return {tuple(index) for index in candidates[np.all(cross >= -1e-9, axis=1)]}


class EmbeddingDraft:
    """Editor-only state: host, centre and explicit included cluster sites."""

    def __init__(self, host, cluster: SPRKKRAtoms | None = None):
        # The source host anchors stored displacements and final materialization.
        # A detached geometry view may reflect uncommitted host edits.
        self.host = host
        self._geometry_host = host
        self._to_geometry = np.eye(3)
        self._to_source = np.eye(3)
        self.dimension = host_dimension(host)
        allowed = embedding_host_indices(host)
        if not allowed:
            raise ValueError("The host has no sites available for embedding")
        self.allowed = frozenset(allowed)
        self.entries: dict[HostSite, EmbeddedSiteParameters] = {}
        self.original_cluster = cluster
        self._original_entries: dict[HostSite, EmbeddedSiteParameters] = {}
        self.center = HostSite(allowed[0], (0,) * self.dimension)
        if cluster is not None:
            if cluster.embedding_host is not host:
                raise ValueError("The embedded structure must reference the selected host")
            for row, site in zip(embedding_data(cluster), cluster.sites):
                host_site = HostSite(int(row[0]), tuple(int(v) for v in row[1:])).canonical(host)
                if host_site.original_site not in self.allowed or host_site in self.entries:
                    raise ValueError("Invalid or duplicate embedded host site")
                self.entries[host_site] = EmbeddedSiteParameters(
                    occupation=dict(site.occupation.to_dict(True)),
                    displacement=np.asarray(site.embedding.displacement, dtype=float).copy(),
                    magnetisation=np.asarray(site.magnetisation, dtype=float).copy(),
                )
            if self.entries:
                self.center = cluster_center(host, cluster)
            self._original_entries = deepcopy(self.entries)
        self._original_center = self.center

    def snapshot(self) -> EmbeddingDraftState:
        """Capture independent editable values, keeping the host shared."""
        return EmbeddingDraftState(self.center, deepcopy(self.entries))

    def restore(self, state: EmbeddingDraftState) -> None:
        """Restore a snapshot without allowing later edits to mutate it."""
        self.center = state.center
        self.entries = deepcopy(state.entries)

    def _physical_data_unchanged(self) -> bool:
        return self.original_cluster is not None and self.entries == self._original_entries

    def is_unchanged(self) -> bool:
        """Whether the physical sites and selected GUI centre are unchanged."""
        return self._physical_data_unchanged() and self.center == self._original_center

    @property
    def geometry_host(self):
        """Live geometry and chemistry, distinct from the source cluster host."""
        return self._geometry_host

    def set_geometry_host(self, host) -> None:
        """Refresh the host view and cache its affine displacement mapping."""
        original = host_atoms(self.host)
        updated = host_atoms(host)
        if host_dimension(host) != self.dimension:
            raise ValueError("The embedded host dimensionality cannot change")
        if len(original) != len(updated) or not np.array_equal(original.pbc, updated.pbc):
            raise ValueError("The embedded host site mapping or periodicity changed")
        if frozenset(embedding_host_indices(host)) != self.allowed:
            raise ValueError("The set of editable embedded host sites changed")
        to_geometry = to_source = np.eye(3)
        if not np.array_equal(original.cell, updated.cell):
            try:
                to_geometry = np.linalg.solve(
                    np.asarray(original.cell), np.asarray(updated.cell)
                )
                to_source = np.linalg.solve(
                    np.asarray(updated.cell), np.asarray(original.cell)
                )
            except np.linalg.LinAlgError as exc:
                raise ValueError("Embedded host preview requires a nonsingular cell") from exc
        # Publish a complete validated mapping at once; no partly updated
        # geometry should ever be observed by the live widget.
        self._to_geometry = to_geometry
        self._to_source = to_source
        self._geometry_host = host

    def display_displacement(self, value):
        """Convert a source-reference vector into the current host coordinates."""
        return np.asarray(value, dtype=float) @ self._to_geometry

    def source_displacement(self, value):
        """Convert a displayed vector back before recording an Undoable edit."""
        return np.asarray(value, dtype=float) @ self._to_source

    def would_discard_radial_data(self) -> bool:
        """Ask whether a physical edit would lose native restart data."""
        return not self._physical_data_unchanged() and embedded_edit_discards_radial_data(
            self.original_cluster, self.entries
        )

    def canonical(self, site: HostSite) -> HostSite:
        result = site.canonical(self.geometry_host)
        if result.original_site not in self.allowed:
            raise ValueError("This site is not in the embeddable part of the host")
        result.position(self.geometry_host)
        return result

    def cell_sites(self, cell_index) -> tuple[HostSite, ...]:
        """Site identities in a displayed cell, including existing native N5VEC."""
        index = tuple(cell_index)
        if len(index) != self.dimension:
            raise ValueError(f"Expected {self.dimension} displayed cell indices")
        regular = {HostSite(i, index).canonical(self.geometry_host) for i in self.allowed}
        # The UI has 2D/3D navigation, but may reopen native files with five
        # independent translation coefficients. Keep those sites accessible.
        extras = {
            site for site in self.entries
            if site.cell_index[:self.dimension] == index
        }
        return tuple(sorted(regular | extras))

    def set_center(self, site: HostSite) -> None:
        self.center = self.canonical(site)

    def equivalents(self, sites) -> tuple[HostSite, ...]:
        originals = [self.canonical(site) for site in sites]
        if not originals:
            return ()
        symmetry = EmbeddingSymmetry(self.geometry_host, self.center)
        # Only sites for which CLUPOT can represent an embedding are eligible.
        return tuple(sorted({s for original in originals
                             for s in symmetry.equivalent_sites(original)
                             if s.original_site in self.allowed}))

    def targets(self, sites, symmetric: bool = False) -> tuple[HostSite, ...]:
        if symmetric:
            return self.equivalents(sites)
        return tuple(sorted({self.canonical(site) for site in sites}))

    def _entry(self, site: HostSite) -> EmbeddedSiteParameters:
        site = self.canonical(site)
        if site not in self.entries:
            self.entries[site] = EmbeddedSiteParameters(occupation=site.occupation(self.geometry_host))
        return self.entries[site]

    def include(self, sites) -> int:
        before = len(self.entries)
        for site in sites:
            self._entry(site)
        return len(self.entries) - before

    def exclude(self, sites) -> int:
        before = len(self.entries)
        for site in sites:
            self.entries.pop(self.canonical(site), None)
        return before - len(self.entries)

    def set_occupation(self, sites, occupation: Mapping[str, float]) -> None:
        validated = parse_occupation(occupation_label(occupation))
        for site in sites:
            self._entry(site).occupation = dict(validated)

    def reset_occupation(self, sites) -> None:
        for site in sites:
            site = self.canonical(site)
            self._entry(site).occupation = site.occupation(self.geometry_host)

    def set_displacement(self, sites, value, *, symmetric=False) -> None:
        """Set a common Cartesian vector, rotating it onto symmetry targets.

        Overlapping target orbits must agree. Validate the complete operation
        before changing any entry, including when several sites are selected.
        """
        vector = np.asarray(value, dtype=float)
        if vector.shape != (3,) or not np.all(np.isfinite(vector)):
            raise ValueError("Displacement must be a finite Cartesian three-vector")
        symmetry = EmbeddingSymmetry(self.geometry_host, self.center) if symmetric else None
        changes = {}
        for original in sites:
            site = self.canonical(original)
            if symmetry is None:
                changes[site] = vector
                continue
            for operation in symmetry.operations:
                mapped = symmetry.map_site(site, operation)
                if mapped.original_site not in self.allowed:
                    continue
                displacement = symmetry.transform_displacement(vector, operation)
                if mapped in changes and not np.allclose(
                    changes[mapped], displacement, atol=1e-7, rtol=0
                ):
                    raise ValueError("Displacement conflicts with the selected site symmetry")
                changes[mapped] = displacement
        for mapped, displacement in changes.items():
            # Symmetry is evaluated in the displayed geometry, while history
            # stores the original-coordinate displacement.
            self._entry(mapped).displacement = self.source_displacement(displacement)

    def sites_within_radius(self, radius: float) -> tuple[HostSite, ...]:
        """Read-only expansion selection, shared by preview and inclusion."""
        return embedding_sites_within_radius(self.geometry_host, self.center, radius)

    def sites_within_shells(self, shells: int) -> tuple[HostSite, ...]:
        """Read-only coordination-shell selection, including the centre."""
        return embedding_sites_within_shells(self.geometry_host, self.center, shells)

    def add_radius(self, radius: float) -> int:
        return self.include(self.sites_within_radius(radius))

    def add_shells(self, shells: int) -> int:
        return self.include(self.sites_within_shells(shells))

    def to_atoms(self, *, allow_radial_reset=False, shallow=False) -> SPRKKRAtoms:
        """Materialize the edited cluster without silently losing radial results.

        Existing radial data can only be reset after explicit caller approval.
        An unchanged cluster is returned as is, including its native potential.
        """
        if self.is_unchanged():
            return self.original_cluster
        if self._physical_data_unchanged():
            # Only the GUI centre changed: retain all native radial/SCF data
            # and leave the source atoms untouched until outer Apply.
            atoms = self.original_cluster.copy(shallow=shallow)
        else:
            atoms = rebuild_embedded_cluster(
                self.host, self.entries, original=self.original_cluster,
                allow_radial_reset=allow_radial_reset, shallow=shallow,
            )
        set_cluster_center(atoms, self.center)
        return atoms


def embedding_source(atoms):
    """Return (host, existing cluster) without accidentally creating a Potential."""
    if atoms is None:
        raise ValueError("Load a host structure first")
    if isinstance(atoms, SPRKKRAtoms) and atoms.embedding_host is not None:
        return atoms.embedding_host, atoms
    has_potential = getattr(atoms, "has_potential", None)
    if callable(has_potential) and has_potential():
        return atoms.potential, None
    return atoms, None


def prepare_embedding_source(atoms):
    """Provide a native host before editing, preserving the source on cancel.

    Existing potentials retain their identity and radial data. A geometry-only
    host is converted on a detached copy; the resulting START potential belongs
    to the new cluster, rather than being deferred until calculation setup.
    """
    host, cluster = embedding_source(atoms)
    if isinstance(host, Potential):
        return atoms
    has_potential = getattr(host, "has_potential", None)
    if callable(has_potential) and has_potential():
        potential = host.potential
    else:
        detached = copy_for_edit(host)
        potential = Potential.from_atoms(detached)
    if cluster is None:
        return potential
    if cluster.embedding_host is potential:
        return cluster
    # Replacing a geometry-only host is an explicit structure edit.
    prepared = copy_for_edit(cluster)
    prepared.embedding_host = potential
    return prepared
