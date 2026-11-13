"""Calculation failures and file-backed states must not dirty the structure."""
from __future__ import annotations

import pytest
from ase import Atoms

from guy4ase.gui.application import historical_state
from guy4ase.gui.application.execution_cancellation import RunCancellation
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.sprkkr_execution import SprkkrExecution
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


class _Parameters:
    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters()


def _controller(tmp_path):
    return WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        )
    )


def _calculation_result(atoms, potential):
    class Result:
        task_name = "SCF"
        produces_potential = True

    return LoadedResult(
        result=Result(),
        output_path=None,
        potential_path=potential,
        atoms=atoms,
        potential_error=None,
        directory=str(potential.parent),
    )


def test_failed_submission_does_not_dirty_the_original_structure(tmp_path, monkeypatch):
    controller = _controller(tmp_path)
    controller.mark_structure_saved(controller.structure_generation)
    controller.use_for_new_calculation()
    assert not controller.has_unsaved_structure
    generation = controller.structure_generation
    original = controller.atoms

    class ConflictingRun:
        def submit(self):
            raise RuntimeError("conflicting calculation")

    class Calculator:
        def create_run(self, **kwargs):
            # Even backend preparation must only mutate the request snapshot.
            kwargs["atoms"].symbols = "Cu"
            return ConflictingRun()

    execution = SprkkrExecution(controller.create_calculation_request(), RunCancellation())
    monkeypatch.setattr(execution, "_calculator", lambda: Calculator())

    with pytest.raises(RuntimeError, match="conflicting calculation"):
        execution.run()

    assert controller.atoms is original
    assert controller.atoms.get_chemical_symbols() == ["Fe"]
    assert controller.structure_generation == generation
    assert not controller.has_unsaved_structure


def test_new_calculation_branch_preserves_saved_structure(tmp_path):
    controller = _controller(tmp_path)
    controller.mark_structure_saved(controller.structure_generation)
    original = controller.atoms

    controller.use_for_new_calculation()

    assert controller.atoms is original
    assert controller.restarted
    assert not controller.has_unsaved_structure


def test_new_calculation_branch_does_not_hide_unsaved_edit(tmp_path):
    controller = _controller(tmp_path)
    controller.mark_structure_saved(controller.structure_generation)
    controller.replace_structure(Atoms("Cu"))
    assert controller.has_unsaved_structure

    controller.use_for_new_calculation()

    assert controller.has_unsaved_structure


def test_file_backed_calculation_result_is_not_an_unsaved_structure(tmp_path):
    controller = _controller(tmp_path)
    controller.mark_structure_saved(controller.structure_generation)
    request = controller.create_calculation_request()
    potential = tmp_path / "Fe.pot"
    potential.write_text("available potential", encoding="utf-8")

    adoption = controller.adopt_calculation_result(
        _calculation_result(Atoms("Fe"), potential), request=request
    )

    assert adoption.workspace_updated
    assert adoption.record is not None
    assert not controller.has_unsaved_structure

    controller.replace_structure(Atoms("Cu"))
    assert controller.has_unsaved_structure


def test_restoring_file_backed_result_is_not_an_unsaved_edit(tmp_path, monkeypatch):
    controller = _controller(tmp_path)
    request = controller.create_calculation_request()
    potential = tmp_path / "Fe.pot"
    potential.write_text("available potential", encoding="utf-8")
    adoption = controller.adopt_calculation_result(
        _calculation_result(Atoms("Fe"), potential), request=request
    )
    assert adoption.record is not None

    controller.replace_structure(Atoms("Cu"))
    assert controller.has_unsaved_structure
    monkeypatch.setattr(
        historical_state, "load_potential_version", lambda _version: Atoms("Fe")
    )

    controller.use_result_state(adoption.record.id)

    assert controller.atoms.get_chemical_symbols() == ["Fe"]
    assert not controller.has_unsaved_structure
