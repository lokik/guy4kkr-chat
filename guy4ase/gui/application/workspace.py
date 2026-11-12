"""Mutable workspace values and their optimistic revisions."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from ase2sprkkr import SPRKKRAtoms

from guy4ase.physics.lattice import StructureKind, detect_structure_kind


T = TypeVar("T")


@dataclass(frozen=True)
class Generation:
    """Monotonic revision of one independently changeable workspace value."""

    value: int = 0

    def next(self) -> Generation:
        return Generation(self.value + 1)


class OptimisticLocked(Generic[T]):
    """A value changed through compare-and-swap style optimistic locking."""

    __slots__ = ("_value", "_generation")

    def __init__(
        self,
        value: T,
        *,
        generation: Generation | None = None,
    ) -> None:
        self._value = value
        self._generation = generation or Generation()

    @property
    def value(self) -> T:
        return self._value

    @property
    def generation(self) -> Generation:
        return self._generation

    def is_current(self, expected_generation: Generation) -> bool:
        return expected_generation == self._generation

    def change(self, value: T, expected_generation: Generation) -> bool:
        """Replace the value iff ``expected_generation`` is still current."""
        if not self.is_current(expected_generation):
            return False
        self.force_change(value)
        return True

    def force_change(self, value: T) -> Generation:
        """Replace the value unconditionally and return its new generation."""
        self._value = value
        self._generation = self._generation.next()
        return self._generation


@dataclass(frozen=True)
class EmptySpheresState:
    """Provenance of the latest explicit empty-sphere search."""

    count: int
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        count = int(self.count)
        if count < 0:
            raise ValueError("Empty-sphere count cannot be negative.")
        object.__setattr__(self, "count", count)
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(deepcopy(dict(self.parameters))),
        )


@dataclass(frozen=True)
class StructureState:
    """Atom-centred state from which the next calculation will start.

    ``atoms`` is the sole physical authority, including an attached SPR-KKR
    potential. ``potential_path`` and the result-tree ids are read-only
    bookkeeping that changes only together with this structure state.
    """

    atoms: Any | None = None
    potential_path: str | None = None
    structure_id: int | None = None
    state_id: int | None = None
    empty_spheres: EmptySpheresState | None = None
    restarted: bool = False

    @property
    def potential(self) -> Any | None:
        atoms = self.atoms
        checker = getattr(atoms, "has_potential", None)
        if not callable(checker) or not checker():
            return None
        return atoms.potential

    @property
    def empty_spheres_added(self) -> int | None:
        if self.empty_spheres is None:
            return None
        return self.empty_spheres.count

    def structure_kind(self) -> StructureKind | None:
        return detect_structure_kind(self.atoms)

    def scf_status(self) -> str | None:
        """Return the effective SCFSTATUS of the active structure state."""
        atoms = self.atoms
        if atoms is None:
            return None
        if self.restarted:
            return "START"
        if not isinstance(atoms, SPRKKRAtoms):
            return None
        if not atoms.has_potential():
            return None
        status = atoms.potential.SCF_INFO.SCFSTATUS()
        if status is None:
            return None
        status = str(status).strip().upper()
        return status or None

    def is_scf_converged(self) -> bool:
        """Return convergence of the active structure potential only."""
        if self.restarted:
            return False
        atoms = self.atoms
        if atoms is None:
            return False
        checker = getattr(atoms, "sprkkr_is_scf_converged", None)
        return bool(callable(checker) and checker())

    def has_vacuum_sites(self) -> bool:
        if self.atoms is None:
            return False
        if isinstance(self.atoms, SPRKKRAtoms):
            return any(site.is_vacuum() for site in self.atoms.sites)
        return any(
            int(number) == 0 for number in getattr(self.atoms, "numbers", ())
        )


@dataclass
class WorkspaceContext:
    """Independently revisioned non-physical context for the next launch."""

    directory: OptimisticLocked[str | None] = field(
        default_factory=lambda: OptimisticLocked(None)
    )
    active_project_id: OptimisticLocked[str | None] = field(
        default_factory=lambda: OptimisticLocked(None)
    )

    @classmethod
    def from_values(
        cls,
        *,
        directory: str | None = None,
        active_project_id: str | None = None,
    ) -> WorkspaceContext:
        return cls(
            directory=OptimisticLocked(directory),
            active_project_id=OptimisticLocked(active_project_id),
        )


@dataclass(init=False)
class WorkspaceState:
    """Revisioned values that define the user's current calculation workspace.

    Results deliberately live outside this object in ``ResultStore``. Each
    independently changeable workspace value owns its own optimistic generation.
    Plain constructor arguments are initial values only; stored/public state is
    always represented by the explicit locks below.
    """

    structure: OptimisticLocked[StructureState]
    input_parameters: OptimisticLocked[Any | None]
    context: WorkspaceContext

    def __init__(
        self,
        *,
        atoms: Any | None = None,
        input_parameters: Any | None = None,
        directory: str | None = None,
        potential_path: str | None = None,
        empty_spheres: EmptySpheresState | None = None,
        restarted: bool = False,
        active_project_id: str | None = None,
    ) -> None:
        self.structure = OptimisticLocked(
            StructureState(
                atoms=atoms,
                potential_path=potential_path,
                empty_spheres=empty_spheres,
                restarted=restarted,
            )
        )
        self.input_parameters = OptimisticLocked(input_parameters)
        self.context = WorkspaceContext.from_values(
            directory=directory,
            active_project_id=active_project_id,
        )

    @classmethod
    def from_values(cls, **values: Any) -> WorkspaceState:
        """Explicit spelling for callers that prefer factory-style construction."""
        return cls(**values)
