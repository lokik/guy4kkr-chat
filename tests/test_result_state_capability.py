from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.result_store import ResultStore
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationRequest,
    WorkspaceController,
)


def _result(*, produces_potential: bool):
    return SimpleNamespace(
        task_name="scf" if produces_potential else "dos",
        produces_potential=produces_potential,
        output_values={},
    )


def test_result_store_ignores_output_atoms_for_non_potential_result():
    store = ResultStore()
    structure_id, state_id = store.new_structure_state(
        Atoms("Fe"),
        potential_path=None,
    )

    record = store.add_result(
        _result(produces_potential=False),
        structure_id=structure_id,
        input_state_id=state_id,
        input_parameters=None,
        directory=None,
        output_atoms=Atoms("Cu"),
        output_potential_path="unexpected.pot",
    )

    assert record.output_state_id is None
    assert store.state_for_result(record).id == state_id
    assert store.results_for_state(state_id) == (record,)


def test_controller_does_not_fast_forward_non_potential_result_with_atoms():
    original_atoms = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=original_atoms))
    request = CalculationRequest(
        atoms=original_atoms,
        input_parameters=object(),
        directory="run",
        generation=controller.generation,
        structure_id=controller.structure_id,
        state_id=controller.state_id,
    )
    original_state_id = controller.state_id

    unexpected_potential = Path("unexpected.pot")
    adoption = controller.adopt_calculation_result(
        LoadedResult(
            result=_result(produces_potential=False),
            output_path=None,
            potential_path=unexpected_potential,
            atoms=Atoms("Cu"),
            potential_error=None,
            directory="run",
        ),
        request=request,
    )

    assert adoption.record.output_state_id is None
    assert adoption.record.potential_path == unexpected_potential
    assert not adoption.workspace_updated
    assert controller.atoms is original_atoms
    assert controller.state_id == original_state_id


def test_controller_fast_forwards_potential_producing_result_with_atoms():
    original_atoms = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=original_atoms))
    request = CalculationRequest(
        atoms=original_atoms,
        input_parameters=object(),
        directory="run",
        generation=controller.generation,
        structure_id=controller.structure_id,
        state_id=controller.state_id,
    )
    output_atoms = Atoms("Cu")

    adoption = controller.adopt_calculation_result(
        LoadedResult(
            result=_result(produces_potential=True),
            output_path=None,
            potential_path=None,
            atoms=output_atoms,
            potential_error=None,
            directory="run",
        ),
        request=request,
    )

    assert adoption.record.output_state_id is not None
    assert adoption.workspace_updated
    assert controller.atoms is output_atoms
    assert controller.state_id == adoption.record.output_state_id
