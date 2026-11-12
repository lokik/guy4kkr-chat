"""Semantic transitions over revisioned workspace values and the result tree."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from typing import Any

from ase import Atoms
from PyQt6.QtCore import QObject, pyqtSignal

from guy4ase.gui.application.historical_state import (
    HistoricalStateAlreadyActive,
    NewHistoricalPotential,
    resolve_historical_state,
)
from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.result_store import ResultRecord, ResultStore
from guy4ase.gui.application.workspace import (
    EmptySpheresState,
    Generation,
    OptimisticLocked,
    StructureState,
    WorkspaceState,
)
from guy4ase.gui.workspace_semantics import EmptySpheresAction as _EmptySpheresAction

_KEEP_DIRECTORY = object()


def _atoms_has_potential(atoms: Any) -> bool:
    """Return whether the authoritative atoms state owns a potential."""
    checker = getattr(atoms, "has_potential", None)
    return bool(callable(checker) and checker())


class DocumentChange(Enum):
    """Semantic result of a revision-sensitive workspace command."""

    APPLIED = auto()
    STALE = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class WorkspaceConflict:
    """One optimistic-lock mismatch presented to a conflict resolver."""

    component: str
    expected_generation: Generation
    current_generation: Generation


ConflictResolver = Callable[[tuple[WorkspaceConflict, ...]], bool]


class CalculationNotReady(RuntimeError):
    """The workspace does not contain all inputs required for calculation."""


@dataclass(frozen=True)
class CalculationRequest:
    """Immutable inputs and result-lineage provenance captured at launch.

    Completed calculations are always recorded against ``structure_id`` and
    ``state_id``. A state-producing output may advance the workspace only while
    that exact input state is still active.

    ``atoms`` identifies the authoritative launch input and is the sole physical
    authority for its potential; potential paths are provenance/artifact metadata
    only. The execution service copies the request atoms before ASE2SPRKKR sees
    them, so backend bookkeeping cannot mutate the workspace structure.

    ``restart_scf`` snapshots the pending workspace execution intent. It asks
    ASE2SPRKKR to serialize ``SCFSTATUS START`` for this run without mutating the
    authoritative workspace potential.
    """

    atoms: Atoms
    input_parameters: Any
    directory: str
    structure_id: int
    state_id: int
    restart_scf: bool = False


@dataclass(frozen=True)
class ResultAdoption:
    """Artifacts and workspace effect of recording a completed result."""

    output_path: Path | None = None
    potential_path: Path | None = None
    potential_error: Exception | None = None
    input_parameters_error: Exception | None = None
    workspace_updated: bool = False
    record: ResultRecord | None = None


class WorkspaceController(QObject):
    """Own revisioned next-calculation values and an independent result tree."""

    structureChanged = pyqtSignal(object)
    inputParametersChanged = pyqtSignal(object)
    directoryChanged = pyqtSignal(object)
    activeProjectChanged = pyqtSignal(object)
    resultChanged = pyqtSignal(object)
    resultSelectionRequested = pyqtSignal(int)

    def __init__(
        self,
        workspace: WorkspaceState | None = None,
        parent: QObject | None = None,
        *,
        conflict_resolver: ConflictResolver | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace or WorkspaceState()
        self._conflict_resolver = conflict_resolver
        self._results = ResultStore()

        structure_lock = self._workspace.structure
        structure = structure_lock.value
        if structure.atoms is not None:
            structure_id, state_id = self._results.new_structure_state(
                structure.atoms,
                potential_path=structure.potential_path,
                empty_spheres=structure.empty_spheres,
            )
            self._workspace.structure = OptimisticLocked(
                replace(
                    structure,
                    structure_id=structure_id,
                    state_id=state_id,
                ),
                generation=structure_lock.generation,
            )

    @property
    def structure_state(self) -> StructureState:
        return self._workspace.structure.value

    @property
    def atoms(self) -> Any:
        return self.structure_state.atoms

    @property
    def potential(self) -> Any | None:
        """Return the potential owned by the current atoms, if any."""
        return self.structure_state.potential

    @property
    def input_parameters(self) -> Any:
        return self._workspace.input_parameters.value

    @property
    def directory(self) -> str | None:
        return self._workspace.context.directory.value

    @property
    def active_project_id(self) -> str | None:
        return self._workspace.context.active_project_id.value

    @property
    def potential_path(self) -> str | None:
        """Return read-only potential provenance/artifact metadata."""
        return self.structure_state.potential_path

    @property
    def structure_id(self) -> int | None:
        return self.structure_state.structure_id

    @property
    def state_id(self) -> int | None:
        return self.structure_state.state_id

    @property
    def structure_generation(self) -> Generation:
        return self._workspace.structure.generation

    @property
    def input_parameters_generation(self) -> Generation:
        return self._workspace.input_parameters.generation

    @property
    def directory_generation(self) -> Generation:
        return self._workspace.context.directory.generation

    @property
    def active_project_generation(self) -> Generation:
        return self._workspace.context.active_project_id.generation

    @property
    def result(self) -> Any | None:
        """Return the latest result attached to the active workspace state."""
        record = self._results.latest_result_for_state(self.state_id)
        return record.result if record is not None else None

    @property
    def result_store(self) -> ResultStore:
        return self._results

    @property
    def empty_spheres(self) -> EmptySpheresState | None:
        return self.structure_state.empty_spheres

    @property
    def empty_spheres_added(self) -> int | None:
        return self.structure_state.empty_spheres_added

    @property
    def restarted(self) -> bool:
        return self.structure_state.restarted

    def structure_kind(self):
        return self.structure_state.structure_kind()

    def can_calculate(self) -> bool:
        """Return generic launch readiness, independent of Guided workflow policy."""
        return (
            self.atoms is not None
            and self.input_parameters is not None
            and bool(self.directory)
        )

    def can_build_2d(self) -> bool:
        return self.structure_kind() == "3d"

    def scf_status(self) -> str | None:
        return self.structure_state.scf_status()

    def is_scf_converged(self) -> bool:
        return self.structure_state.is_scf_converged()

    def has_vacuum_sites(self) -> bool:
        return self.structure_state.has_vacuum_sites()

    def empty_spheres_action(self) -> _EmptySpheresAction | None:
        """Return the empty-sphere workflow action recommended for the draft."""
        if self.atoms is None:
            return None
        if self.empty_spheres is not None:
            return _EmptySpheresAction.RECALCULATE
        if self.has_vacuum_sites():
            return None
        return _EmptySpheresAction.ADD

    def structure_change_requires_scf_restart(self) -> bool:
        if self.atoms is None or self.restarted:
            return False
        if self.is_scf_converged():
            return True
        return self.scf_status() not in (None, "START")

    def create_calculation_request(self) -> CalculationRequest:
        atoms = self.atoms
        parameters = self.input_parameters
        directory = self.directory
        structure_id = self.structure_id
        state_id = self.state_id
        if (
            atoms is None
            or parameters is None
            or not directory
            or structure_id is None
            or state_id is None
        ):
            raise CalculationNotReady(
                "Structure, input parameters, working directory and calculation state are required."
            )
        return CalculationRequest(
            atoms=atoms,
            input_parameters=parameters.copy(copy_values=True),
            directory=directory,
            structure_id=structure_id,
            state_id=state_id,
            restart_scf=self.restarted,
        )

    @staticmethod
    def _conflict(
        component: str,
        locked: OptimisticLocked[Any],
        expected_generation: Generation | None,
    ) -> WorkspaceConflict | None:
        if expected_generation is None or locked.is_current(expected_generation):
            return None
        return WorkspaceConflict(
            component=component,
            expected_generation=expected_generation,
            current_generation=locked.generation,
        )

    def _prepare_change(
        self,
        checks: tuple[tuple[str, OptimisticLocked[Any], Generation | None], ...],
    ) -> tuple[DocumentChange | None, bool]:
        """Resolve all optimistic mismatches before any state is mutated.

        The bool result says that the user explicitly approved overwriting a
        newer value, so the caller must commit with ``force_change``.
        """
        while True:
            conflicts = tuple(
                conflict
                for component, locked, expected in checks
                if (conflict := self._conflict(component, locked, expected)) is not None
            )
            if not conflicts:
                return None, False
            if self._conflict_resolver is None:
                return DocumentChange.STALE, False

            displayed = {
                component: locked.generation
                for component, locked, _expected in checks
            }
            if not self._conflict_resolver(conflicts):
                return DocumentChange.CANCELLED, False

            # A Qt resolver may run a nested event loop. If the workspace changed
            # again while the confirmation dialog was open, the user has not seen
            # that newer conflict yet; ask again instead of force-overwriting it.
            if all(
                locked.generation == displayed[component]
                for component, locked, _expected in checks
            ):
                return None, True

    @staticmethod
    def _commit_locked(
        locked: OptimisticLocked[Any],
        value: Any,
        *,
        expected_generation: Generation | None,
        force: bool,
    ) -> None:
        if force or expected_generation is None:
            locked.force_change(value)
            return
        if not locked.change(value, expected_generation):
            raise RuntimeError("workspace generation changed during an atomic commit")

    def replace_structure(
        self,
        atoms: Any,
        *,
        potential_path: str | None = None,
        directory: Any = _KEEP_DIRECTORY,
        expected_structure_generation: Generation | None = None,
        expected_directory_generation: Generation | None = None,
        restarted: bool = False,
    ) -> DocumentChange:
        checks = [(
            "structure",
            self._workspace.structure,
            expected_structure_generation,
        )]
        if directory is not _KEEP_DIRECTORY:
            checks.append(
                (
                    "working directory",
                    self._workspace.context.directory,
                    expected_directory_generation,
                )
            )
        rejected, force = self._prepare_change(tuple(checks))
        if rejected is not None:
            return rejected

        if atoms is None:
            structure_id = state_id = None
        else:
            structure_id, state_id = self._results.new_structure_state(
                atoms,
                potential_path=potential_path,
                empty_spheres=None,
            )
        structure = StructureState(
            atoms=atoms,
            potential_path=potential_path,
            structure_id=structure_id,
            state_id=state_id,
            empty_spheres=None,
            restarted=restarted,
        )
        self._commit_locked(
            self._workspace.structure,
            structure,
            expected_generation=expected_structure_generation,
            force=force,
        )

        directory_changed = False
        if directory is not _KEEP_DIRECTORY and directory != self.directory:
            directory_changed = True
            self._commit_locked(
                self._workspace.context.directory,
                directory,
                expected_generation=expected_directory_generation,
                force=force,
            )
        if directory_changed:
            self.directoryChanged.emit(directory)
        self.structureChanged.emit(atoms)
        return DocumentChange.APPLIED

    def apply_structure_edit(
        self,
        edit: Callable[[Any], Any],
        *,
        expected_structure_generation: Generation,
    ) -> DocumentChange | None:
        rejected, _ = self._prepare_change(
            ((
                "structure",
                self._workspace.structure,
                expected_structure_generation,
            ),)
        )
        if rejected is not None:
            return rejected

        source = self.atoms
        if source is None:
            raise ValueError("No structure is loaded.")
        edit_generation = self.structure_generation
        atoms = edit(source.copy())
        if atoms is None:
            return None

        rejected, force = self._prepare_change(
            (("structure", self._workspace.structure, edit_generation),)
        )
        if rejected is not None:
            return rejected

        structure_id, state_id = self._results.new_structure_state(
            atoms,
            potential_path=None,
            empty_spheres=None,
        )
        structure = StructureState(
            atoms=atoms,
            potential_path=None,
            structure_id=structure_id,
            state_id=state_id,
            empty_spheres=None,
            restarted=True,
        )
        self._commit_locked(
            self._workspace.structure,
            structure,
            expected_generation=edit_generation,
            force=force,
        )
        self.structureChanged.emit(atoms)
        return DocumentChange.APPLIED

    def replace_input_parameters(
        self,
        parameters: Any,
        *,
        directory: Any = _KEEP_DIRECTORY,
        expected_input_parameters_generation: Generation | None = None,
        expected_structure_generation: Generation | None = None,
        expected_directory_generation: Generation | None = None,
    ) -> DocumentChange:
        checks = [(
            "input parameters",
            self._workspace.input_parameters,
            expected_input_parameters_generation,
        )]
        if expected_structure_generation is not None:
            checks.append((
                "structure",
                self._workspace.structure,
                expected_structure_generation,
            ))
        if directory is not _KEEP_DIRECTORY:
            checks.append(
                (
                    "working directory",
                    self._workspace.context.directory,
                    expected_directory_generation,
                )
            )
        rejected, force = self._prepare_change(tuple(checks))
        if rejected is not None:
            return rejected

        self._commit_locked(
            self._workspace.input_parameters,
            parameters,
            expected_generation=expected_input_parameters_generation,
            force=force,
        )
        directory_changed = False
        if directory is not _KEEP_DIRECTORY and directory != self.directory:
            directory_changed = True
            self._commit_locked(
                self._workspace.context.directory,
                directory,
                expected_generation=expected_directory_generation,
                force=force,
            )
        if directory_changed:
            self.directoryChanged.emit(directory)
        self.inputParametersChanged.emit(parameters)
        return DocumentChange.APPLIED

    def change_directory(
        self,
        directory: str | None,
        *,
        expected_directory_generation: Generation | None = None,
    ) -> DocumentChange:
        if directory == self.directory:
            return DocumentChange.APPLIED
        rejected, force = self._prepare_change(
            ((
                "working directory",
                self._workspace.context.directory,
                expected_directory_generation,
            ),)
        )
        if rejected is not None:
            return rejected
        self._commit_locked(
            self._workspace.context.directory,
            directory,
            expected_generation=expected_directory_generation,
            force=force,
        )
        self.directoryChanged.emit(directory)
        return DocumentChange.APPLIED

    def set_active_project(
        self,
        project_id: str | None,
        *,
        expected_active_project_generation: Generation | None = None,
    ) -> DocumentChange:
        if project_id == self.active_project_id:
            return DocumentChange.APPLIED
        rejected, force = self._prepare_change(
            ((
                "active project",
                self._workspace.context.active_project_id,
                expected_active_project_generation,
            ),)
        )
        if rejected is not None:
            return rejected
        self._commit_locked(
            self._workspace.context.active_project_id,
            project_id,
            expected_generation=expected_active_project_generation,
            force=force,
        )
        self.activeProjectChanged.emit(project_id)
        return DocumentChange.APPLIED

    @staticmethod
    def _result_adoption(
        loaded: LoadedResult,
        *,
        record: ResultRecord | None = None,
        workspace_updated: bool = False,
    ) -> ResultAdoption:
        return ResultAdoption(
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            potential_error=loaded.potential_error,
            input_parameters_error=loaded.input_parameters_error,
            workspace_updated=workspace_updated,
            record=record,
        )

    def adopt_external_result(
        self,
        loaded: LoadedResult,
        *,
        select_result: bool = False,
    ) -> ResultAdoption:
        """Record an imported result without implicitly replacing the workspace."""
        record = self._results.add_external_result(
            loaded.result,
            atoms=loaded.atoms,
            input_parameters=loaded.input_parameters,
            directory=loaded.directory,
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            persistent_ref=loaded.persistent_ref,
        )
        self.resultChanged.emit(loaded.result)
        if select_result:
            self.resultSelectionRequested.emit(record.id)
        return self._result_adoption(loaded, record=record)

    def adopt_calculation_result(
        self,
        loaded: LoadedResult,
        *,
        request: CalculationRequest,
    ) -> ResultAdoption:
        """Record a launched result against its exact captured provenance."""
        produces_potential = loaded.result.produces_potential
        output_atoms = (
            loaded.atoms
            if produces_potential and loaded.atoms is not None
            else None
        )
        output_potential_path = (
            str(loaded.potential_path)
            if produces_potential and loaded.potential_path is not None
            else None
        )
        record = self._results.add_result(
            loaded.result,
            structure_id=request.structure_id,
            input_state_id=request.state_id,
            input_parameters=request.input_parameters,
            directory=request.directory,
            persistent_ref=loaded.persistent_ref,
            restart_scf=request.restart_scf,
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            output_atoms=output_atoms,
            output_potential_path=output_potential_path,
        )

        workspace_updated = False
        current = self.structure_state
        if (
            produces_potential
            and output_atoms is not None
            and record.output_state_id is not None
            and request.structure_id == current.structure_id
            and request.state_id == current.state_id
        ):
            state = self._results.state(record.output_state_id)
            self._workspace.structure.force_change(
                StructureState(
                    atoms=output_atoms,
                    potential_path=state.potential_path,
                    structure_id=state.structure_id,
                    state_id=state.id,
                    empty_spheres=state.empty_spheres,
                    restarted=False,
                )
            )
            workspace_updated = True
            self.structureChanged.emit(output_atoms)

        self.resultChanged.emit(loaded.result)
        return self._result_adoption(
            loaded,
            record=record,
            workspace_updated=workspace_updated,
        )

    def use_result_state(
        self,
        result_id: int,
        expected_potential: PotentialFileVersion | None = None,
        *,
        expected_structure_generation: Generation | None = None,
    ) -> DocumentChange:
        rejected, _ = self._prepare_change(
            ((
                "structure",
                self._workspace.structure,
                expected_structure_generation,
            ),)
        )
        if rejected is not None:
            return rejected
        baseline = self.structure_generation

        resolution = resolve_historical_state(
            self._results,
            result_id,
            active_state_id=self.state_id,
            expected_potential=expected_potential,
        )
        if isinstance(resolution, HistoricalStateAlreadyActive):
            return DocumentChange.APPLIED

        rejected, force = self._prepare_change(
            (("structure", self._workspace.structure, baseline),)
        )
        if rejected is not None:
            return rejected

        atoms = resolution.atoms
        if isinstance(resolution, NewHistoricalPotential):
            target_state_id = self._results.new_child_state(
                resolution.parent_state.id,
                potential_path=str(resolution.potential_version.path),
                potential_version=resolution.potential_version,
                empty_spheres=None,
            )
            target_state = self._results.state(target_state_id)
        else:
            target_state = resolution.state

        structure = StructureState(
            atoms=atoms,
            potential_path=target_state.potential_path,
            structure_id=target_state.structure_id,
            state_id=target_state.id,
            empty_spheres=target_state.empty_spheres,
            restarted=(
                target_state.parent_id is not None and not _atoms_has_potential(atoms)
            ),
        )
        self._commit_locked(
            self._workspace.structure,
            structure,
            expected_generation=baseline,
            force=force,
        )
        self.structureChanged.emit(atoms)
        return DocumentChange.APPLIED

    def reset(self) -> None:
        """Clear calculation values while preserving history and active project."""
        structure = self.structure_state
        if (
            structure.atoms is not None
            or structure.potential_path is not None
            or structure.structure_id is not None
            or structure.state_id is not None
            or structure.empty_spheres is not None
            or structure.restarted
        ):
            self._workspace.structure.force_change(StructureState())
        if self.input_parameters is not None:
            self._workspace.input_parameters.force_change(None)
        if self.directory is not None:
            self._workspace.context.directory.force_change(None)
        self.structureChanged.emit(None)
        self.inputParametersChanged.emit(None)
        self.directoryChanged.emit(None)

    def use_for_new_calculation(
        self,
        *,
        result_id: int | None = None,
        expected_potential: PotentialFileVersion | None = None,
        expected_structure_generation: Generation | None = None,
    ) -> DocumentChange:
        """Create one new calculation branch from active or historical state."""
        rejected, _ = self._prepare_change(
            ((
                "structure",
                self._workspace.structure,
                expected_structure_generation,
            ),)
        )
        if rejected is not None:
            return rejected
        baseline = self.structure_generation

        child_kwargs: dict[str, Any] = {}
        if result_id is None:
            atoms = self.atoms
            parent_state_id = self.state_id
        else:
            resolution = resolve_historical_state(
                self._results,
                result_id,
                active_state_id=self.state_id,
                expected_potential=expected_potential,
            )
            if isinstance(resolution, HistoricalStateAlreadyActive):
                atoms = self.atoms
                parent_state_id = self.state_id
            elif isinstance(resolution, NewHistoricalPotential):
                atoms = resolution.atoms
                parent_state_id = resolution.parent_state.id
                child_kwargs = {
                    "potential_path": str(resolution.potential_version.path),
                    "potential_version": resolution.potential_version,
                    "empty_spheres": None,
                }
            else:
                atoms = resolution.atoms
                parent_state_id = resolution.state.id

        rejected, force = self._prepare_change(
            (("structure", self._workspace.structure, baseline),)
        )
        if rejected is not None:
            return rejected
        if atoms is None or parent_state_id is None:
            raise ValueError("No calculation state is available for a new branch.")

        state_id = self._results.new_child_state(
            parent_state_id,
            new_branch=True,
            **child_kwargs,
        )
        state = self._results.state(state_id)
        structure = StructureState(
            atoms=atoms,
            potential_path=state.potential_path,
            structure_id=state.structure_id,
            state_id=state.id,
            empty_spheres=state.empty_spheres,
            restarted=True,
        )
        self._commit_locked(
            self._workspace.structure,
            structure,
            expected_generation=baseline,
            force=force,
        )
        self.structureChanged.emit(atoms)
        return DocumentChange.APPLIED

    def update_empty_spheres(
        self,
        edit: Callable[[Any, int], tuple[Any, int, bool]],
        *,
        expected_structure_generation: Generation,
        parameters: Mapping[str, Any] | None = None,
    ) -> DocumentChange:
        rejected, _ = self._prepare_change(
            ((
                "structure",
                self._workspace.structure,
                expected_structure_generation,
            ),)
        )
        if rejected is not None:
            return rejected

        source = self.atoms
        structure_id = self.structure_id
        state_id = self.state_id
        if source is None or structure_id is None or state_id is None:
            raise ValueError("No structure is loaded.")

        baseline = self.structure_generation
        previous_state = self.empty_spheres
        previous_count = previous_state.count if previous_state is not None else 0
        updated, count, structure_changed = edit(source.copy(), previous_count)

        rejected, force = self._prepare_change(
            (("structure", self._workspace.structure, baseline),)
        )
        if rejected is not None:
            return rejected

        empty_spheres = EmptySpheresState(count=count, parameters=parameters or {})
        result = EmptySpheresResult(found=empty_spheres.count)
        record = self._results.add_result(
            result,
            structure_id=structure_id,
            input_state_id=state_id,
            input_parameters=empty_spheres.parameters,
            directory=self.directory,
            output_atoms=updated if structure_changed else None,
            output_potential_path=(None if structure_changed else self.potential_path),
            output_empty_spheres=empty_spheres,
        )

        assert record.output_state_id is not None
        state = self._results.state(record.output_state_id)
        active_atoms = updated if structure_changed else source
        structure = StructureState(
            atoms=active_atoms,
            potential_path=state.potential_path,
            structure_id=state.structure_id,
            state_id=state.id,
            empty_spheres=state.empty_spheres,
            restarted=self.restarted or structure_changed,
        )
        self._commit_locked(
            self._workspace.structure,
            structure,
            expected_generation=baseline,
            force=force,
        )
        if structure_changed:
            self.structureChanged.emit(active_atoms)
        self.resultChanged.emit(result)
        return DocumentChange.APPLIED
