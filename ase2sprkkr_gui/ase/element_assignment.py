"""Qt-independent working model for assigning elements to structure sites."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

import numpy as np
from ase import Atoms
from ase.data import chemical_symbols
from ase2sprkkr import SPRKKRAtoms
from ase2sprkkr.sprkkr.atomic_types import AtomicType
from ase2sprkkr.sprkkr.sites import Site, SiteType

from ase2sprkkr_gui.ase.utils import labels_for_partitions, partition_by_kinds


_VALID_SYMBOLS = {
    symbol for symbol in chemical_symbols if isinstance(symbol, str)
} | {"Vc"}
_OCCUPANCY_TOLERANCE = 1e-6


@dataclass
class OccupancyEntry:
    """One editable component of a site's chemical occupation."""

    symbol: str = ""
    value: float = 1.0


@dataclass
class AssignmentSite:
    """One independently editable group of equivalent fractional positions."""

    label: str
    positions: np.ndarray
    origins: list[int | None]
    occupancies: list[OccupancyEntry]

    @property
    def can_split(self) -> bool:
        return len(self.positions) > 1


class ElementAssignmentDraft:
    """Transactional edit buffer for the element-assignment dialog.

    This deliberately is not another general material or structure model.
    ``Atoms``/``SPRKKRAtoms`` remain the authoritative accepted structures,
    while this sidecar can represent dialog-only provenance, labels, grouping,
    and temporarily incomplete occupancy without polluting or invalidating the
    source object.  :meth:`apply` materializes a valid structure only on OK.

    ``origins`` records which input atom, if any, supplied every position.  It
    replaces the former ambiguous combination of payload ``index`` and
    ``origin`` fields and remains aligned with ``positions`` after edits.
    """

    def __init__(self, atoms: Atoms):
        self._source_atoms = atoms
        self._cell = np.asarray(atoms.cell, dtype=float).copy()
        self.sites = self._sites_from_atoms(atoms)
        self._original_partition = tuple(
            tuple(site.origins) for site in self.sites
        )

    @property
    def cell(self) -> np.ndarray:
        """Return a copy of the currently edited lattice vectors."""
        return self._cell.copy()

    def set_cell_component(self, row: int, column: int, value: float) -> None:
        self._cell[row, column] = float(value)

    def split_site(self, site: AssignmentSite) -> tuple[AssignmentSite, ...]:
        """Replace a multi-position site by uniquely labelled single sites."""
        site_index = self._site_index(site)
        if not site.can_split:
            return (site,)

        used_labels = {candidate.label for candidate in self.sites}
        replacements: list[AssignmentSite] = []
        for position_index, position in enumerate(site.positions):
            template = f"{site.label}.{position_index + 1}"
            label = self._unique_label(template, used_labels)
            used_labels.add(label)
            replacements.append(
                AssignmentSite(
                    label=label,
                    positions=np.asarray(position, dtype=float).reshape(1, 3),
                    origins=[site.origins[position_index]],
                    occupancies=self._copy_occupancies(site.occupancies),
                )
            )
        self.sites[site_index:site_index + 1] = replacements
        return tuple(replacements)

    def add_position(self, site: AssignmentSite) -> int:
        """Append a position, duplicating the last coordinates when present."""
        self._site_index(site)
        if len(site.positions):
            position = site.positions[-1].copy()
            site.positions = np.vstack((site.positions, position))
        else:
            site.positions = np.zeros((1, 3), dtype=float)
        site.origins.append(None)
        return len(site.positions) - 1

    def remove_position(self, site: AssignmentSite, index: int) -> bool:
        """Remove a position while preserving the invariant of one per site."""
        self._site_index(site)
        if len(site.positions) <= 1:
            return False
        index = max(0, min(int(index), len(site.positions) - 1))
        site.positions = np.delete(site.positions, index, axis=0)
        del site.origins[index]
        return True

    def set_position_component(
        self,
        site: AssignmentSite,
        position: int,
        component: int,
        value: float,
    ) -> None:
        self._site_index(site)
        site.positions[position, component] = float(value)

    def add_occupancy(
        self,
        site: AssignmentSite,
        symbol: str = "",
        value: float = 1.0,
    ) -> OccupancyEntry:
        self._site_index(site)
        entry = OccupancyEntry(symbol, float(value))
        site.occupancies.append(entry)
        return entry

    def remove_occupancy(
        self, site: AssignmentSite, entry: OccupancyEntry
    ) -> bool:
        self._site_index(site)
        if len(site.occupancies) <= 1:
            return False
        site.occupancies.remove(entry)
        return True

    def set_occupancy_symbol(
        self, site: AssignmentSite, entry: OccupancyEntry, symbol: str
    ) -> None:
        self._occupancy_index(site, entry)
        entry.symbol = symbol.strip()

    def set_occupancy_value(
        self, site: AssignmentSite, entry: OccupancyEntry, value: float
    ) -> None:
        self._occupancy_index(site, entry)
        entry.value = float(value)

    def normalize_occupancy(self, site: AssignmentSite) -> None:
        self._site_index(site)
        total = self.occupancy_total(site)
        if total == 0.0:
            return
        for entry in site.occupancies:
            entry.value /= total

    @staticmethod
    def occupancy_total(site: AssignmentSite) -> float:
        return sum(entry.value for entry in site.occupancies)

    @classmethod
    def occupancy_is_overfull(cls, site: AssignmentSite) -> bool:
        return cls.occupancy_total(site) > 1.0 + _OCCUPANCY_TOLERANCE

    @staticmethod
    def symbol_is_valid(symbol: str) -> bool:
        return symbol in _VALID_SYMBOLS

    def validation_errors(self, site: AssignmentSite) -> tuple[str, ...]:
        """Return all domain validation errors for one site."""
        self._site_index(site)
        errors: list[str] = []
        if site.positions.ndim != 2 or site.positions.shape[1:] != (3,):
            errors.append(f"Invalid positions for site {site.label}")
        elif not len(site.positions):
            errors.append(f"Site {site.label} requires a position")
        if len(site.origins) != len(site.positions):
            errors.append(f"Position origins are inconsistent for site {site.label}")
        nonempty = [entry for entry in site.occupancies if entry.symbol]
        invalid = [
            entry.symbol
            for entry in nonempty
            if not self.symbol_is_valid(entry.symbol)
        ]
        if invalid:
            errors.append(
                f"Invalid element for site {site.label}: {', '.join(invalid)}"
            )
        if not nonempty:
            errors.append(f"Site {site.label} requires an element")
        if any(
            entry.value < 0.0 or entry.value > 1.0
            for entry in site.occupancies
        ):
            errors.append(
                f"Occupation component is outside 0..1 for site {site.label}"
            )
        total = self.occupancy_total(site)
        if total <= 0.0:
            errors.append(f"Occupation must be positive for site {site.label}")
        elif self.occupancy_is_overfull(site):
            errors.append(f"Occupation too large for site {site.label}")
        return tuple(errors)

    def is_site_valid(self, site: AssignmentSite) -> bool:
        return not self.validation_errors(site)

    def is_valid(self) -> bool:
        return bool(self.sites) and all(
            self.is_site_valid(site) for site in self.sites
        )

    def apply(self, atoms: Atoms | None = None) -> Atoms:
        """Validate and materialize the draft into a detached structure."""
        if not self.is_valid():
            raise ValueError("Element assignment is not valid")

        source = self._source_atoms
        if atoms is None or atoms is source:
            atoms = source.copy()
        changed = self._partition_changed()

        if changed:
            materialization_source = atoms
            rebuilt: Atoms | None = None
            for site in self.sites:
                if all(origin is not None for origin in site.origins):
                    indices = [int(origin) for origin in site.origins]
                    part = materialization_source[indices]
                else:
                    part = self._rebuilt_site(materialization_source, site)
                rebuilt = part if rebuilt is None else rebuilt + part
            atoms = rebuilt if rebuilt is not None else Atoms(cell=self._cell)

        positions: list[np.ndarray] = []
        kinds: list[int] = []
        symbols: list[str] = []
        labels: list[str] = []
        occupancy: dict[str, dict[Any, float]] = {}
        for kind, site in enumerate(self.sites):
            count = len(site.positions)
            positions.append(site.positions @ self._cell)
            kinds.extend([kind] * count)
            site_occupancy = self._occupancy_mapping(site.occupancies)
            occupancy[str(kind)] = site_occupancy
            symbol = next(iter(site_occupancy), "X")
            symbols.extend([getattr(symbol, "symbol", symbol)] * count)
            labels.extend(
                f"{site.label}.{position + 1}"
                for position in range(count)
            )

        atoms.cell = self._cell
        atoms.symbols = symbols
        atoms.set_array("spacegroup_kinds", np.asarray(kinds, dtype=int))
        atoms.set_array("labels", np.asarray(labels, dtype=object))
        atoms.positions = np.vstack(positions)
        atoms.info["occupancy"] = occupancy
        if isinstance(source, SPRKKRAtoms):
            if not isinstance(atoms, SPRKKRAtoms):
                atoms = SPRKKRAtoms.promote_ase_atoms(
                    atoms, symmetry=False, update_info=False
                )
            self._apply_sprkkr_sites(atoms)
        return atoms

    def _apply_sprkkr_sites(self, atoms: SPRKKRAtoms) -> None:
        """Materialize site groups while retaining origin SiteType data."""
        source_sites = self._source_atoms.sites
        result_sites: list[Site] = []
        for draft_site in self.sites:
            occupation = self._occupancy_mapping(draft_site.occupancies)
            origin = next(
                (item for item in draft_site.origins if item is not None),
                None,
            )
            if origin is None:
                site_type = SiteType(atoms, occupation)
            else:
                site_type = source_sites[origin].site_type.copy(atoms=atoms)
                site_type.occupation.set(
                    self._occupation_with_preserved_types(
                        site_type, occupation
                    )
                )
            result_sites.extend(
                Site(site_type) for _position in draft_site.positions
            )
        atoms.set_sites(
            np.asarray(result_sites, dtype=object),
            spacegroup_info=False,
            update=True,
        )

    @staticmethod
    def _occupation_with_preserved_types(
        site_type: SiteType,
        occupation: dict[Any, float],
    ) -> dict[Any, float]:
        """Reuse matching AtomicTypes so their SPR-KKR data survive editing."""
        available: dict[str, list[AtomicType]] = {}
        for atomic_type in site_type.occupation:
            available.setdefault(atomic_type.symbol, []).append(atomic_type)
        result: dict[Any, float] = {}
        for key, value in occupation.items():
            symbol = getattr(key, "symbol", str(key))
            candidates = available.get(symbol, [])
            preserved = candidates.pop(0) if candidates else key
            result[preserved] = value
        return result

    def _rebuilt_site(self, source: Atoms, site: AssignmentSite) -> Atoms:
        """Rebuild an edited site while retaining data of sourced atoms."""
        result: Atoms | None = None
        for position, origin in zip(site.positions, site.origins):
            if origin is None:
                atom = Atoms(
                    positions=[position], cell=self._cell, pbc=True
                )
            else:
                atom = source[[origin]]
            result = atom if result is None else result + atom
        return result if result is not None else Atoms(cell=self._cell)

    def _partition_changed(self) -> bool:
        current = tuple(tuple(site.origins) for site in self.sites)
        return current != self._original_partition or any(
            origin is None for site in self.sites for origin in site.origins
        )

    def _site_index(self, site: AssignmentSite) -> int:
        for index, candidate in enumerate(self.sites):
            if candidate is site:
                return index
        raise ValueError("Site is not part of this assignment")

    def _occupancy_index(
        self, site: AssignmentSite, entry: OccupancyEntry
    ) -> int:
        self._site_index(site)
        for index, candidate in enumerate(site.occupancies):
            if candidate is entry:
                return index
        raise ValueError("Occupancy is not part of this site")

    @staticmethod
    def _unique_label(template: str, used: set[str]) -> str:
        if template not in used:
            return template
        suffix = 1
        while f"{template}.{suffix}" in used:
            suffix += 1
        return f"{template}.{suffix}"

    @staticmethod
    def _copy_occupancies(
        entries: Iterable[OccupancyEntry],
    ) -> list[OccupancyEntry]:
        return [OccupancyEntry(entry.symbol, entry.value) for entry in entries]

    @staticmethod
    def _occupancy_mapping(
        entries: Iterable[OccupancyEntry],
    ) -> dict[Any, float]:
        result: dict[Any, float] = {}
        for entry in entries:
            if not entry.symbol:
                continue
            key: Any = entry.symbol
            if key in result:
                key = AtomicType.from_symbol(entry.symbol)
            result[key] = entry.value
        return result

    @classmethod
    def _sites_from_atoms(cls, atoms: Atoms) -> list[AssignmentSite]:
        partitions = partition_by_kinds(atoms)
        kinds = (
            atoms.get_array("spacegroup_kinds")
            if "spacegroup_kinds" in atoms.arrays
            else None
        )
        stored_occupancy = atoms.info.get("occupancy", {})
        labels = labels_for_partitions(atoms, partitions=partitions)
        positions = atoms.get_scaled_positions()
        sites: list[AssignmentSite] = []
        for number, partition in enumerate(partitions):
            indices = [int(index) for index in partition]
            first = indices[0]
            occupancy = None
            if stored_occupancy and kinds is not None:
                occupancy = stored_occupancy.get(str(kinds[first]))
            if occupancy is None:
                symbol = atoms[first].symbol
                occupancy = {} if symbol == "X" else {symbol: 1.0}
            entries = [
                OccupancyEntry(
                    re.sub(r"_\d+$", "", getattr(symbol, "symbol", str(symbol))),
                    float(value),
                )
                for symbol, value in occupancy.items()
            ] or [OccupancyEntry()]
            sites.append(
                AssignmentSite(
                    label=str(labels[number]),
                    positions=np.asarray(positions[partition], dtype=float).copy(),
                    origins=indices,
                    occupancies=entries,
                )
            )
        return sites
