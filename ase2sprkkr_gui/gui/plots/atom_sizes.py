"""Presentation-only atom marker sizes from ase2sprkkr's static WSR table.

Optional site-specific radial mesh RWS is only used for a potential that has
progressed beyond START. Neither Atoms nor potentials are changed.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

import numpy as np
from ase2sprkkr.physics.winger_seitz_radii import winger_seitz_radii


@dataclass(frozen=True)
class AtomAppearance:
    size_percent: int = 100
    relative_sizes: bool = True
    potential_radii: bool = True


MIN_ATOM_SIZE_PERCENT = 5
MAX_ATOM_SIZE_PERCENT = 2000

_appearance = AtomAppearance()


def marker_area_scale() -> float:
    """Shared multiplier for geometry-only markers without element identities."""
    return (_appearance.size_percent / 100.0) ** 2


def set_atom_appearance(
    size_percent: int = 100,
    relative_sizes: bool = True,
    potential_radii: bool = True,
) -> None:
    """Update shared GUI presentation preferences."""
    global _appearance
    _appearance = AtomAppearance(
        max(MIN_ATOM_SIZE_PERCENT, min(MAX_ATOM_SIZE_PERCENT, int(size_percent))),
        bool(relative_sizes),
        bool(potential_radii),
    )


def _valid_radius(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _sites(atoms):
    sites = getattr(atoms, "arrays", {}).get("sprkkr_sites_data")
    return sites if sites is not None and len(sites) == len(atoms) else None


def _occupation_radius(occupation):
    """Return concentration-weighted static WSR, or None for unknown species."""
    if isinstance(occupation, Mapping):
        occupation = occupation.items()
    if occupation is None:
        return None
    total = weighted = 0.0
    for symbol, concentration in occupation:
        radius = _valid_radius(winger_seitz_radii.get(str(symbol)))
        weight = _valid_radius(concentration)
        if radius is not None and weight is not None:
            weighted += weight * radius
            total += weight
    return weighted / total if total > 0 else None


def _static_radius(atoms, index, sites, symbols):
    occupation = None
    if sites is not None:
        try:
            occupation = (
                (atomic_type.symbol, concentration)
                for atomic_type, concentration in
                sites[index].site_type.occupation.items()
            )
            radius = _occupation_radius(occupation)
            if radius is not None:
                return radius
        except (AttributeError, TypeError, ValueError):
            pass
    kinds = getattr(atoms, "arrays", {}).get("spacegroup_kinds")
    key = kinds[index] if kinds is not None else index
    values = getattr(atoms, "info", {}).get("occupancy", {})
    if isinstance(values, Mapping):
        occupation = values.get(key, values.get(str(key)))
    return (
        _occupation_radius(occupation)
        or _valid_radius(winger_seitz_radii.get(symbols[index]))
        or 2.8
    )


def marker_area_factors_for_occupations(occupations, *, appearance=None):
    """Relative scatter *area* factors for a collection of draft site occupations.

    Each item is an iterable of (symbol, concentration) pairs. The collection
    must include all displayed sites before filtering highlights, so a change
    of selection cannot resize otherwise unchanged atoms.
    """
    appearance = _appearance if appearance is None else appearance
    radii = np.asarray([
        _occupation_radius(occupation) or 2.8 for occupation in occupations
    ], dtype=float)
    if not len(radii):
        return radii
    if not appearance.relative_sizes:
        return np.ones(len(radii), dtype=float)
    return (radii / np.mean(radii)) ** 2


def _post_start(potential):
    if potential is None:
        return False
    try:
        status = potential.SCF_INFO.SCFSTATUS()
    except (AttributeError, TypeError, ValueError, KeyError):
        return False
    status = str(status).strip().upper()
    return status in ("ITERATING", "CONVERGED") or status.startswith("ITR")


def marker_areas(atoms, base_area=48.0, *, potential=None, appearance=None):
    """Scatter areas; normalize mean radius to avoid global size jumps.

    No potential/site initialization is performed. Per-site invalid RWS values
    use the static element WSR, including for mixed-occupation sites.
    """
    appearance = _appearance if appearance is None else appearance
    n = 0 if atoms is None else len(atoms)
    if not n:
        return np.empty(0, dtype=float)
    area = float(base_area) * (appearance.size_percent / 100.0) ** 2
    if not appearance.relative_sizes:
        return np.full(n, area, dtype=float)

    sites = _sites(atoms)
    symbols = atoms.get_chemical_symbols()
    radii = np.asarray([_static_radius(atoms, i, sites, symbols) for i in range(n)])
    if potential is None:
        potential = getattr(atoms, "_potential", None)
    if appearance.potential_radii and sites is not None and _post_start(potential):
        for i, site in enumerate(sites):
            radius = _valid_radius(
                getattr(
                    getattr(getattr(site, "site_type", None), "mesh", None),
                    "rws", None,
                )
            )
            if radius is not None:
                radii[i] = radius
    return area * (radii / np.mean(radii)) ** 2
