from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms

from ase2sprkkr_gui.gui.application import result_loading as result_loading_module
from ase2sprkkr_gui.gui.application.result_loading import load_result, load_result_file
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController


def test_embedded_scf_loads_new_clupot_instead_of_registered_start(tmp_path):
    start = tmp_path / "cluster.clupot"
    produced = tmp_path / "cluster.clupot_new"
    start.touch()
    produced.touch()
    output_atoms = Atoms("Fe")
    result = SimpleNamespace(
        files={"potential": start.name},
        directory=str(tmp_path),
        task_name="scf",
        is_embedded=True,
        potential_filename=produced.name,
        potential=SimpleNamespace(atoms=output_atoms),
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=tmp_path)

    assert loaded.potential_path == produced.resolve()
    assert loaded.atoms is output_atoms
    assert loaded.potential_error is None




def test_embedded_dos_resolves_cluster_potential_not_registered_host(tmp_path):
    """The DOS FILES potential is the host; the reusable state is CLUPOT."""
    host = tmp_path / "host.pot"
    cluster = tmp_path / "cluster.pot"
    host.touch()
    cluster.touch()
    cluster_atoms = Atoms("Fe")
    result = SimpleNamespace(
        task_name="dos",
        is_embedded=True,
        files={"potential": host.name},
        directory=str(tmp_path),
        potential_filename=cluster.name,
        potential=SimpleNamespace(atoms=cluster_atoms),
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=tmp_path)

    assert loaded.potential_path == cluster.resolve()
    assert loaded.potential_path != host.resolve()
    assert loaded.atoms is cluster_atoms
    assert loaded.potential_error is None


def test_native_dos_result_selects_control_potfil_clu(tmp_path, monkeypatch):
    """The real DOS result resolves its CLUPOT despite a host FILES entry."""
    from ase2sprkkr import InputParameters
    from ase2sprkkr.outputs.readers.dos import DosResult

    parameters = InputParameters.create("DOS")
    parameters.CONTROL.CLUTYPE = "embedded"
    parameters.CONTROL.POTFIL = "host.pot"
    parameters.CONTROL.POTFIL_CLU = "cluster.clu"
    # The native result requires a concrete host file for provenance,
    # even when this test stubs out potential parsing itself.
    (tmp_path / "host.pot").write_text("host placeholder")
    result = DosResult(parameters, None, tmp_path, task_name="dos")
    result.files.add_file("potential", "host.pot")
    parsed_atoms = Atoms("Fe")
    monkeypatch.setattr(
        result, "_read_potential",
        lambda path: SimpleNamespace(atoms=parsed_atoms),
    )

    loaded = load_result(result, fallback_directory=tmp_path)

    assert result.is_embedded
    assert loaded.potential_path == (tmp_path / "cluster.clu").resolve()
    assert loaded.atoms is parsed_atoms


def test_embedded_dos_does_not_use_host_when_cluster_reference_is_missing(tmp_path):
    """A host file must never masquerade as the embedded result's geometry."""
    host = tmp_path / "host.pot"
    host.touch()
    result = SimpleNamespace(
        task_name="dos",
        is_embedded=True,
        files={"potential": host.name},
        directory=str(tmp_path),
        potential_filename=None,
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=tmp_path)

    assert loaded.potential_path is None
    assert loaded.atoms is None


def test_imported_embedded_dos_restores_cluster_and_offers_edit_not_build(
    tmp_path, monkeypatch,
):
    """Imported DOS history reopens the original cluster, never its periodic host."""
    from ase.build import bulk
    from ase2sprkkr import SPRKKRAtoms
    from ase2sprkkr_gui.ase.embedding import EmbeddingDraft
    from ase2sprkkr_gui.gui.application import historical_state
    from ase2sprkkr_gui.gui.workflow.model import BuildEmbedding, WorkflowSection
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner

    host_potential = SPRKKRAtoms.promote_ase_atoms(
        bulk("Fe", "bcc", a=2.87, cubic=True)
    ).potential
    host_potential.SCF_INFO.SCFSTATUS = "CONVERGED"
    draft = EmbeddingDraft(host_potential)
    draft.include([draft.center])
    embedded_atoms = draft.to_atoms()

    host_file = tmp_path / "host.pot"
    cluster_file = tmp_path / "cluster.clu"
    host_file.touch()
    cluster_file.touch()
    result = SimpleNamespace(
        task_name="dos",
        produces_potential=False,
        output_values={},
        is_embedded=True,
        files={"potential": host_file.name},
        directory=str(tmp_path),
        potential_filename=cluster_file.name,
        potential=SimpleNamespace(atoms=embedded_atoms),
        input_parameters=None,
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=tmp_path)
    controller = WorkspaceController(WorkspaceState())
    record = controller.adopt_external_result(loaded).record
    assert record is not None
    state = controller.result_store.state_for_result(record)
    assert state is not None
    assert state.potential_path == str(cluster_file.resolve())

    def read_state(version, *, embedding_host):
        assert version.path == cluster_file.resolve()
        assert embedding_host is host_potential
        return embedded_atoms

    monkeypatch.setattr(historical_state, "load_potential_version", read_state)
    controller.use_result_state(record.id)

    assert controller.structure_kind() == "0d"
    assert controller.atoms.embedding_host is host_potential
    actions = WorkflowPlanner().for_workspace(controller).group(WorkflowSection.CREATE)
    assert actions is not None
    assert next(
        action.title for action in actions.actions
        if action.command == BuildEmbedding()
    ) == "Edit Embedded Cluster"


