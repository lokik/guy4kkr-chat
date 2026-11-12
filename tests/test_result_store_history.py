from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ase import Atoms

from guy4ase.gui.application.operation_results import EmptySpheresResult
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


class _Parameters:
    def __init__(self, value=0):
        self.value = value

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(self.value)


def _result(task_name: str):
    return SimpleNamespace(
        task_name=task_name,
        produces_potential=task_name.lower() == "scf",
    )


def _loaded(
    result,
    *,
    atoms=None,
    potential_path: str | Path | None = None,
    input_parameters=None,
):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=Path(potential_path) if potential_path is not None else None,
        atoms=atoms,
        potential_error=None,
        directory=None,
        input_parameters=input_parameters,
    )


def _controller(tmp_path, atoms=None, potential_path=None):
    return WorkspaceController(
        WorkspaceState(
            atoms=atoms or Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
            potential_path=potential_path,
        )
    )


def _results(controller: WorkspaceController):
    return tuple(record.result for record in controller.result_store.results)


def test_result_history_is_independent_and_not_bounded_to_ten(tmp_path):
    controller = _controller(tmp_path)
    results = [_result("dos") for _ in range(12)]

    for result in results:
        request = controller.create_calculation_request()
        adoption = controller.adopt_calculation_result(_loaded(result), request=request)
        assert not adoption.workspace_updated

    assert _results(controller) == tuple(reversed(results))
    assert len(controller.result_store.results) == 12


def test_input_and_structure_changes_do_not_delete_results(tmp_path):
    controller = _controller(tmp_path)
    first_structure_id = controller.structure_id
    result = _result("dos")
    request = controller.create_calculation_request()
    controller.adopt_calculation_result(_loaded(result), request=request)

    controller.replace_input_parameters(_Parameters(2))
    controller.replace_structure(Atoms("Ni"))

    assert _results(controller) == (result,)
    assert controller.result_store.results[0].structure_id == first_structure_id
    assert controller.structure_id != first_structure_id


def test_external_result_is_recorded_without_replacing_workspace(tmp_path):
    controller = _controller(tmp_path, atoms=Atoms("Cu"), potential_path="current.pot")
    original_atoms = controller.atoms
    original_state_id = controller.state_id
    external_atoms = Atoms("Fe")
    external = _result("scf")

    adoption = controller.adopt_external_result(
        _loaded(
            external,
            atoms=external_atoms,
            potential_path=tmp_path / "external.pot_new",
            input_parameters=_Parameters(7),
        )
    )

    assert not adoption.workspace_updated
    assert controller.atoms is original_atoms
    assert controller.state_id == original_state_id
    record = controller.result_store.results[0]
    assert record.result is external
    assert record.output_state_id is not None
    assert record.imported


