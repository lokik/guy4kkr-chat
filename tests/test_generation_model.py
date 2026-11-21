from dataclasses import replace
from types import SimpleNamespace

from ase import Atoms
from ase2sprkkr import InputParameters

from ase2sprkkr_gui.gui.application.potential_version import PotentialFileVersion
from ase2sprkkr_gui.gui.application.result_loading import FileBackedInput, LoadedResult
from ase2sprkkr_gui.gui.application.workspace import Generation, WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import (
    CalculationRequest,
    DocumentChange,
    WorkspaceController,
)


class _Parameters:
    def __init__(self, value=None):
        self.value = value

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(self.value)


def _result(task_name, *, produces_potential=False):
    return SimpleNamespace(
        task_name=task_name,
        produces_potential=produces_potential,
    )


def _controller(tmp_path, *, conflict_resolver=None):
    return WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters(),
            directory=str(tmp_path),
        ),
        conflict_resolver=conflict_resolver,
    )


def _loaded(result, *, atoms=None, potential_path=None, directory=None):
    return LoadedResult(
        result=result,
        output_path=None,
        potential_path=potential_path,
        atoms=atoms,
        potential_error=None,
        directory=directory,
    )


def _generations(controller):
    return (
        controller.structure_generation,
        controller.input_parameters_generation,
        controller.directory_generation,
        controller.active_project_generation,
    )


def test_generation_is_a_regular_value_type_without_integer_compatibility():
    generation = Generation(1)

    assert generation == Generation(1)
    assert hash(generation) == hash(Generation(1))
    assert {generation: "value"}[Generation(1)] == "value"
    assert generation != 1
    assert generation != (1,)


def test_workspace_generations_are_independent(tmp_path):
    controller = _controller(tmp_path)
    structure, inputs, directory, project = _generations(controller)

    controller.change_directory(str(tmp_path / "other"))
    assert _generations(controller) == (
        structure,
        inputs,
        directory.next(),
        project,
    )

    controller.set_active_project("project")
    assert _generations(controller) == (
        structure,
        inputs,
        directory.next(),
        project.next(),
    )

    controller.replace_input_parameters(_Parameters(1))
    assert _generations(controller) == (
        structure,
        inputs.next(),
        directory.next(),
        project.next(),
    )

    controller.replace_structure(Atoms("Cu"))
    assert _generations(controller) == (
        structure.next(),
        inputs.next(),
        directory.next(),
        project.next(),
    )


def test_unrelated_context_change_does_not_stale_structure_edit(tmp_path):
    controller = _controller(tmp_path)
    generation = controller.structure_generation

    controller.change_directory(str(tmp_path / "other"))
    controller.set_active_project("project")
    change = controller.apply_structure_edit(
        lambda atoms: atoms,
        expected_structure_generation=generation,
    )

    assert change is DocumentChange.APPLIED


def test_input_edit_depends_on_structure_but_not_context(tmp_path):
    controller = _controller(tmp_path)
    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation

    controller.change_directory(str(tmp_path / "other"))
    controller.set_active_project("project")
    assert (
        controller.replace_input_parameters(
            _Parameters(1),
            expected_input_parameters_generation=input_generation,
            expected_structure_generation=structure_generation,
        )
        is DocumentChange.APPLIED
    )

    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation
    controller.replace_structure(Atoms("Cu"))
    assert (
        controller.replace_input_parameters(
            _Parameters(2),
            expected_input_parameters_generation=input_generation,
            expected_structure_generation=structure_generation,
        )
        is DocumentChange.STALE
    )


def test_conflict_resolver_can_reject_without_mutating_value(tmp_path):
    conflicts = []

    def reject(items):
        conflicts.append(items)
        return False

    controller = _controller(tmp_path, conflict_resolver=reject)
    generation = controller.input_parameters_generation
    newer = _Parameters("newer")
    controller.replace_input_parameters(newer)

    change = controller.replace_input_parameters(
        _Parameters("stale"),
        expected_input_parameters_generation=generation,
    )

    assert change is DocumentChange.CANCELLED
    assert controller.input_parameters is newer
    assert len(conflicts) == 1
    assert [item.component for item in conflicts[0]] == ["input parameters"]


def test_conflict_resolver_can_force_one_atomic_commit(tmp_path):
    conflicts = []

    def accept(items):
        conflicts.append(items)
        return True

    controller = _controller(tmp_path, conflict_resolver=accept)
    generation = controller.input_parameters_generation
    controller.replace_input_parameters(_Parameters("newer"))
    before = controller.input_parameters_generation
    replacement = _Parameters("chosen")

    change = controller.replace_input_parameters(
        replacement,
        expected_input_parameters_generation=generation,
    )

    assert change is DocumentChange.APPLIED
    assert controller.input_parameters is replacement
    assert controller.input_parameters_generation == before.next()
    assert len(conflicts) == 1