def test_scf_output_without_converged_registration_overrides_input(tmp_path, monkeypatch):
    start = tmp_path / "Fe.pot"
    produced = tmp_path / "Fe.pot_new"
    start.touch()
    produced.touch()
    output_atoms = Atoms("Fe")

    def read(path, *, check_file_unchanged):
        assert check_file_unchanged
        assert path == str(produced.resolve())
        return SimpleNamespace(atoms=output_atoms)

    monkeypatch.setattr(result_loading_module.Potential, "from_file", staticmethod(read))
    result = SimpleNamespace(
        files={"potential": start.name},
        directory=str(tmp_path),
        task_name="scf",
        potential_filename=produced.name,
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=tmp_path)

    assert loaded.potential_path == produced.resolve()
    assert loaded.atoms is output_atoms


def test_result_loading_resolves_relative_artifacts_from_result_directory(
    tmp_path, monkeypatch
):
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    output = run_directory / "Fe.out"
    converged = run_directory / "Fe_converged.pot"
    fallback_potential = run_directory / "Fe.pot"
    converged.touch()
    fallback_potential.touch()
    atoms = Atoms("Fe")
    potential_reads = []
    parameters = object()
    result = SimpleNamespace(
        files={
            "output": output.name,
            "converged": converged.name,
            "potential": fallback_potential.name,
        },
        directory=str(run_directory),
        potential_filename="ignored.pot",
        input_parameters=parameters,
    )
    result.path_to = lambda key: result.files[key]

    def read_potential(path, *, check_file_unchanged):
        assert check_file_unchanged
        potential_reads.append(path)
        return SimpleNamespace(atoms=atoms)

    monkeypatch.setattr(
        result_loading_module.Potential,
        "from_file",
        staticmethod(read_potential),
    )

    loaded = load_result(result, fallback_directory=tmp_path / "unused-fallback")

    assert loaded.output_path == output.resolve()
    assert loaded.potential_path == converged.resolve()
    assert loaded.atoms is atoms
    assert loaded.potential_error is None
    assert loaded.directory == str(run_directory.resolve())
    assert loaded.input_parameters is parameters
    assert loaded.input_parameters_error is None
    assert potential_reads == [str(converged.resolve())]


def test_result_loading_keeps_input_parameter_parse_failure_nonfatal(tmp_path):
    error = ValueError("broken input")

    class Result:
        files = {}
        directory = str(tmp_path)
        output_file = None

        @property
        def input_parameters(self):
            raise error

    loaded = load_result(Result(), fallback_directory=tmp_path)

    assert loaded.input_parameters is None
    assert loaded.input_parameters_error is error


@pytest.mark.parametrize(
    ("files", "potential_filename", "expected_name"),
    [
        ({"potential": "registered.pot"}, "filename.pot", "registered.pot"),
        ({}, "filename.pot", "filename.pot"),
    ],
)
def test_result_loading_uses_potential_fallbacks_and_fallback_directory(
    tmp_path, monkeypatch, files, potential_filename, expected_name
):
    potential = tmp_path / expected_name
    potential.touch()
    atoms = Atoms("Fe")
    result = SimpleNamespace(
        files=files,
        directory=None,
        potential_filename=potential_filename,
    )
    result.path_to = lambda key: result.files[key]

    def read_potential(_path, *, check_file_unchanged):
        assert check_file_unchanged
        return SimpleNamespace(atoms=atoms)

    monkeypatch.setattr(
        result_loading_module.Potential,
        "from_file",
        staticmethod(read_potential),
    )

    loaded = load_result(result, fallback_directory=tmp_path)

    assert loaded.potential_path == potential.resolve()
    assert loaded.atoms is atoms
    assert loaded.potential_error is None


