"""Human-readable, site-aware chemical composition helpers."""
from __future__ import annotations

from collections.abc import Mapping
from math import isclose, isfinite
import re
from typing import Any


__all__ = ["site_composition", "structure_formula"]

_OCCUPANCY_TOLERANCE = 1e-6
_TYPE_SUFFIX = re.compile(r"_\d+$")


def structure_formula(atoms: Any) -> str:
    """Return a deterministic formula while preserving mixed-site identity.

    Partial occupancy is read from ``atoms.info["occupancy"]`` and associated
    with atoms through ``atoms.arrays["spacegroup_kinds"]``.  Missing or
    inconsistent occupancy metadata falls back to ASE's standard formula.
    """
    fallback = _standard_formula(atoms)
    try:
        occupancies = atoms.info.get("occupancy")
        kinds = atoms.arrays.get("spacegroup_kinds")
        if (
            not isinstance(occupancies, Mapping)
            or not occupancies
            or kinds is None
            or len(kinds) != len(atoms)
        ):
            return fallback

        multiplicities: dict[str, int] = {}
        for kind in kinds:
            key = str(kind)
            multiplicities[key] = multiplicities.get(key, 0) + 1

        components: list[list[Any]] = []
        pure_component_indices: dict[str, int] = {}
        for kind, multiplicity in multiplicities.items():
            occupancy = occupancies.get(kind)
            formatted = _format_site_formula(occupancy)
            if formatted is None:
                return fallback
            text, pure_symbol = formatted
            if pure_symbol is not None:
                existing = pure_component_indices.get(pure_symbol)
                if existing is not None:
                    components[existing][1] += multiplicity
                    continue
                pure_component_indices[pure_symbol] = len(components)
            components.append([text, multiplicity])

        return "".join(
            text if multiplicity == 1 else f"{text}{multiplicity}"
            for text, multiplicity in components
        )
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return fallback


def site_composition(atoms: Any, atom_index: int) -> str:
    """Return the display composition for one atom's crystallographic site."""
    fallback = _atom_symbol(atoms, atom_index)
    try:
        occupancies = atoms.info.get("occupancy")
        kinds = atoms.arrays.get("spacegroup_kinds")
        if (
            not isinstance(occupancies, Mapping)
            or kinds is None
            or len(kinds) != len(atoms)
        ):
            return fallback
        entries = _occupancy_entries(occupancies.get(str(kinds[atom_index])))
        if entries is None:
            return fallback
        return ", ".join(f"{symbol}:{value:.2f}" for symbol, value in entries)
    except (
        AttributeError,
        IndexError,
        KeyError,
        OverflowError,
        TypeError,
        ValueError,
    ):
        return fallback


def _format_site_formula(
    occupancy: Any,
) -> tuple[str, str | None] | None:
    entries = _occupancy_entries(occupancy)
    if entries is None:
        return None

    total = sum(value for _symbol, value in entries)
    if total > 1.0 + _OCCUPANCY_TOLERANCE:
        return None
    full = isclose(total, 1.0, abs_tol=_OCCUPANCY_TOLERANCE)
    if len(entries) == 1 and full:
        symbol = entries[0][0]
        return symbol, symbol

    equal = all(
        isclose(value, entries[0][1], abs_tol=_OCCUPANCY_TOLERANCE)
        for _symbol, value in entries[1:]
    )
    if len(entries) > 1 and full and equal:
        content = "|".join(symbol for symbol, _value in entries)
    else:
        content = "|".join(
            f"{symbol}:{_format_occupancy(value)}"
            for symbol, value in entries
        )
    return f"({content})", None


def _occupancy_entries(occupancy: Any) -> list[tuple[str, float]] | None:
    if not isinstance(occupancy, Mapping) or not occupancy:
        return None

    values: dict[str, float] = {}
    for species, raw_value in occupancy.items():
        symbol = _chemical_symbol(species)
        try:
            value = float(raw_value)
        except (OverflowError, TypeError, ValueError):
            return None
        if symbol is None or not isfinite(value) or value < 0.0:
            return None
        if value <= _OCCUPANCY_TOLERANCE:
            continue
        values[symbol] = values.get(symbol, 0.0) + value
    return list(values.items()) or None


def _chemical_symbol(species: Any) -> str | None:
    symbol = getattr(species, "symbol", species)
    if not isinstance(symbol, str) or not symbol:
        return None
    return _TYPE_SUFFIX.sub("", symbol)


def _format_occupancy(value: float) -> str:
    return f"{value:.6g}"


def _standard_formula(atoms: Any) -> str:
    try:
        return str(atoms.get_chemical_formula())
    except (AttributeError, TypeError, ValueError):
        return ""


def _atom_symbol(atoms: Any, atom_index: int) -> str:
    try:
        return str(atoms[atom_index].symbol)
    except (AttributeError, IndexError, TypeError):
        return ""
