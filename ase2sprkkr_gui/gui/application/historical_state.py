"""Resolve reusable historical calculation state without mutating a workspace."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

from ase2sprkkr_gui.gui.application.potential_version import PotentialFileVersion
from ase2sprkkr_gui.gui.application.result_loading import (
    load_potential_version,
    require_potential_version_current,
)
from ase2sprkkr_gui.gui.application.result_store import CalculationStateRecord, ResultStore


@dataclass(frozen=True)
class ExistingHistoricalState:
    """A historical input already represented by a recorded calculation state."""

    atoms: Any
    state: CalculationStateRecord


@dataclass(frozen=True)
class NewHistoricalPotential:
    """A user-approved POTFIL version not yet represented in the result lineage."""

    atoms: Any
    parent_state: CalculationStateRecord
    potential_version: PotentialFileVersion


@dataclass(frozen=True)
class HistoricalStateAlreadyActive:
    """The approved historical calculation input is already the active state."""


HistoricalStateResolution = Union[
    ExistingHistoricalState,
    NewHistoricalPotential,
    HistoricalStateAlreadyActive,
]


def _state_for_result(store: ResultStore, result_id: int) -> CalculationStateRecord:
    record = store.result(result_id)
    state_id = record.output_state_id or record.input_state_id
    if state_id is None:
        raise ValueError("The selected result has no reusable calculation input.")
    return store.state(state_id)


def _restore_state_atoms(state: CalculationStateRecord) -> Any:
    version = state.potential_version
    if version is not None and version.available:
        return load_potential_version(version)
    if state.structure_snapshot is not None:
        return state.structure_snapshot.to_atoms()
    raise ValueError("The selected result no longer has a reusable calculation input.")


def resolve_historical_state(
    store: ResultStore,
    result_id: int,
    *,
    active_state_id: int | None = None,
    expected_potential: PotentialFileVersion | None = None,
) -> HistoricalStateResolution:
    """Resolve the physical input for a historical result without mutating ``store``.

    When ``expected_potential`` is supplied it represents an explicit user-approved
    version of the result's POTFIL path. The function loads exactly that version.
    If the version is not represented by an existing state, the returned resolution
    asks the controller to create a child of the historical state; doing so remains
    part of the controller's atomic mutation boundary.
    """
    state = _state_for_result(store, result_id)
    if expected_potential is None:
        return ExistingHistoricalState(
            atoms=_restore_state_atoms(state),
            state=state,
        )

    if state.potential_path is None:
        raise ValueError("The selected result has no reusable potential.")
    state_path = Path(state.potential_path).expanduser().resolve()
    if expected_potential.path != state_path:
        raise ValueError("The approved potential does not belong to this result.")

    if active_state_id is not None:
        active = store.state(active_state_id)
        if (
            active.structure_id == state.structure_id
            and active.potential_version == expected_potential
        ):
            require_potential_version_current(expected_potential)
            return HistoricalStateAlreadyActive()

    if state.potential_version == expected_potential:
        target_state = state
    else:
        target_state = store.state_for_potential_version(
            expected_potential,
            structure_id=state.structure_id,
        )

    atoms = load_potential_version(expected_potential)
    if target_state is not None:
        return ExistingHistoricalState(atoms=atoms, state=target_state)
    return NewHistoricalPotential(
        atoms=atoms,
        parent_state=state,
        potential_version=expected_potential,
    )
