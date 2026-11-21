from __future__ import annotations

import pytest
from ase import Atoms

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import DocumentChange, WorkspaceController
from ase2sprkkr_gui.gui.flows import files as file_flows
from ase2sprkkr_gui.gui.flows import structures as structure_flows


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
    assert not controller.has_unsaved_structure
    assert controller.input_parameters is parameters
    assert history.paths("structure") == (str(path),)



def test_periodic_potential_from_recent_file_is_probed_and_parsed_once(tmp_path, monkeypatch):
    from types import SimpleNamespace

    path = tmp_path / "Fe.pot"
    path.touch()
    atoms = Atoms("Fe", cell=(3, 3, 3), pbc=True)
    history = RecentFiles(tmp_path / "recent.json")
    controller = WorkspaceController()
    calls = []

    def probe(candidate):
        calls.append(("probe", candidate))
        return False

    def read(candidate, *, check_file_unchanged):
        calls.append(("read", candidate))
        assert check_file_unchanged
        return SimpleNamespace(atoms=atoms)

    monkeypatch.setattr(file_flows.Potential, "is_cluster_file", staticmethod(probe))
    monkeypatch.setattr(
        file_flows.PeriodicPotential, "from_file", staticmethod(read),
    )

    assert file_flows.load_structure(controller, history, path, None)
    assert calls == [("probe", path.resolve()), ("read", str(path.resolve()))]
    assert controller.atoms is atoms


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



def test_input_refresh_finishes_before_working_dialog_closes(tmp_path, monkeypatch):
    path = tmp_path / "Fe.inp"
    controller = WorkspaceController()
    recent = RecentFiles(tmp_path / "recent.json")
    events = []

    monkeypatch.setattr(
        file_flows.InputParameters, "from_file", staticmethod(lambda _path: object()),
    )
    controller.inputParametersChanged.connect(lambda _params: events.append("parameters"))
    recent.changed.connect(lambda: events.append("actions"))

    def modal(_parent, operation, *, on_success, **_kwargs):
        result = operation()
        prepared = on_success(result)
        events.append("working closed")
        return prepared

    monkeypatch.setattr(file_flows, "run_modal_task", modal)
    assert file_flows.load_input_parameters(controller, recent, path, object())
    assert events == ["parameters", "actions", "working closed"]


def test_structure_actions_refresh_before_working_dialog_closes(tmp_path, monkeypatch):
    from ase2sprkkr_gui.gui.flows import structure_candidates

    path = tmp_path / "Fe.xyz"
    atoms = Atoms("Fe", cell=(3, 3, 3), pbc=True)
    controller = WorkspaceController()
    recent = RecentFiles(tmp_path / "recent.json")
    events = []

    monkeypatch.setattr(file_flows, "_read_structure_file", lambda _path: atoms)
    controller.structureChanged.connect(lambda _atoms: events.append("structure"))
    recent.changed.connect(lambda: events.append("actions"))

    def modal(_parent, operation, *, on_success, **_kwargs):
        result = operation()
        prepared = on_success(result)
        events.append("working closed")
        return prepared

    monkeypatch.setattr(structure_candidates, "run_modal_task", modal)
    assert file_flows.load_structure(controller, recent, path, object())
    assert events == ["structure", "actions", "working closed"]


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


def test_loaded_structure_is_clean_until_edited(tmp_path, monkeypatch):
    structure = tmp_path / "Fe.cif"
    atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    monkeypatch.setattr(file_flows, "ase_read", lambda _path: atoms)
    controller = WorkspaceController()
    recent = RecentFiles(tmp_path / "recent.json")

    assert file_flows.load_structure(controller, recent, structure, object())
    assert not controller.has_unsaved_structure

    controller.apply_structure_edit(
        lambda original: original.repeat((2, 1, 1)),
        expected_structure_generation=controller.structure_generation,
    )
    assert controller.has_unsaved_structure


