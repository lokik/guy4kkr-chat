from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application import result_loading as result_loading_module
from guy4ase.gui.application.result_loading import load_result, load_result_file
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController


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
