from __future__ import annotations

import pytest
from ase import Atoms
from types import SimpleNamespace

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import DocumentChange, WorkspaceController
from guy4ase.gui.flows import files as file_flows
from guy4ase.gui.flows import structures as structure_flows


@pytest.mark.parametrize("suffix", [".pot", ".pot_new"])
def test_structure_flow_loads_potential_and_document_metadata(tmp_path, monkeypatch, suffix):
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    path = tmp_path / f"Fe{suffix}"
    reads = []
    monkeypatch.setattr(file_flows, "ase_read", lambda value: reads.append(value) or atoms)
    parameters = object()
    controller = WorkspaceController(WorkspaceState(input_parameters=parameters))
    history = RecentFiles(tmp_path / "recent.json")

    assert file_flows.load_structure(controller, history, path, object())
    assert reads == [path.resolve()]
    assert controller.atoms is atoms
    assert controller.directory == str(tmp_path.resolve())
    assert controller.potential_path == str(path.resolve())
    assert controller.input_parameters is parameters
    assert history.paths("structure") == (str(path),)


def test_loading_nonpotential_structure_drops_old_potential_source(tmp_path, monkeypatch):
    atoms = Atoms("Cu", cell=(2.8, 2.8, 2.8), pbc=True)
    path = tmp_path / "Cu.xyz"
    monkeypatch.setattr(file_flows, "ase_read", lambda _path: atoms)
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe"), potential_path="Fe.pot")
    )

    assert file_flows.load_structure(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        path,
        object(),
    )
    assert controller.atoms is atoms
    assert controller.potential_path is None


def test_input_flow_keeps_independent_structure_change(tmp_path, monkeypatch):
    path = tmp_path / "Fe.inp"
    original_parameters = object()
    parsed_parameters = object()
    replacement_atoms = Atoms("Cu")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=original_parameters,
            directory="original",
        )
    )
    history = RecentFiles(tmp_path / "recent.json")

    def parse(_path):
        controller.replace_structure(replacement_atoms)
        return parsed_parameters

    monkeypatch.setattr(file_flows.InputParameters, "from_file", staticmethod(parse))
    monkeypatch.setattr(
        file_flows,
        "document_change_applied",
        lambda _parent, change: change is DocumentChange.APPLIED,
    )

    assert file_flows.load_input_parameters(controller, history, path, object())
    assert controller.atoms is replacement_atoms
    assert controller.input_parameters is parsed_parameters
    assert controller.directory == str(tmp_path.resolve())
    assert history.paths("input") == (str(path),)


def test_structure_save_uses_published_atoms_and_updates_history(tmp_path, monkeypatch):
    structure_path = tmp_path / "Fe.xyz"
    atoms = Atoms("Fe")
    writes = []
    controller = WorkspaceController(WorkspaceState(atoms=atoms))
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(
        file_flows.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(structure_path), ""),
    )
    monkeypatch.setattr(
        file_flows,
        "ase_write",
        lambda path, value: writes.append((path, value)),
    )

    assert file_flows.save_structure(controller, history, object())
    assert writes == [(structure_path.resolve(), atoms)]
    assert history.paths("structure") == (str(structure_path),)


def test_file_chooser_and_recent_use_same_structure_loader(tmp_path, monkeypatch):
    path = tmp_path / "Fe.cif"
    path.touch()
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    calls = []

    monkeypatch.setattr(file_flows, "load_structure", lambda *args: calls.append(args) or True)
    monkeypatch.setattr(
        file_flows.QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(path), ""),
    )

    assert file_flows.choose_and_load_structure(controller, history, object())
    assert file_flows.open_recent(controller, history, "structure", path, object())
    assert len(calls) == 2


def test_loading_unknown_structure_from_file_warns_but_keeps_it(tmp_path, monkeypatch):
    atoms = Atoms("Fe", cell=(2.8, 2.8, 8.0), pbc=(True, True, False))
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(file_flows, "ase_read", lambda _source: atoms)
    warnings = []
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    assert file_flows.load_structure(controller, history, tmp_path / "layer.xyz", object())
    assert [title for title, _message in warnings] == ["Unknown Structure Type"]


def _external_output(path):
    return LoadedResult(
        result=SimpleNamespace(
            task_name="scf", produces_potential=True, output_values={}
        ),
        output_path=path,
        potential_path=None,
        atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        potential_error=None,
        directory=str(path.parent),
        input_parameters=None,
    )


@pytest.mark.parametrize("from_recent", (False, True))
def test_opening_output_updates_directory_without_replacing_structure(
    tmp_path, monkeypatch, from_recent
):
    old_directory = tmp_path / "previous"
    new_directory = tmp_path / "old-calculation"
    new_directory.mkdir()
    output = new_directory / "SCF.out"
    output.write_text("saved output", encoding="utf-8")
    original_atoms = Atoms("Cu")
    original_parameters = object()
    controller = WorkspaceController(
        WorkspaceState(
            atoms=original_atoms,
            input_parameters=original_parameters,
            directory=str(old_directory),
        )
    )
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(
        file_flows, "_read_output", lambda _path, _parent: _external_output(output)
    )

    if from_recent:
        assert file_flows.open_recent(
            controller, history, "output", output, None
        )
    else:
        assert file_flows.load_output(controller, history, output, None)

    assert controller.directory == str(new_directory)
    assert controller.atoms is original_atoms
    assert controller.input_parameters is original_parameters
    assert len(controller.result_store.results) == 1
    assert history.paths("output") == (str(output),)


def test_failed_output_load_keeps_working_directory(tmp_path, monkeypatch):
    controller = WorkspaceController(WorkspaceState(directory="original"))
    generation = controller.directory_generation
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(file_flows, "_read_output", lambda *_args: None)

    assert not file_flows.load_output(
        controller, history, tmp_path / "bad.out", None
    )
    assert controller.directory == "original"
    assert controller.directory_generation == generation
    assert controller.result_store.results == ()