def test_loading_host_as_structure_replaces_an_existing_cluster(tmp_path, monkeypatch):
    """Opening a periodic host must never silently attach it to the old cluster."""
    cluster = Atoms("Fe", positions=[[0, 0, 0]], pbc=False)
    cluster.embedding_host = object()
    host_atoms = Atoms("Cu", cell=(3.6, 3.6, 3.6), pbc=True)
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    old_structure_id = controller.structure_id
    host_file = tmp_path / "Cu.pot"
    host_file.write_text("host")
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(
        file_flows.QFileDialog, "getOpenFileName",
        lambda *_args: (str(host_file), ""),
    )
    monkeypatch.setattr(
        file_flows.Potential, "is_cluster_file", staticmethod(lambda _path: False)
    )
    monkeypatch.setattr(file_flows, "_read_structure_file", lambda _path: host_atoms)

    assert file_flows.load_host_potential(controller, history, object())
    assert controller.atoms is host_atoms
    assert controller.structure_kind() == "3d"
    assert getattr(controller.atoms, "embedding_host", None) is None
    assert controller.structure_id != old_structure_id
    assert controller.potential_path == str(host_file.resolve())
    assert not controller.has_unsaved_structure
    assert history.paths("structure") == (str(host_file.resolve()),)


def test_host_load_cancel_or_cluster_file_preserves_current_cluster(
    tmp_path, monkeypatch,
):
    cluster = Atoms("Fe", pbc=False)
    cluster.embedding_host = object()
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    history = RecentFiles(tmp_path / "recent.json")
    generation = controller.structure_generation
    monkeypatch.setattr(
        file_flows.QFileDialog, "getOpenFileName",
        lambda *_args: ("", ""),
    )
    assert not file_flows.load_host_potential(controller, history, object())
    cluster_file = tmp_path / "wrong.clu.pot"
    cluster_file.write_text("cluster")
    monkeypatch.setattr(
        file_flows.QFileDialog, "getOpenFileName",
        lambda *_args: (str(cluster_file), ""),
    )
    monkeypatch.setattr(
        file_flows.Potential, "is_cluster_file", staticmethod(lambda _path: True)
    )
    warning = []
    monkeypatch.setattr(
        file_flows.QMessageBox, "warning",
        lambda _parent, title, message: warning.append((title, message)),
    )
    assert not file_flows.load_host_potential(controller, history, object())
    assert warning and warning[0][0] == "Not a Host Potential"
    assert controller.atoms is cluster
    assert controller.structure_generation == generation


def test_load_all_recent_results_reads_once_and_selects_latest(tmp_path, monkeypatch):
    from types import SimpleNamespace

    latest = tmp_path / "new.out"
    earlier = tmp_path / "old.out"
    broken = tmp_path / "broken.out"
    earlier_potential = tmp_path / "old.pot"
    latest_potential = tmp_path / "new.pot_new"
    history = RecentFiles(tmp_path / "recent.json")
    history.remember("output", earlier)
    history.remember("output", broken)
    history.remember("output", latest)
    selected = []
    parsed = []
    notices = []

    class Controller:
        resultSelectionRequested = SimpleNamespace(emit=selected.append)

        def adopt_external_result(self, result):
            return SimpleNamespace(
                record=SimpleNamespace(id=result),
                potential_path=(
                    earlier_potential if result == 1 else latest_potential
                ),
                potential_error=None,
            )

    def load(path):
        parsed.append(path)
        if path == broken:
            raise ValueError("invalid output")
        return 1 if path == earlier else 2

    calls = []
    def modal(parent, operation, **kwargs):
        calls.append(kwargs["title"])
        return operation()

    monkeypatch.setattr(file_flows, "load_result_file", load)
    monkeypatch.setattr(file_flows, "run_modal_task", modal)
    monkeypatch.setattr(
        file_flows.QMessageBox, "warning",
        lambda parent, title, detail: notices.append((title, detail)),
    )
    original = history.paths("output")
    imported = file_flows.load_all_recent_outputs(Controller(), history, None)

    assert imported == (earlier, latest)
    assert parsed == [earlier, broken, latest]
    assert calls == ["Loading Recent Results"]
    assert selected == [2]
    assert history.paths("output") == original
    assert history.paths("structure") == (
        str(latest_potential.resolve()), str(earlier_potential.resolve()),
    )
    assert history.last_kind == "output"
    assert len(notices) == 1
    assert "skipped 1" in notices[0][1]