def test_result_loading_uses_output_file_before_explicit_output_fallback(tmp_path):
    result = SimpleNamespace(
        files={},
        directory=None,
        output_file="metadata.out",
    )

    loaded = load_result(
        result,
        fallback_directory=tmp_path,
        output_fallback=tmp_path / "external.out",
    )

    assert loaded.output_path == (tmp_path / "metadata.out").resolve()
    assert loaded.directory == str(tmp_path.resolve())


def test_result_loading_reports_a_potential_path_that_is_not_a_file(tmp_path):
    potential_directory = tmp_path / "potential.pot"
    potential_directory.mkdir()
    result = SimpleNamespace(
        files={"potential": potential_directory.name},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=None)

    assert loaded.potential_path == potential_directory.resolve()
    assert loaded.atoms is None
    assert isinstance(loaded.potential_error, IsADirectoryError)


def test_missing_output_path_is_advisory_provenance(tmp_path):
    missing_output = tmp_path / "missing.out"
    result = SimpleNamespace(
        files={"output": missing_output.name},
        directory=str(tmp_path),
    )
    result.path_to = lambda key: result.files[key]

    loaded = load_result(result, fallback_directory=tmp_path)

    assert loaded.output_path == missing_output.resolve()
    assert not missing_output.exists()
    assert loaded.potential_error is None


def test_missing_referenced_potential_is_nonfatal_and_does_not_replace_workspace(
    tmp_path, monkeypatch
):
    output = tmp_path / "external.out"
    missing = tmp_path / "missing.pot"
    result = SimpleNamespace(
        task_name="scf",
        files={"output": output.name, "converged": missing.name},
        directory=str(tmp_path),
        produces_potential=True,
    )
    result.path_to = lambda key: result.files[key]
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: result),
    )
    original_atoms = Atoms("Cu")
    controller = WorkspaceController(
        WorkspaceState(atoms=original_atoms, potential_path="Cu.pot")
    )

    adoption = controller.adopt_external_result(load_result_file(output))

    assert adoption.potential_path == missing.resolve()
    assert isinstance(adoption.potential_error, FileNotFoundError)
    assert controller.result_store.results[0].result is result
    assert controller.atoms is original_atoms
    assert controller.potential_path == "Cu.pot"


def test_result_parse_failure_has_no_workspace_side_effects(tmp_path, monkeypatch):
    atoms = Atoms("Cu")
    workspace = WorkspaceState(
        atoms=atoms,
        directory="original",
        potential_path="Cu.pot",
    )
    controller = WorkspaceController(workspace)
    structure_generation = controller.structure_generation
    input_generation = controller.input_parameters_generation
    directory_generation = controller.directory_generation
    project_generation = controller.active_project_generation
    monkeypatch.setattr(
        result_loading_module.TaskResult,
        "from_file",
        staticmethod(lambda _path: (_ for _ in ()).throw(ValueError("broken output"))),
    )

    with pytest.raises(ValueError, match="broken output"):
        load_result_file(tmp_path / "broken.out")

    assert controller.structure_generation == structure_generation
    assert controller.input_parameters_generation == input_generation
    assert controller.directory_generation == directory_generation
    assert controller.active_project_generation == project_generation
    assert controller.atoms is atoms
    assert controller.directory == "original"
    assert controller.potential_path == "Cu.pot"
    assert controller.result_store.results == ()


def test_native_cluster_result_requires_and_reuses_original_host(tmp_path, monkeypatch):
    from ase2sprkkr.potentials.cluster_potentials import ClusterPotential

    cluster_path = tmp_path / "after_scf.clu"
    cluster_path.write_text("GLOBAL SYSTEM PARAMETER\nNQCLU 1\n", encoding="utf-8")
    host = object()
    expected = Atoms("Fe")
    calls = []

    def parse(path, *, host):
        calls.append((path, host))
        return SimpleNamespace(atoms=expected)

    monkeypatch.setattr(ClusterPotential, "from_file", staticmethod(parse))
    result = SimpleNamespace(
        files={"converged": cluster_path.name},
        directory=str(tmp_path),
        input_parameters=None,
    )
    result.path_to = lambda key: result.files[key]

    missing = load_result(result, fallback_directory=tmp_path)
    assert missing.atoms is None
    assert "requires a host" in str(missing.potential_error)

    loaded = load_result(result, fallback_directory=tmp_path, embedding_host=host)
    assert loaded.atoms is expected
    assert loaded.potential_error is None
    assert calls == [(cluster_path.resolve(), host)]


