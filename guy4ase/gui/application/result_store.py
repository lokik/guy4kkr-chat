"""Calculation-result provenance independent of the mutable workspace draft."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from guy4ase.gui.application.file_version import FileState, FileVersion
from guy4ase.gui.application.potential_version import PotentialFileVersion
from guy4ase.gui.application.result_contract import ResultCapabilities
from guy4ase.gui.application.result_files import capture_result_files
from guy4ase.gui.application.structure_snapshot import StructureSnapshot
from guy4ase.gui.application.workspace import EmptySpheresState
from guy4ase.physics.composition import structure_formula

_KEEP_POTENTIAL = object()
_KEEP_EMPTY_SPHERES = object()
_KEEP_POTENTIAL_SOURCE = object()
_KEEP_STRUCTURE = object()


def _task_name(result: ResultCapabilities) -> str:
    """Capture a stable normalized task identity from a result."""
    return str(result.task_name).strip().lower()


def _snapshot_input_parameters(parameters: Any | None) -> Any | None:
    """Detach small mutable input provenance from its live source object."""
    if parameters is None:
        return None

    copier = getattr(parameters, "copy", None)
    if callable(copier):
        try:
            return copier(copy_values=True)
        except TypeError:
            pass

    if isinstance(parameters, Mapping):
        return deepcopy(dict(parameters))
    return deepcopy(parameters)


def _capture_potential(path: str | Path | None) -> PotentialFileVersion | None:
    return PotentialFileVersion.capture(path) if path is not None else None


def _resolve_potential_version(
    path: str | Path | None,
    version: PotentialFileVersion | None,
) -> PotentialFileVersion | None:
    if version is None:
        return _capture_potential(path)
    if path is None:
        raise AssertionError("A captured potential version requires its potential path.")
    resolved_path = Path(path).expanduser().absolute()
    if version.path != resolved_path:
        raise AssertionError("Captured potential version does not match potential path.")
    return version


def _snapshot_needed(version: PotentialFileVersion | None) -> bool:
    return version is None or not version.available


@dataclass(frozen=True)
class StructureRecord:
    """Identity of one user-visible physical structure."""

    id: int
    formula: str


@dataclass(frozen=True)
class CalculationStateRecord:
    """One calculation state without retaining a live ``Atoms`` object.

    A usable POTFIL version is sufficient structure provenance and is preferred.
    ``structure_snapshot`` is populated only when no usable POTFIL existed when
    the state was created.
    """

    id: int
    structure_id: int
    parent_id: int | None
    branch_id: int
    potential_path: str | None
    potential_version: PotentialFileVersion | None
    structure_snapshot: StructureSnapshot | None = None
    empty_spheres: EmptySpheresState | None = None
    produced_by_result_id: int | None = None
    potential_source_result_id: int | None = None


@dataclass(frozen=True)
class ResultRecord:
    """Immutable lightweight provenance captured for one completed operation."""

    id: int
    result: Any
    task_name: str
    structure_id: int | None
    input_state_id: int | None
    output_state_id: int | None
    input_parameters: Any | None
    directory: str | None
    result_files: Mapping[str, FileVersion]
    persistent_ref: str | None = None
    restart_scf: bool = False
    output_path: Path | None = None
    output_version: FileVersion | None = None
    potential_path: Path | None = None
    imported: bool = False


@dataclass(frozen=True)
class _PreparedState:
    """A fully materialized state transition that has not mutated the store yet."""

    state: CalculationStateRecord
    structure: StructureRecord | None = None
    creates_branch: bool = False


class ResultStore:
    """Own exact provenance independently of its user-facing tree projection."""

    def __init__(self) -> None:
        self._next_structure_id = 1
        self._next_state_id = 1
        self._next_result_id = 1
        self._next_branch_id = 1
        self._structures: dict[int, StructureRecord] = {}
        self._states: dict[int, CalculationStateRecord] = {}
        self._results: dict[int, ResultRecord] = {}
        self._state_children: dict[int, list[int]] = {}
        self._result_ids_by_state: dict[int, list[int]] = {}
        self._unstructured_result_ids: list[int] = []
        self._structure_branches: dict[int, list[int]] = {}
        self._imported_result_ids_by_directory: dict[str | None, list[int]] = {}

    def __len__(self) -> int:
        return len(self._results)

    def __bool__(self) -> bool:
        return bool(self._results)

    def __iter__(self) -> Iterator[ResultRecord]:
        return iter(self.results)

    def __getitem__(self, index):
        return self.results[index]

    @property
    def results(self) -> tuple[ResultRecord, ...]:
        """Return results newest first."""
        return tuple(
            self._results[result_id]
            for result_id in sorted(self._results, reverse=True)
        )

    @property
    def structures(self) -> tuple[StructureRecord, ...]:
        return tuple(self._structures.values())

    @property
    def import_directories(self) -> tuple[str | None, ...]:
        """Return imported-result directories in first-import order."""
        return tuple(self._imported_result_ids_by_directory)

    @property
    def unstructured_results(self) -> tuple[ResultRecord, ...]:
        return tuple(
            self._results[result_id]
            for result_id in self._unstructured_result_ids
        )

    def imported_results(self, directory: str | None) -> tuple[ResultRecord, ...]:
        """Return results explicitly imported from one source directory."""
        return tuple(
            self._results[result_id]
            for result_id in self._imported_result_ids_by_directory.get(directory, ())
        )

    def structure_results(self, structure_id: int) -> tuple[ResultRecord, ...]:
        """Return native results for one structure in recording order."""
        return tuple(
            record
            for record in sorted(self._results.values(), key=lambda item: item.id)
            if record.structure_id == structure_id and not record.imported
        )

    def structure(self, structure_id: int) -> StructureRecord:
        return self._structures[structure_id]

    def state(self, state_id: int) -> CalculationStateRecord:
        return self._states[state_id]

    def result(self, result_id: int) -> ResultRecord:
        return self._results[result_id]

    def result_for_external_source(
        self,
        output_path: str | Path | None,
        *,
        persistent_ref: str | None = None,
    ) -> ResultRecord | None:
        """Return an already recorded result for the same persistent/source version.

        A persistent run id is the strongest identity. Otherwise the exact
        captured contents of the source output file identify an external result.
        Re-importing an unchanged file therefore reuses its record, while a file
        that was overwritten with new contents may legitimately create a new one.
        """
        if persistent_ref is not None:
            for record in self.results:
                if record.persistent_ref == persistent_ref:
                    return record

        if output_path is None:
            return None
        path = Path(output_path).expanduser().resolve()
        for record in self.results:
            version = record.output_version
            if version is None or version.path != path:
                continue
            if version.state() is FileState.CURRENT:
                return record
        return None

    def current_value_for_result_file(self, result_file: FileVersion) -> Any | None:
        """Return the known result value that owns the file currently at this path."""
        for record in self.results:
            for name, candidate in record.result_files.items():
                if candidate.path != result_file.path:
                    continue
                if candidate.state() is not FileState.CURRENT:
                    continue
                try:
                    values = record.result.output_values
                    for key, value in values.items():
                        if str(key) == name:
                            return value
                except Exception:  # noqa: BLE001 - optional presentation metadata
                    continue
        return None

    def state_for_result(self, record: ResultRecord) -> CalculationStateRecord | None:
        state_id = record.output_state_id or record.input_state_id
        return self._states.get(state_id) if state_id is not None else None

    def state_for_potential_version(
        self,
        version: PotentialFileVersion,
        *,
        structure_id: int | None = None,
    ) -> CalculationStateRecord | None:
        """Return the newest state known to represent this exact POTFIL version."""
        for state_id in sorted(self._states, reverse=True):
            state = self._states[state_id]
            if structure_id is not None and state.structure_id != structure_id:
                continue
            if state.potential_version == version:
                return state
        return None

    def potential_source_result(self, state_id: int | None) -> ResultRecord | None:
        if state_id is None:
            return None
        source_id = self.state(state_id).potential_source_result_id
        return self._results.get(source_id) if source_id is not None else None

    def branch_id_for_result(self, record: ResultRecord) -> int | None:
        state = self.state_for_result(record)
        return state.branch_id if state is not None else None

    def branch_ids(self, structure_id: int) -> tuple[int, ...]:
        """Return branches which currently contain at least one native result."""
        used = {
            branch_id
            for record in self._results.values()
            if record.structure_id == structure_id and not record.imported
            for branch_id in (self.branch_id_for_result(record),)
            if branch_id is not None
        }
        return tuple(
            branch_id
            for branch_id in self._structure_branches.get(structure_id, ())
            if branch_id in used
        )

    def branch_number(self, structure_id: int, branch_id: int) -> int:
        return self._structure_branches[structure_id].index(branch_id) + 1

    def results_in_branch(
        self, structure_id: int, branch_id: int
    ) -> tuple[ResultRecord, ...]:
        """Return one branch in calculation order."""
        return tuple(
            sorted(
                (
                    record
                    for record in self._results.values()
                    if record.structure_id == structure_id
                    and not record.imported
                    and self.branch_id_for_result(record) == branch_id
                ),
                key=lambda record: record.id,
            )
        )

    def results_for_state(self, state_id: int) -> tuple[ResultRecord, ...]:
        return tuple(
            self._results[result_id]
            for result_id in self._result_ids_by_state.get(state_id, ())
        )

    def latest_result_for_state(self, state_id: int | None) -> ResultRecord | None:
        if state_id is None:
            return None
        result_ids = self._result_ids_by_state.get(state_id, ())
        if not result_ids:
            return None
        return self._results[result_ids[-1]]

    def _prepare_structure_state(
        self,
        atoms: Any,
        *,
        potential_path: str | None,
        potential_version: PotentialFileVersion | None = None,
        empty_spheres: EmptySpheresState | None = None,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None = None,
    ) -> _PreparedState:
        resolved_version = _resolve_potential_version(potential_path, potential_version)
        formula = structure_formula(atoms) or type(atoms).__name__
        snapshot = (
            StructureSnapshot.capture(atoms)
            if _snapshot_needed(resolved_version)
            else None
        )
        source_result_id = (
            potential_source_result_id
            if resolved_version is not None and resolved_version.available
            else None
        )
        structure = StructureRecord(self._next_structure_id, formula)
        state = CalculationStateRecord(
            id=self._next_state_id,
            structure_id=structure.id,
            parent_id=None,
            branch_id=self._next_branch_id,
            potential_path=potential_path,
            potential_version=resolved_version,
            structure_snapshot=snapshot,
            empty_spheres=empty_spheres,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=source_result_id,
        )
        return _PreparedState(state=state, structure=structure, creates_branch=True)

    def _prepare_child_state(
        self,
        parent_id: int,
        *,
        potential_path: str | None | object = _KEEP_POTENTIAL,
        potential_version: PotentialFileVersion | None = None,
        structure_snapshot: StructureSnapshot | None | object = _KEEP_STRUCTURE,
        empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None | object = _KEEP_POTENTIAL_SOURCE,
        new_branch: bool = False,
    ) -> _PreparedState:
        parent = self.state(parent_id)
        reuses_potential = potential_path is _KEEP_POTENTIAL
        if reuses_potential:
            if potential_version is not None:
                raise AssertionError(
                    "An explicit potential version requires an explicit potential path."
                )
            resolved_path = parent.potential_path
            resolved_version = parent.potential_version
        else:
            resolved_path = potential_path
            resolved_version = _resolve_potential_version(
                resolved_path,
                potential_version,
            )
        resolved_source = (
            parent.potential_source_result_id
            if potential_source_result_id is _KEEP_POTENTIAL_SOURCE and reuses_potential
            else None
            if potential_source_result_id is _KEEP_POTENTIAL_SOURCE
            else potential_source_result_id
        )
        if resolved_version is None or not resolved_version.available:
            resolved_source = None

        if _snapshot_needed(resolved_version):
            resolved_snapshot = (
                parent.structure_snapshot
                if structure_snapshot is _KEEP_STRUCTURE
                else structure_snapshot
            )
            if resolved_snapshot is None:
                raise ValueError(
                    "A state without a usable potential requires a structure snapshot."
                )
        else:
            resolved_snapshot = None

        resolved_empty_spheres = (
            parent.empty_spheres
            if empty_spheres is _KEEP_EMPTY_SPHERES
            else empty_spheres
        )
        same_branch_child_exists = any(
            self.state(child_id).branch_id == parent.branch_id
            for child_id in self._state_children.get(parent_id, ())
        )
        creates_branch = new_branch or same_branch_child_exists
        branch_id = self._next_branch_id if creates_branch else parent.branch_id
        state = CalculationStateRecord(
            id=self._next_state_id,
            structure_id=parent.structure_id,
            parent_id=parent.id,
            branch_id=branch_id,
            potential_path=resolved_path,
            potential_version=resolved_version,
            structure_snapshot=resolved_snapshot,
            empty_spheres=resolved_empty_spheres,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=resolved_source,
        )
        return _PreparedState(state=state, creates_branch=creates_branch)

    def _validate_prepared_state(self, prepared: _PreparedState) -> None:
        state = prepared.state
        if state.id != self._next_state_id:
            raise AssertionError(
                "Prepared state no longer matches the store state counter."
            )
        if prepared.structure is not None:
            if prepared.structure.id != self._next_structure_id:
                raise AssertionError(
                    "Prepared structure no longer matches the store structure counter."
                )
            if state.structure_id != prepared.structure.id:
                raise AssertionError("Prepared state belongs to the wrong structure.")
        elif state.structure_id not in self._structures:
            raise AssertionError("Prepared state belongs to an unknown structure.")
        if prepared.creates_branch and state.branch_id != self._next_branch_id:
            raise AssertionError(
                "Prepared state no longer matches the store branch counter."
            )

    def _commit_prepared_state(self, prepared: _PreparedState) -> None:
        self._validate_prepared_state(prepared)
        state = prepared.state
        structure = prepared.structure
        if structure is not None:
            self._structures[structure.id] = structure
            self._next_structure_id += 1
        if prepared.creates_branch:
            self._structure_branches.setdefault(state.structure_id, []).append(
                state.branch_id
            )
            self._next_branch_id += 1
        self._states[state.id] = state
        self._next_state_id += 1
        if state.parent_id is not None:
            self._state_children.setdefault(state.parent_id, []).append(state.id)

    def new_structure_state(
        self,
        atoms: Any,
        *,
        potential_path: str | None,
        potential_version: PotentialFileVersion | None = None,
        empty_spheres: EmptySpheresState | None = None,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None = None,
    ) -> tuple[int, int]:
        prepared = self._prepare_structure_state(
            atoms,
            potential_path=potential_path,
            potential_version=potential_version,
            empty_spheres=empty_spheres,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=potential_source_result_id,
        )
        self._commit_prepared_state(prepared)
        assert prepared.structure is not None
        return prepared.structure.id, prepared.state.id

    def new_child_state(
        self,
        parent_id: int,
        *,
        potential_path: str | None | object = _KEEP_POTENTIAL,
        potential_version: PotentialFileVersion | None = None,
        structure_snapshot: StructureSnapshot | None | object = _KEEP_STRUCTURE,
        empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        produced_by_result_id: int | None = None,
        potential_source_result_id: int | None | object = _KEEP_POTENTIAL_SOURCE,
        new_branch: bool = False,
    ) -> int:
        prepared = self._prepare_child_state(
            parent_id,
            potential_path=potential_path,
            potential_version=potential_version,
            structure_snapshot=structure_snapshot,
            empty_spheres=empty_spheres,
            produced_by_result_id=produced_by_result_id,
            potential_source_result_id=potential_source_result_id,
            new_branch=new_branch,
        )
        self._commit_prepared_state(prepared)
        return prepared.state.id

    def _commit_result(
        self,
        record: ResultRecord,
        *,
        prepared_state: _PreparedState | None = None,
    ) -> None:
        if record.id != self._next_result_id:
            raise AssertionError(
                "Prepared result no longer matches the store result counter."
            )
        if prepared_state is not None:
            self._validate_prepared_state(prepared_state)
            if prepared_state.state.id not in (
                record.input_state_id,
                record.output_state_id,
            ):
                raise AssertionError(
                    "Prepared result does not reference its prepared state."
                )

        if prepared_state is not None:
            self._commit_prepared_state(prepared_state)
        self._results[record.id] = record
        self._next_result_id += 1

        state_id = record.output_state_id or record.input_state_id
        if record.imported:
            imported_ids = self._imported_result_ids_by_directory.setdefault(
                record.directory, []
            )
            imported_ids.append(record.id)
        elif state_id is None:
            self._unstructured_result_ids.append(record.id)
        else:
            self._result_ids_by_state.setdefault(state_id, []).append(record.id)
        if record.imported and state_id is not None:
            self._result_ids_by_state.setdefault(state_id, []).append(record.id)

    def _prepare_result_record(
        self,
        result: ResultCapabilities,
        *,
        structure_id: int | None,
        input_state_id: int | None,
        output_state_id: int | None,
        input_parameters: Any | None,
        directory: str | None,
        persistent_ref: str | None,
        restart_scf: bool,
        output_path: Path | None,
        potential_path: Path | None,
        imported: bool,
    ) -> ResultRecord:
        """Snapshot one result record completely before anything is committed."""
        return ResultRecord(
            id=self._next_result_id,
            result=result,
            task_name=_task_name(result),
            structure_id=structure_id,
            input_state_id=input_state_id,
            output_state_id=output_state_id,
            input_parameters=_snapshot_input_parameters(input_parameters),
            directory=directory,
            result_files=capture_result_files(result),
            persistent_ref=persistent_ref,
            restart_scf=restart_scf,
            output_path=output_path,
            output_version=(
                FileVersion.capture(output_path) if output_path is not None else None
            ),
            potential_path=potential_path,
            imported=imported,
        )

    def add_result(
        self,
        result: ResultCapabilities,
        *,
        structure_id: int | None,
        input_state_id: int | None,
        input_parameters: Any | None,
        directory: str | None,
        persistent_ref: str | None = None,
        restart_scf: bool = False,
        output_path: Path | None = None,
        potential_path: Path | None = None,
        output_atoms: Any | None = None,
        output_potential_path: str | None = None,
        output_empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
    ) -> ResultRecord:
        """Record one native operation result and its optional state transition."""
        return self._add_result(
            result,
            structure_id=structure_id,
            input_state_id=input_state_id,
            input_parameters=input_parameters,
            directory=directory,
            persistent_ref=persistent_ref,
            restart_scf=restart_scf,
            output_path=output_path,
            potential_path=potential_path,
            output_atoms=output_atoms,
            output_potential_path=output_potential_path,
            output_empty_spheres=output_empty_spheres,
            imported=False,
        )

    def _add_result(
        self,
        result: ResultCapabilities,
        *,
        structure_id: int | None,
        input_state_id: int | None,
        input_parameters: Any | None,
        directory: str | None,
        persistent_ref: str | None = None,
        restart_scf: bool = False,
        output_path: Path | None = None,
        potential_path: Path | None = None,
        output_atoms: Any | None = None,
        output_potential_path: str | None = None,
        output_empty_spheres: EmptySpheresState | None | object = _KEEP_EMPTY_SPHERES,
        imported: bool,
    ) -> ResultRecord:
        if (structure_id is None) != (input_state_id is None):
            raise ValueError(
                "Result provenance requires structure_id and input_state_id together."
            )

        input_state = None
        if input_state_id is not None:
            input_state = self.state(input_state_id)
            if input_state.structure_id != structure_id:
                raise AssertionError(
                    "Result provenance mismatch: input state "
                    f"{input_state_id} belongs to structure "
                    f"{input_state.structure_id}, not {structure_id}."
                )

        result_id = self._next_result_id
        potential_source_result_id = (
            result_id
            if result.produces_potential and output_potential_path is not None
            else None
        )

        prepared_state = None
        output_state_id = None
        produces_state = (
            result.produces_potential and output_atoms is not None
        ) or output_empty_spheres is not _KEEP_EMPTY_SPHERES
        if produces_state:
            if structure_id is None:
                root_empty_spheres = (
                    None
                    if output_empty_spheres is _KEEP_EMPTY_SPHERES
                    else output_empty_spheres
                )
                if output_atoms is None:
                    raise ValueError("A new structure state requires atoms.")
                prepared_state = self._prepare_structure_state(
                    output_atoms,
                    potential_path=output_potential_path,
                    empty_spheres=root_empty_spheres,
                    produced_by_result_id=result_id,
                    potential_source_result_id=potential_source_result_id,
                )
                assert prepared_state.structure is not None
                structure_id = prepared_state.structure.id
            else:
                if input_state is None:
                    raise ValueError("A derived result requires an input state.")
                child_potential: str | None | object = output_potential_path
                if (
                    output_atoms is None
                    and output_potential_path == input_state.potential_path
                ):
                    child_potential = _KEEP_POTENTIAL
                child_snapshot: StructureSnapshot | None | object = _KEEP_STRUCTURE
                if output_atoms is not None:
                    child_snapshot = StructureSnapshot.capture(output_atoms)
                prepared_state = self._prepare_child_state(
                    input_state_id,
                    potential_path=child_potential,
                    structure_snapshot=child_snapshot,
                    empty_spheres=output_empty_spheres,
                    produced_by_result_id=result_id,
                    potential_source_result_id=potential_source_result_id,
                )
            output_state_id = prepared_state.state.id

        record = self._prepare_result_record(
            result,
            structure_id=structure_id,
            input_state_id=input_state_id,
            output_state_id=output_state_id,
            input_parameters=input_parameters,
            directory=directory,
            persistent_ref=persistent_ref,
            restart_scf=restart_scf,
            output_path=output_path,
            potential_path=potential_path,
            imported=imported,
        )
        self._commit_result(record, prepared_state=prepared_state)
        return record

    def add_external_result(
        self,
        result: ResultCapabilities,
        *,
        atoms: Any | None,
        input_parameters: Any | None,
        directory: str | None,
        output_path: Path | None,
        potential_path: Path | None,
        persistent_ref: str | None = None,
    ) -> ResultRecord:
        existing = self.result_for_external_source(
            output_path,
            persistent_ref=persistent_ref,
        )
        if existing is not None:
            return existing

        if atoms is None:
            return self._add_result(
                result,
                structure_id=None,
                input_state_id=None,
                input_parameters=input_parameters,
                directory=directory,
                persistent_ref=persistent_ref,
                output_path=output_path,
                potential_path=potential_path,
                imported=True,
            )

        if result.produces_potential:
            return self._add_result(
                result,
                structure_id=None,
                input_state_id=None,
                input_parameters=input_parameters,
                directory=directory,
                persistent_ref=persistent_ref,
                output_path=output_path,
                potential_path=potential_path,
                output_atoms=atoms,
                output_potential_path=(str(potential_path) if potential_path else None),
                imported=True,
            )

        prepared_state = self._prepare_structure_state(
            atoms,
            potential_path=(str(potential_path) if potential_path else None),
        )
        assert prepared_state.structure is not None
        record = self._prepare_result_record(
            result,
            structure_id=prepared_state.structure.id,
            input_state_id=prepared_state.state.id,
            output_state_id=None,
            input_parameters=input_parameters,
            directory=directory,
            persistent_ref=persistent_ref,
            restart_scf=False,
            output_path=output_path,
            potential_path=potential_path,
            imported=True,
        )
        self._commit_result(record, prepared_state=prepared_state)
        return record

    def branch_path(self, record: ResultRecord) -> tuple[int, ...]:
        if record.structure_id is None:
            return ()
        branch_id = self.branch_id_for_result(record)
        branches = self.branch_ids(record.structure_id)
        if branch_id is None or len(branches) <= 1:
            return ()
        return (self.branch_number(record.structure_id, branch_id),)
