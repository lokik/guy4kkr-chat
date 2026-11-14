from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from ase import Atoms
from ase2sprkkr import SPRKKRAtoms

from ase2sprkkr_gui.gui.application.result_loading import LoadedResult
from ase2sprkkr_gui.gui.application.result_presentation import present_result_record
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return self


def _atoms_with_potential(marker: str, *, x: float = 0.0):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", positions=[[x, 0.0, 0.0]], cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms._potential = SimpleNamespace(atoms=atoms, marker=marker)
    return atoms


def _loaded_scf(atoms, potential_path: str | Path | None = None):
    return LoadedResult(
        result=SimpleNamespace(
            task_name="scf",
            produces_potential=True,
            output_values={},
        ),
        output_path=None,
        potential_path=(Path(potential_path) if potential_path is not None else None),
        atoms=atoms,
        potential_error=None,
        directory=None,
    )


def test_use_result_state_never_substitutes_current_atoms_for_historical_state(tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=_atoms_with_potential("root"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    current_request = controller.create_calculation_request()
    historical_request = controller.create_calculation_request()

    current_atoms = _atoms_with_potential("current", x=0.1)
    current = controller.adopt_calculation_result(
        _loaded_scf(current_atoms),
        request=current_request,
    )
    assert current.workspace_updated

    historical_atoms = _atoms_with_potential("historical", x=0.2)
    historical = controller.adopt_calculation_result(
        _loaded_scf(historical_atoms),
        request=historical_request,
    )
    assert not historical.workspace_updated
    assert current.record.structure_id == historical.record.structure_id
    assert controller.atoms is current_atoms

    controller.use_result_state(historical.record.id)

    assert controller.state_id == historical.record.output_state_id
    assert controller.atoms is not current_atoms
    assert controller.atoms is not historical_atoms
    np.testing.assert_allclose(controller.atoms.positions, historical_atoms.positions)
    assert not np.array_equal(controller.atoms.positions, current_atoms.positions)


def test_restore_presentation_never_silently_treats_overwritten_potential_as_exact(tmp_path):
    historical_path = tmp_path / "historical.pot"
    current_path = tmp_path / "current.pot"
    historical_path.write_text("historical file", encoding="utf-8")
    current_path.write_text("current file", encoding="utf-8")

    controller = WorkspaceController(
        WorkspaceState(
            atoms=_atoms_with_potential("root"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )
    historical_request = controller.create_calculation_request()
    historical = controller.adopt_calculation_result(
        _loaded_scf(_atoms_with_potential("historical"), historical_path),
        request=historical_request,
    )
    assert historical.workspace_updated

    current_request = controller.create_calculation_request()
    current = controller.adopt_calculation_result(
        _loaded_scf(_atoms_with_potential("current"), current_path),
        request=current_request,
    )
    assert current.workspace_updated

    before = present_result_record(
        controller.result_store,
        historical.record,
        current_structure_id=controller.structure_id,
        current_state_id=controller.state_id,
    )
    assert before.actions.use_state is not None
    assert before.actions.use_state.label == "Use this potential"

    historical_path.write_text("replacement file", encoding="utf-8")
    after = present_result_record(
        controller.result_store,
        historical.record,
        current_structure_id=controller.structure_id,
        current_state_id=controller.state_id,
    )

    assert after.actions.use_state is not None
    assert after.actions.use_state.label == "Continue with current version of this potential"
    assert after.actions.use_state.expected_potential is not None
    assert after.actions.use_state.expected_potential != (
        controller.result_store.state_for_result(historical.record).potential_version
    )