def test_multi_value_conflict_is_resolved_once(tmp_path):
    conflicts = []

    def accept(items):
        conflicts.append(items)
        return True

    controller = _controller(tmp_path, conflict_resolver=accept)
    structure_generation = controller.structure_generation
    directory_generation = controller.directory_generation
    controller.replace_structure(Atoms("Cu"))
    controller.change_directory(str(tmp_path / "newer"))

    change = controller.replace_structure(
        Atoms("Ni"),
        directory=str(tmp_path / "chosen"),
        expected_structure_generation=structure_generation,
        expected_directory_generation=directory_generation,
    )

    assert change is DocumentChange.APPLIED
    assert controller.atoms.get_chemical_symbols() == ["Ni"]
    assert controller.directory == str(tmp_path / "chosen")
    assert len(conflicts) == 1
    assert {item.component for item in conflicts[0]} == {
        "structure",
        "working directory",
    }


def test_calculation_context_rejects_conflict_without_partial_changes(tmp_path):
    conflicts = []

    def reject(items):
        conflicts.append(items)
        return False

    controller = _controller(tmp_path, conflict_resolver=reject)
    directory_generation = controller.directory_generation
    project_generation = controller.active_project_generation
    controller.set_active_project("concurrent")

    change = controller.set_calculation_context(
        str(tmp_path / "new-directory"),
        "chosen",
        expected_directory_generation=directory_generation,
        expected_active_project_generation=project_generation,
    )

    assert change is DocumentChange.CANCELLED
    assert controller.directory == str(tmp_path)
    assert controller.active_project_id == "concurrent"
    assert len(conflicts) == 1
    assert [item.component for item in conflicts[0]] == ["active project"]


def test_result_publication_does_not_advance_workspace_generations(tmp_path):
    controller = _controller(tmp_path)
    generations = _generations(controller)
    request = controller.create_calculation_request()
    result = _result("DOS")

    adoption = controller.adopt_calculation_result(
        _loaded(result, directory=str(tmp_path)),
        request=request,
    )

    assert not adoption.workspace_updated
    assert _generations(controller) == generations
    assert controller.result_store.results[0].result is result


def test_parallel_non_scf_results_are_both_recorded_without_touching_workspace(tmp_path):
    controller = _controller(tmp_path)
    generations = _generations(controller)
    request_a = controller.create_calculation_request()
    request_b = controller.create_calculation_request()
    first = _result("DOS")
    second = _result("BSF")

    controller.adopt_calculation_result(_loaded(first), request=request_a)
    controller.adopt_calculation_result(_loaded(second), request=request_b)

    assert _generations(controller) == generations
    assert tuple(record.result for record in controller.result_store.results[:2]) == (
        second,
        first,
    )


def test_non_potential_result_atoms_do_not_fast_forward_structure(tmp_path):
    controller = _controller(tmp_path)
    request = controller.create_calculation_request()
    generation = controller.structure_generation

    adoption = controller.adopt_calculation_result(
        _loaded(_result("DOS"), atoms=Atoms("Cu")),
        request=request,
    )

    assert not adoption.workspace_updated
    assert controller.structure_generation == generation
    assert controller.atoms.get_chemical_symbols() == ["Fe"]


def test_structure_change_does_not_reject_completed_job_from_history(tmp_path):
    controller = _controller(tmp_path)
    request = controller.create_calculation_request()
    old_structure_id = request.structure_id
    controller.replace_structure(Atoms("Cu"))
    result = _result("DOS")

    adoption = controller.adopt_calculation_result(_loaded(result), request=request)

    assert not adoption.workspace_updated
    assert controller.result_store.results[0].result is result
    assert controller.result_store.results[0].structure_id == old_structure_id
    assert controller.atoms.get_chemical_symbols() == ["Cu"]


def test_file_backed_result_records_its_source_without_adopting_it(tmp_path):
    controller = WorkspaceController(WorkspaceState())
    parameters = InputParameters.for_task("SCF")
    source = tmp_path / "Fe.pot"
    source.write_text("original potential")
    launch = FileBackedInput(Atoms("Fe"), (PotentialFileVersion.capture(source),))
    parameters.CONTROL.POTFIL = str(source)
    request = CalculationRequest(
        Atoms("Fe"), parameters, str(tmp_path), None, None, potential=False,
    )
    loaded = _loaded(
        _result("SCF", produces_potential=True),
        atoms=Atoms("Fe"), potential_path=tmp_path / "Fe.pot_new",
    )
    output = loaded.potential_path
    output.write_text("result potential")
    output_version = PotentialFileVersion.capture(output)
    loaded = replace(loaded, file_backed_input=launch, output_potential_version=output_version)
    source.write_text("replaced before result adoption")
    output.write_text("replaced before result adoption")

    adoption = controller.adopt_calculation_result(loaded, request=request)

    assert not adoption.workspace_updated
    assert controller.atoms is None
    assert controller.input_parameters is None
    assert adoption.record.output_state_id is not None
    input_state = controller.result_store.state(adoption.record.input_state_id)
    assert input_state.potential_path == str(source)
    assert input_state.potential_version == launch.potential_version
    assert input_state.source_versions == launch.input_versions
    assert not input_state.potential_version.is_current()
    output_state = controller.result_store.state(adoption.record.output_state_id)
    assert output_state.potential_version == output_version
    assert not output_state.potential_version.is_current()


