"""Semantic transitions over revisioned workspace values and the result tree."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path
from typing import Any

from ase import Atoms
from PyQt6.QtCore import QObject, pyqtSignal

from ase2sprkkr_gui.ase.copy import copy_for_edit
from ase2sprkkr_gui.gui.application.historical_state import (
    HistoricalStateAlreadyActive,
    NewHistoricalPotential,
    resolve_historical_state,
)
from ase2sprkkr_gui.gui.application.operation_results import EmptySpheresResult
from ase2sprkkr_gui.gui.application.potential_version import PotentialFileVersion
from ase2sprkkr_gui.gui.application.result_loading import LoadedResult
from ase2sprkkr_gui.gui.application.result_store import ResultRecord, ResultStore
from ase2sprkkr_gui.gui.application.workspace import (
    EmptySpheresState,
    Generation,
    OptimisticLocked,
    StructureState,
    WorkspaceState,
)
from ase2sprkkr_gui.gui.workspace_semantics import EmptySpheresAction as _EmptySpheresAction

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

    An ordinary launch uses the attached potential of its workspace atoms.
    A file-backed launch retains the native paths in the input parameters and
    captures the parsed atoms for result provenance.

    ``restart_scf`` snapshots the pending workspace execution intent. It asks
    ASE2SPRKKR to serialize ``SCFSTATUS START`` for this run without mutating the
    authoritative workspace potential.
    """

    atoms: Atoms
    input_parameters: Any
    directory: str
    structure_id: int | None
    state_id: int | None
    restart_scf: bool = False
    clear_cache: bool = False
    # An explicit host Potential can be used without rebuilding it from a copy
    # of its atoms (which would lose its native SCFSTATUS).
    # False selects the backend's existing-POTFIL mode.
    potential: Any | None = None
    # Parsed and versioned source from an input file, not part of the workspace.
    file_source: Any | None = None


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
        # A native CLUPOT may be opened read-only without its host POTFIL.
        # It is a loaded file, not an editable Atoms document or unsaved work.
        self._unresolved_cluster = None
        self._unresolved_cluster_path: Path | None = None
        # The loaded or written revision, not merely the presence of a file.
        self._saved_structure_generation: Generation | None = None
        self._saved_input_parameters_generation: Generation | None = None

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
    def unresolved_cluster(self):
        """Native read-only CLUPOT awaiting an explicitly provided host."""
        return self._unresolved_cluster

    @property
    def unresolved_cluster_path(self) -> Path | None:
        return self._unresolved_cluster_path

    def load_unresolved_cluster(
        self,
        potential,
        path: str | Path,
        *,
        expected_structure_generation: Generation | None = None,
        expected_directory_generation: Generation | None = None,
    ) -> DocumentChange:
        """Open an orphan CLUPOT without treating it as an editable structure."""
        path = Path(path).resolve()
        change = self.replace_structure(
            None,
            directory=str(path.parent),
            expected_structure_generation=expected_structure_generation,
            expected_directory_generation=expected_directory_generation,
            emit_structure_changed=False,
        )
        if change is DocumentChange.APPLIED:
            self._unresolved_cluster = potential
            self._unresolved_cluster_path = path
            self.structureChanged.emit(None)
        return change

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
    def has_unsaved_structure(self) -> bool:
        return (
            self.atoms is not None
            and self.structure_generation != self._saved_structure_generation
        )

    @property
    def has_unsaved_input_parameters(self) -> bool:
        return (
            self.input_parameters is not None
            and self.input_parameters_generation != self._saved_input_parameters_generation
        )

    def mark_structure_saved(self, generation: Generation) -> bool:
        """Record only the structure revision actually loaded or written."""
        if generation != self.structure_generation or self.atoms is None:
            return False
        self._saved_structure_generation = generation
        return True

    def _mark_file_backed_structure_saved(self, state_id: int) -> None:
        """A structure recovered from an available POTFIL is already saved."""
        version = self._results.state(state_id).potential_version
        if version is not None and version.available:
            self.mark_structure_saved(self.structure_generation)

    def mark_input_parameters_saved(self, generation: Generation) -> bool:
        """Do not mark changes made during a file dialog as saved."""
        if generation != self.input_parameters_generation or self.input_parameters is None:
            return False
        self._saved_input_parameters_generation = generation
        return True

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

    def can_run_embedding(self) -> bool:
        """A guided cluster task can be configured once a native host exists."""
        if self.structure_kind() != "0d":
            return False
        from ase2sprkkr import Potential

        return isinstance(getattr(self.atoms, "embedding_host", None), Potential)

    def embedding_host_scf_status(self) -> str | None:
        """Raw host SCFSTATUS; a START host is not a converged input for embedding."""
        if self.structure_kind() != "0d":
            return None
        from ase2sprkkr import Potential

        host = getattr(self.atoms, "embedding_host", None)
        if not isinstance(host, Potential):
            return None
        status = host.SCF_INFO.SCFSTATUS()
        return str(status).strip().upper() if status is not None else None

    def replace_embedding_host_if_current(self, expected_host, new_host) -> bool:
        """Attach a completed host SCF to the *latest* embedded cluster.

        Cluster edits made during the host calculation must survive. Only a
        different host reference (or switching away from the cluster) prevents
        adoption. The previous cluster SCF is no longer considered converged.
        """
        from ase2sprkkr import Potential
        from ase2sprkkr_gui.gui.application.structure_snapshot import StructureSnapshot

        if not isinstance(new_host, Potential):
            raise TypeError("Host SCF must produce a periodic SPR-KKR Potential.")
        atoms = self.atoms
        if (self.structure_kind() != "0d" or
                getattr(atoms, "embedding_host", None) is not expected_host):
            return False
        if self.state_id is None:
            return False

        # Work on the latest cluster rather than the launch-time snapshot.
        # SPRKKRAtoms.copy retains the host by reference; updating the copy
        # does not affect the original or lose edits to sites/occupations.
        updated = copy_for_edit(atoms)
        updated.embedding_host = new_host
        # A different host invalidates the earlier embedded SCF, even if
        # the cluster sites still carry a full set of radial data. Attach an
        # explicit START ClusterPotential rather than allowing the atom data
        # to be misinterpreted as an already converged cluster.
        from ase2sprkkr.potentials.cluster_potentials import ClusterPotential

        updated._potential = None
        updated.info["sprkkr_embedding_scf_status"] = "START"
        updated._potential = ClusterPotential.from_atoms(updated, scf_status="START")

        parent_id = self.state_id
        state_id = self._results.new_child_state(
            parent_id,
            potential_path=None,
            structure_snapshot=StructureSnapshot.capture(updated),
            empty_spheres=None,
            new_branch=True,
        )
        state = self._results.state(state_id)
        self._workspace.structure.force_change(StructureState(
            atoms=updated,
            potential_path=None,
            structure_id=state.structure_id,
            state_id=state.id,
            empty_spheres=None,
            restarted=False,
        ))
        self.structureChanged.emit(updated)
        return True

    def can_calculate(self) -> bool:
        """Whether a fully configured calculation can be launched."""
        if self.atoms is None or self.input_parameters is None:
            return False
        return self.structure_kind() != "0d" or self.can_run_embedding()

    def can_build_2d(self) -> bool:
        return self.structure_kind() == "3d"

    def can_build_embedding(self) -> bool:
        """A 3D/2D host or existing embedded cluster can open the editor."""
        kind = self.structure_kind()
        return (kind in {"3d", "2d"}
                or (kind == "0d" and
                    getattr(self.atoms, "embedding_host", None) is not None))

    def scf_status(self) -> str | None:
        return self.structure_state.scf_status()

    def is_scf_converged(self) -> bool:
        return self.structure_state.is_scf_converged()

    def has_vacuum_sites(self) -> bool:
        return self.structure_state.has_vacuum_sites()

    def empty_spheres_action(self) -> _EmptySpheresAction | None:
        """Return the empty-sphere workflow action recommended for the draft."""
        if self.atoms is None or self.structure_kind() == "0d":
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
        if not self.can_calculate():
            raise CalculationNotReady(
                "An embedded calculation requires a host SPR-KKR Potential."
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
        emit_structure_changed: bool = True,
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
        # A successfully loaded regular structure replaces the read-only CLUPOT.
        self._unresolved_cluster = None
        self._unresolved_cluster_path = None
        if emit_structure_changed:
            self.structureChanged.emit(atoms)
        return DocumentChange.APPLIED

    def apply_structure_edit(
        self,
        edit: Callable[[Any], Any],
        *,
        expected_structure_generation: Generation,
        copy_source: bool = True,
    ) -> DocumentChange | None:
        """Apply an edit transactionally, using a shallow editing copy by default.

        Read-only dialogs that create their own result use ``copy_source=False``
        to retain the source identity until an actual edit is accepted.
        """
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
        atoms = edit(copy_for_edit(source) if copy_source else source)
        if atoms is None or atoms is source:
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
            # New embedded clusters already start with SCFSTATUS=START.
            # Do not request another restart (which would discard radial data).
            restarted="sprkkr_embedding" not in getattr(atoms, "arrays", {}),
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

    def _change_context(
        self,
        *,
        directory: str | None | object = _KEEP_DIRECTORY,
        project_id: str | None | object = _KEEP_DIRECTORY,
        expected_directory_generation: Generation | None = None,
        expected_active_project_generation: Generation | None = None,
    ) -> DocumentChange:
        """Change workspace context atomically, checking all changed values."""
        directory_changed = (
            directory is not _KEEP_DIRECTORY and directory != self.directory
        )
        project_changed = (
            project_id is not _KEEP_DIRECTORY and project_id != self.active_project_id
        )
        checks = []
        if directory_changed:
            checks.append((
                "working directory",
                self._workspace.context.directory,
                expected_directory_generation,
            ))
        if project_changed:
            checks.append((
                "active project",
                self._workspace.context.active_project_id,
                expected_active_project_generation,
            ))
        if not checks:
            return DocumentChange.APPLIED
        rejected, force = self._prepare_change(tuple(checks))
        if rejected is not None:
            return rejected

        if directory_changed:
            self._commit_locked(
                self._workspace.context.directory,
                directory,
                expected_generation=expected_directory_generation,
                force=force,
            )
        if project_changed:
            self._commit_locked(
                self._workspace.context.active_project_id,
                project_id,
                expected_generation=expected_active_project_generation,
                force=force,
            )
        # Publish only after both values have been committed.
        if directory_changed:
            self.directoryChanged.emit(directory)
        if project_changed:
            self.activeProjectChanged.emit(project_id)
        return DocumentChange.APPLIED

    def change_directory(
        self,
        directory: str | None,
        *,
        expected_directory_generation: Generation | None = None,
    ) -> DocumentChange:
        return self._change_context(
            directory=directory,
            expected_directory_generation=expected_directory_generation,
        )

    def set_active_project(
        self,
        project_id: str | None,
        *,
        expected_active_project_generation: Generation | None = None,
    ) -> DocumentChange:
        return self._change_context(
            project_id=project_id,
            expected_active_project_generation=expected_active_project_generation,
        )

    def set_calculation_context(
        self,
        directory: str,
        project_id: str | None,
        *,
        expected_directory_generation: Generation | None = None,
        expected_active_project_generation: Generation | None = None,
    ) -> DocumentChange:
        """Commit the execution dialog's directory and active project together."""
        return self._change_context(
            directory=directory,
            project_id=project_id,
            expected_directory_generation=expected_directory_generation,
            expected_active_project_generation=expected_active_project_generation,
        )

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
            source_versions=loaded.source_versions,
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
        structure_id, state_id = request.structure_id, request.state_id
        if request.potential is False:
            source = loaded.file_backed_input
            if source is None:
                raise ValueError("File-backed results require a captured launch input.")
            version = source.potential_version
            structure_id, state_id = self._results.new_structure_state(
                source.atoms,
                potential_path=str(version.path),
                potential_version=version,
                source_versions=source.input_versions,
            )
        record = self._results.add_result(
            loaded.result,
            structure_id=structure_id,
            input_state_id=state_id,
            input_parameters=request.input_parameters,
            directory=request.directory,
            persistent_ref=loaded.persistent_ref,
            restart_scf=request.restart_scf,
            output_path=loaded.output_path,
            potential_path=loaded.potential_path,
            output_atoms=loaded.atoms,
            output_potential_path=(
                str(loaded.potential_path)
                if loaded.potential_path is not None
                else None
            ),
            output_potential_version=loaded.output_potential_version,
        )

        workspace_updated = False
        current = self.structure_state
        if (
            loaded.atoms is not None
            and record.output_state_id is not None
            and structure_id == current.structure_id
            and state_id == current.state_id
        ):
            state = self._results.state(record.output_state_id)
            self._workspace.structure.force_change(
                StructureState(
                    atoms=loaded.atoms,
                    potential_path=state.potential_path,
                    structure_id=state.structure_id,
                    state_id=state.id,
                    empty_spheres=state.empty_spheres,
                    restarted=False,
                )
            )
            workspace_updated = True
            self._mark_file_backed_structure_saved(state.id)
            self.structureChanged.emit(loaded.atoms)

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
        self._mark_file_backed_structure_saved(target_state.id)
        self.structureChanged.emit(atoms)
        return DocumentChange.APPLIED

    def reset(self) -> None:
        """Clear calculation values while preserving history and active project."""
        self._unresolved_cluster = None
        self._unresolved_cluster_path = None
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
        # Branching a calculation changes provenance, not necessarily geometry.
        source_was_saved = not self.has_unsaved_structure
        source_state_id = self.state_id

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
        if source_was_saved and parent_state_id == source_state_id:
            self.mark_structure_saved(self.structure_generation)
        else:
            self._mark_file_backed_structure_saved(state.id)
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
        updated, count, structure_changed = edit(copy_for_edit(source), previous_count)

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