def test_native_pot_extension_cluster_is_detected_by_header(tmp_path):
    from ase2sprkkr import Potential

    periodic = tmp_path / "bulk.pot"
    embedded = tmp_path / "cluster.pot_new"
    periodic.write_text("GLOBAL SYSTEM PARAMETER\nNQ 1\n", encoding="utf-8")
    embedded.write_text("GLOBAL SYSTEM PARAMETER\nNQCLU 3\n", encoding="utf-8")
    assert not Potential.is_cluster_file(periodic)
    assert Potential.is_cluster_file(embedded)
    assert not Potential.is_cluster_file(tmp_path / "missing.pot")


def test_imported_native_embedded_dos_preserves_host_version(tmp_path, native_embedded_potentials):
    """The reusable imported CLUPOT must retain its specific periodic host."""
    from ase2sprkkr import InputParameters
    from ase2sprkkr.outputs.readers.dos import DosResult
    from ase2sprkkr_gui.gui.application.historical_state import _restore_state_atoms
    from ase2sprkkr_gui.gui.application.result_loading import PotentialVersionChanged

    host, cluster = native_embedded_potentials

    parameters = InputParameters.for_task("DOS")
    parameters.CONTROL.CLUTYPE = "embedded"
    parameters.CONTROL.POTFIL = host.name
    parameters.CONTROL.POTFIL_CLU = cluster.name
    result = DosResult(parameters, None, tmp_path, task_name="dos")
    loaded = load_result(result, fallback_directory=tmp_path)
    assert loaded.potential_error is None
    assert loaded.atoms is not None
    assert len(loaded.source_versions) == 1
    assert loaded.source_versions[0].path == host
    assert loaded.source_versions[0].is_current()

    controller = WorkspaceController(WorkspaceState())
    record = controller.adopt_external_result(loaded).record
    state = controller.result_store.state_for_result(record)
    assert state.potential_path == str(cluster)
    assert state.source_dependencies == loaded.source_versions
    assert state.potential_version.path == cluster

    host.write_text("changed host potential")
    with pytest.raises(PotentialVersionChanged, match="changed"):
        _restore_state_atoms(state)


def test_imported_embedded_result_rejects_host_changed_during_loading(tmp_path, native_embedded_potentials, monkeypatch):
    """Do not attach a host version captured after the native potential was read."""
    from ase2sprkkr import InputParameters
    from ase2sprkkr.outputs.readers.dos import DosResult

    host, cluster = native_embedded_potentials

    parameters = InputParameters.for_task("DOS")
    parameters.CONTROL.CLUTYPE = "embedded"
    parameters.CONTROL.POTFIL = host.name
    parameters.CONTROL.POTFIL_CLU = cluster.name
    result = DosResult(parameters, None, tmp_path, task_name="dos")

    class ChangingPotential:
        @property
        def atoms(self):
            host.write_text("changed during import")
            return Atoms("Fe")

    monkeypatch.setattr(result, "_read_potential", lambda _: ChangingPotential())
    loaded = load_result(result, fallback_directory=tmp_path)
    assert loaded.atoms is None
    assert loaded.source_versions == ()
    assert "changed while" in str(loaded.potential_error)



def test_imported_embedded_result_uses_recorded_host_version(tmp_path, native_embedded_potentials):
    """Do not replace historical host evidence with a new disk snapshot."""
    from ase2sprkkr import InputParameters
    from ase2sprkkr.outputs.readers.dos import DosResult
    from kkrunner.files import FileEntry, FileManifest, FileVersion

    host, cluster = native_embedded_potentials

    params = InputParameters.for_task("DOS")
    params.CONTROL.CLUTYPE = "embedded"
    params.CONTROL.POTFIL = host.name
    params.CONTROL.POTFIL_CLU = cluster.name
    result = DosResult(params, None, tmp_path, task_name="dos")
    host_version = FileVersion.capture(host, require_digest=True)
    cluster_version = FileVersion.capture(cluster, require_digest=True)
    result.file_manifest = FileManifest(
        inputs=(FileEntry(local_path=str(host)), FileEntry(local_path=str(cluster))),
        input_versions=(host_version, cluster_version),
        captured_at="2026-11-20T00:00:00+00:00",
    )

    loaded = load_result(result, fallback_directory=tmp_path)
    assert loaded.potential_error is None
    assert loaded.source_versions == (host_version,)
    assert loaded.source_versions[0] is host_version