def test_historical_structure_rejects_changed_host_source(tmp_path):
    """A CLUPOT's version alone cannot authenticate its embedded host."""
    import pytest
    from ase2sprkkr_gui.gui.application.result_store import ResultStore
    from ase2sprkkr_gui.gui.application.historical_state import _restore_state_atoms
    from ase2sprkkr_gui.gui.application.result_loading import PotentialVersionChanged

    host = tmp_path / "host.pot"
    cluster = tmp_path / "cluster.pot"
    host.write_text("original host")
    cluster.write_text("original cluster")
    sources = (PotentialFileVersion.capture(host), PotentialFileVersion.capture(cluster))
    store = ResultStore()
    _, state_id = store.new_structure_state(
        Atoms("Fe"), potential_path=str(cluster),
        potential_version=sources[-1], source_versions=sources,
    )
    assert store.state(state_id).source_versions == sources

    host.write_text("changed host")
    with pytest.raises(PotentialVersionChanged, match="changed"):
        _restore_state_atoms(store.state(state_id))



def test_matching_potential_also_requires_matching_embedded_host_version(tmp_path):
    """Identical cluster bytes under different host versions are not one state."""
    from ase2sprkkr_gui.gui.application.result_store import ResultStore

    host = tmp_path / "host.pot"
    cluster = tmp_path / "cluster.pot"
    host.write_text("host version 1")
    cluster.write_text("unchanged cluster")
    host_v1 = PotentialFileVersion.capture(host)
    clu_v = PotentialFileVersion.capture(cluster)
    store = ResultStore()
    _, state1 = store.new_structure_state(
        Atoms("Fe"), potential_path=str(cluster),
        potential_version=clu_v, source_versions=(host_v1, clu_v),
    )
    host.write_text("host version 2")
    host_v2 = PotentialFileVersion.capture(host)
    _, state2 = store.new_structure_state(
        Atoms("Fe"), potential_path=str(cluster),
        potential_version=clu_v, source_versions=(host_v2, clu_v),
    )
    assert store.state(state1).source_dependencies == (host_v1,)
    assert store.state(state2).source_dependencies == (host_v2,)
    assert store.state_for_potential_version(
        clu_v, source_dependencies=(host_v1,),
    ).id == state1
    assert store.state_for_potential_version(
        clu_v, source_dependencies=(host_v2,),
    ).id == state2
    assert store.state_for_potential_version(
        clu_v, source_dependencies=(),
    ) is None


def test_external_potential_output_retains_imported_host_dependency(
    tmp_path, native_embedded_potentials,
):
    """Imported SCF output keeps a versioned host and its embedded structure."""
    import pytest
    from shutil import copyfile

    from ase2sprkkr import Potential
    from ase2sprkkr.potentials.cluster_potentials import EmbeddedPotential
    from ase2sprkkr_gui.gui.application.historical_state import _restore_state_atoms
    from ase2sprkkr_gui.gui.application.result_loading import PotentialVersionChanged

    host, cluster = native_embedded_potentials
    output = tmp_path / "cluster.pot_new"
    copyfile(cluster, output)
    host_potential = Potential.from_file(host)
    embedded_atoms = EmbeddedPotential.from_file(
        output, host=host_potential,
    ).atoms
    host_version = PotentialFileVersion.capture(host, require_digest=True)
    controller = WorkspaceController(WorkspaceState())
    loaded = replace(
        _loaded(
            _result("SCF", produces_potential=True),
            atoms=embedded_atoms, potential_path=output,
            directory=str(tmp_path),
        ),
        source_versions=(host_version,),
    )

    record = controller.adopt_external_result(loaded).record
    assert record.input_state_id is None
    state = controller.result_store.state_for_result(record)
    assert state.potential_version.path == output
    assert state.source_dependencies == (host_version,)
    assert state.structure_snapshot is not None
    restored = _restore_state_atoms(state)
    assert restored.embedding_host is host_potential
    assert len(restored) == len(embedded_atoms)

    host.write_text("different host")
    with pytest.raises(PotentialVersionChanged, match="changed"):
        _restore_state_atoms(state)