def test_load_output_registers_reusable_potential_without_activating_it(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from ase2sprkkr_gui.gui.application.result_loading import LoadedResult

    output = tmp_path / "SCF.out"
    potential = tmp_path / "SCF.pot_new"
    output.write_text("output")
    potential.write_text("potential")
    loaded_atoms = Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    loaded = LoadedResult(
        result=SimpleNamespace(
            task_name="scf", produces_potential=True, output_values={},
        ),
        output_path=output,
        potential_path=potential,
        atoms=loaded_atoms,
        potential_error=None,
        directory=str(tmp_path),
        input_parameters=None,
    )
    monkeypatch.setattr(file_flows, "_read_output", lambda *_args: loaded)
    monkeypatch.setattr(file_flows, "_try_adopt_companion_scf", lambda *_args: None)

    original_atoms = Atoms("Cu", cell=(3, 3, 3), pbc=True)
    controller = WorkspaceController(WorkspaceState(atoms=original_atoms))
    history = RecentFiles(tmp_path / "recent.json")
    changed = []
    history.changed.connect(lambda: changed.append(True))

    assert file_flows.load_output(controller, history, output, None)
    assert history.paths("output") == (str(output.resolve()),)
    assert history.paths("structure") == (str(potential.resolve()),)
    assert history.last_kind == "output"
    assert len(changed) == 1
    assert controller.atoms is original_atoms
    assert controller.potential_path is None


def test_load_output_does_not_remember_unreadable_potential(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ase2sprkkr_gui.gui.application.result_loading import LoadedResult

    output = tmp_path / "SCF.out"
    potential = tmp_path / "broken.pot_new"
    output.write_text("output")
    loaded = LoadedResult(
        result=SimpleNamespace(
            task_name="scf", produces_potential=True, output_values={},
        ),
        output_path=output,
        potential_path=potential,
        atoms=None,
        potential_error=ValueError("invalid potential"),
        directory=str(tmp_path),
        input_parameters=None,
    )
    monkeypatch.setattr(file_flows, "_read_output", lambda *_args: loaded)
    monkeypatch.setattr(file_flows, "_try_adopt_companion_scf", lambda *_args: None)
    warnings = []
    monkeypatch.setattr(
        file_flows.QMessageBox, "warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")

    assert file_flows.load_output(controller, history, output, None)
    assert history.paths("output") == (str(output.resolve()),)
    assert history.paths("structure") == ()
    assert len(warnings) == 1


def test_directory_import_adds_only_successfully_loaded_potentials(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from ase2sprkkr_gui.gui.application.result_loading import LoadedResult

    output_a, output_b = tmp_path / "a.out", tmp_path / "b.out"
    potential_a, potential_b = tmp_path / "a.pot_new", tmp_path / "b.clu"
    for path in (output_a, output_b, potential_a):
        path.touch()

    def load(path):
        good = path == output_a
        return LoadedResult(
            result=SimpleNamespace(
                task_name="scf", produces_potential=True, output_values={},
            ),
            output_path=path,
            potential_path=potential_a if good else potential_b,
            atoms=Atoms("Fe", cell=(3, 3, 3), pbc=True) if good else None,
            potential_error=None if good else FileNotFoundError(potential_b),
            directory=str(tmp_path),
            input_parameters=None,
        )

    monkeypatch.setattr(file_flows, "load_result_file", load)
    monkeypatch.setattr(
        file_flows, "run_modal_task", lambda _parent, operation, **_kw: operation(),
    )
    monkeypatch.setattr(
        file_flows.QMessageBox, "information", lambda *_args: None,
    )
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    changed = []
    history.changed.connect(lambda: changed.append(True))

    assert file_flows.load_output_directory(controller, history, tmp_path, None) == (
        output_a, output_b,
    )
    assert history.paths("structure") == (str(potential_a.resolve()),)
    assert history.paths("output") == (
        str(output_b.resolve()), str(output_a.resolve()),
    )
    assert history.last_kind == "output"
    assert len(changed) == 2