def test_active_scf_advances_workspace_but_late_sibling_stays_in_old_branch(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()

    result_b = _result("scf")
    atoms_b = Atoms("Fe")
    adoption_b = controller.adopt_calculation_result(
        _loaded(result_b, atoms=atoms_b, potential_path=tmp_path / "pb.pot_new"),
        request=request_b,
    )
    assert adoption_b.workspace_updated
    state_b = controller.state_id

    request_c = controller.create_calculation_request()
    result_c = _result("scf")
    atoms_c = Atoms("Fe")
    adoption_c = controller.adopt_calculation_result(
        _loaded(result_c, atoms=atoms_c, potential_path=tmp_path / "pc.pot_new"),
        request=request_c,
    )
    assert adoption_c.workspace_updated
    state_c = controller.state_id
    assert state_c != state_b
    assert controller.result is result_c

    result_a = _result("scf")
    atoms_a = Atoms("Fe")
    adoption_a = controller.adopt_calculation_result(
        _loaded(result_a, atoms=atoms_a, potential_path=tmp_path / "pa.pot_new"),
        request=request_a,
    )

    assert not adoption_a.workspace_updated
    assert controller.state_id == state_c
    assert controller.atoms is atoms_c
    assert controller.potential_path == str(tmp_path / "pc.pot_new")
    assert controller.result is result_c
    assert controller.result_store.branch_id_for_result(adoption_b.record) == (
        controller.result_store.branch_id_for_result(adoption_c.record)
    )
    assert controller.result_store.branch_id_for_result(adoption_a.record) != (
        controller.result_store.branch_id_for_result(adoption_c.record)
    )


def test_use_for_new_calculation_is_a_new_branch_and_write_barrier(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    old_request = controller.create_calculation_request()
    old_state = controller.state_id
    old_branch = controller.result_store.state(old_state).branch_id

    controller.use_for_new_calculation(
        expected_structure_generation=controller.structure_generation
    )
    restart_state = controller.state_id
    restart_branch = controller.result_store.state(restart_state).branch_id
    assert restart_branch != old_branch
    assert controller.potential_path == "p0.pot"

    late_result = _result("scf")
    late = controller.adopt_calculation_result(
        _loaded(late_result, atoms=Atoms("Fe"), potential_path=tmp_path / "old.pot_new"),
        request=old_request,
    )

    assert not late.workspace_updated
    assert controller.state_id == restart_state
    assert controller.restarted
    assert controller.potential_path == "p0.pot"
    assert controller.result_store.branch_id_for_result(late.record) == old_branch

    new_request = controller.create_calculation_request()
    new_result = _result("scf")
    new = controller.adopt_calculation_result(
        _loaded(new_result, atoms=Atoms("Fe"), potential_path=tmp_path / "new.pot_new"),
        request=new_request,
    )
    assert new.workspace_updated
    assert controller.result_store.branch_id_for_result(new.record) == restart_branch


def test_use_result_state_explicitly_switches_to_historical_potential(tmp_path):
    controller = _controller(tmp_path, potential_path="p0.pot")
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()
    result_a = _result("scf")
    result_b = _result("scf")

    a = controller.adopt_calculation_result(
        _loaded(result_a, atoms=Atoms("Fe"), potential_path=tmp_path / "pa.pot_new"),
        request=request_a,
    )
    assert a.workspace_updated
    b = controller.adopt_calculation_result(
        _loaded(result_b, atoms=Atoms("Fe"), potential_path=tmp_path / "pb.pot_new"),
        request=request_b,
    )
    assert not b.workspace_updated
    assert controller.result is result_a

    controller.use_result_state(b.record.id)

    assert controller.state_id == b.record.output_state_id
    assert controller.potential_path == str(tmp_path / "pb.pot_new")
    assert controller.result is result_b


def test_empty_spheres_is_result_transition_within_same_structure(tmp_path):
    controller = _controller(tmp_path, potential_path="Fe.pot")
    structure_id = controller.structure_id
    input_state_id = controller.state_id

    def add_one(atoms, _previous):
        atoms += Atoms("X")
        return atoms, 1, True

    controller.update_empty_spheres(
        add_one,
        expected_structure_generation=controller.structure_generation,
        parameters={"radius": 1.25},
    )

    record = controller.result_store.results[0]
    state = controller.result_store.state(controller.state_id)
    assert record.result == EmptySpheresResult(found=1)
    assert record.structure_id == structure_id
    assert record.input_state_id == input_state_id
    assert record.output_state_id == controller.state_id
    assert state.parent_id == input_state_id
    assert state.empty_spheres == controller.empty_spheres
    assert dict(state.empty_spheres.parameters) == {"radius": 1.25}
    assert controller.potential_path is None


def test_empty_spheres_without_structure_change_creates_restorable_state(tmp_path):
    controller = _controller(tmp_path, potential_path="Fe.pot")
    input_state_id = controller.state_id
    generation = controller.structure_generation
    atoms = controller.atoms

    controller.update_empty_spheres(
        lambda candidate, _previous: (candidate, 0, False),
        expected_structure_generation=generation,
        parameters={"method": "probe"},
    )

    record = controller.result_store.results[0]
    state = controller.result_store.state(controller.state_id)
    assert record.result == EmptySpheresResult(found=0)
    assert record.input_state_id == input_state_id
    assert record.output_state_id == controller.state_id
    assert controller.state_id != input_state_id
    assert controller.atoms is atoms
    assert state.structure_snapshot is not None
    assert controller.potential_path == "Fe.pot"
    assert state.potential_path == "Fe.pot"
    assert controller.structure_generation != generation
    assert state.empty_spheres == controller.empty_spheres
    assert dict(state.empty_spheres.parameters) == {"method": "probe"}


def test_use_result_state_restores_empty_sphere_provenance(tmp_path):
    controller = _controller(tmp_path, potential_path="Fe.pot")

    controller.update_empty_spheres(
        lambda candidate, _previous: (candidate, 0, False),
        expected_structure_generation=controller.structure_generation,
        parameters={"radius": 1.5, "grid": 24},
    )
    empty_spheres_record = controller.result_store.results[0]
    empty_spheres_state_id = controller.state_id

    controller.replace_structure(Atoms("Ni"), potential_path="Ni.pot")
    assert controller.empty_spheres is None

    controller.use_result_state(empty_spheres_record.id)

    assert controller.state_id == empty_spheres_state_id
    assert controller.potential_path == "Fe.pot"
    assert controller.empty_spheres is not None
    assert controller.empty_spheres.count == 0
    assert dict(controller.empty_spheres.parameters) == {"radius": 1.5, "grid": 24}
