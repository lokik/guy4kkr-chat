"""Lightweight immutable snapshots of calculation structure state."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np
from ase import Atoms


_STRUCTURAL_ARRAYS = (
    "spacegroup_kinds",
    "labels",
    "tags",
    "masses",
    "initial_magmoms",
)
_STRUCTURAL_INFO = ("occupancy",)


def _freeze(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _freeze(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class StructureSnapshot:
    """Small ASE-level structure state, deliberately excluding SPR-KKR runtime data.

    A snapshot is kept only when a calculation state has no usable POTFIL version
    from which its structure can later be reconstructed. It stores geometry and
    the small pieces of ASE metadata Ase2sprkkr needs to preserve mixed sites and
    labels; attached ``Potential`` objects, radial data, charges, convergence
    state, caches and runtime site objects are intentionally absent.
    """

    numbers: tuple[int, ...]
    positions: tuple[tuple[float, float, float], ...]
    cell: tuple[tuple[float, float, float], ...]
    pbc: tuple[bool, bool, bool]
    arrays: Mapping[str, Any]
    info: Mapping[str, Any]

    @classmethod
    def capture(cls, atoms: Any) -> "StructureSnapshot":
        arrays = getattr(atoms, "arrays", {})
        structural_arrays = {
            name: _freeze(arrays[name])
            for name in _STRUCTURAL_ARRAYS
            if name in arrays
        }
        atom_info = getattr(atoms, "info", {})
        structural_info = {
            name: _freeze(atom_info[name])
            for name in _STRUCTURAL_INFO
            if name in atom_info
        }
        return cls(
            numbers=tuple(int(number) for number in atoms.numbers),
            positions=tuple(
                tuple(float(component) for component in position)
                for position in atoms.positions
            ),
            cell=tuple(
                tuple(float(component) for component in vector)
                for vector in atoms.cell.array
            ),
            pbc=tuple(bool(value) for value in atoms.pbc),
            arrays=MappingProxyType(structural_arrays),
            info=MappingProxyType(structural_info),
        )

    def to_atoms(self) -> Atoms:
        """Reconstruct a fresh plain ASE ``Atoms`` object from the snapshot."""
        atoms = Atoms(
            numbers=self.numbers,
            positions=self.positions,
            cell=self.cell,
            pbc=self.pbc,
        )
        for name, value in self.arrays.items():
            atoms.set_array(name, np.asarray(_thaw(value)))
        atoms.info.update(_thaw(self.info))
        return atoms
