"""Lightweight immutable snapshots of calculation structure state."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np
from ase import Atoms

from ase2sprkkr_gui.ase.embedding import GUI_CLUSTER_CENTER


_STRUCTURAL_ARRAYS = (
    "spacegroup_kinds",
    "labels",
    "tags",
    "masses",
    "initial_magmoms",
    "sprkkr_embedding",
)
_STRUCTURAL_INFO = ("occupancy", "sprkkr_embedding_host", GUI_CLUSTER_CENTER)


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
    # Embedding site properties have no small ASE array equivalent; the
    # actual host reference remains under info["sprkkr_embedding_host"].
    embedding_occupations: tuple[tuple[tuple[str, float], ...], ...] = ()
    embedding_magnetisations: tuple[tuple[float, float], ...] = ()

    @classmethod
    def capture(cls, atoms: Any) -> "StructureSnapshot":
        arrays = getattr(atoms, "arrays", {})
        structural_arrays = {
            name: _freeze(arrays[name])
            for name in _STRUCTURAL_ARRAYS
            if name in arrays
        }
        atom_info = getattr(atoms, "info", {})
        embedded = "sprkkr_embedding" in arrays
        if embedded and atom_info.get("sprkkr_embedding_host") is None:
            raise ValueError("Embedded cluster is missing its host reference")
        if embedded:
            occupations = tuple(
                tuple((str(symbol), float(concentration))
                      for symbol, concentration in site.occupation.to_dict(True).items())
                for site in atoms.sites
            )
            magnetisations = tuple(
                tuple(float(value) for value in site.magnetisation)
                for site in atoms.sites
            )
        else:
            occupations = ()
            magnetisations = ()
        structural_info = {
            # Keep exactly the same host object: copying a Potential would
            # unnecessarily duplicate its possibly very large radial arrays.
            name: (atom_info[name] if name == "sprkkr_embedding_host"
                   else _freeze(atom_info[name]))
            for name in _STRUCTURAL_INFO
            if name in atom_info and (
                name not in ("sprkkr_embedding_host", GUI_CLUSTER_CENTER) or embedded
            )
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
            embedding_occupations=occupations,
            embedding_magnetisations=magnetisations,
        )

    def to_atoms(self) -> Atoms:
        """Reconstruct the structure, including embedded-cluster identity."""
        host = self.info.get("sprkkr_embedding_host")
        if host is not None:
            from ase2sprkkr import SPRKKRAtoms

            if "sprkkr_embedding" not in self.arrays:
                raise ValueError("Embedding snapshot is missing site identities")
            rows = np.asarray(_thaw(self.arrays["sprkkr_embedding"]), dtype=int)
            if rows.shape != (len(self.positions), 6):
                raise ValueError("Invalid embedding site mapping in structure snapshot")
            if len(self.embedding_occupations) != len(rows):
                raise ValueError("Missing cluster occupation metadata in snapshot")
            sites = [
                (int(row[0]), tuple(int(i) for i in row[1:]), dict(occ))
                for row, occ in zip(rows, self.embedding_occupations)
            ]
            atoms = SPRKKRAtoms.from_embedding(host, sites)
            atoms.set_positions(np.asarray(self.positions, dtype=float))
            for site, magnetisation in zip(atoms.sites, self.embedding_magnetisations):
                site.magnetisation = np.asarray(magnetisation, dtype=float)
            if GUI_CLUSTER_CENTER in self.info:
                atoms.info[GUI_CLUSTER_CENTER] = tuple(_thaw(self.info[GUI_CLUSTER_CENTER]))
            return atoms

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
