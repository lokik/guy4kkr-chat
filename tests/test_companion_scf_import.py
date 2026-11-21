"""Related SCF imports are opportunistic and never replace the chosen result."""
from __future__ import annotations

from types import SimpleNamespace

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.result_loading import (
    LoadedResult,
    load_companion_scf_result,
)
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.application import result_loading
from ase2sprkkr_gui.gui.flows import files as file_flows


def _loaded(path, *, task="dos", potential=None):
    return LoadedResult(
        result=SimpleNamespace(
            task_name=task, produces_potential=task == "scf", output_values={}
        ),
        output_path=path,
        potential_path=potential,
        atoms=None,
        potential_error=None,
        directory=str(path.parent),
    )


def test_companion_scf_requires_same_produced_potential(tmp_path, monkeypatch):
    dos = tmp_path / "Fe_DOS.out"
    scf = tmp_path / "Fe_SCF.out"
    unrelated = tmp_path / "other.out"
    corrupt = tmp_path / "broken.out"
    for path in (dos, scf, unrelated, corrupt):
        path.write_text(path.name)
    potential = (tmp_path / "Fe.pot_new").resolve()

    def parse(path):
        if path == corrupt:
            raise ValueError("malformed output")
        name = "Fe.pot_new" if path == scf else "other.pot_new"
        result = SimpleNamespace(
            task_name="scf",
            directory=str(tmp_path),
            files={"converged": name},
            input_parameters=None,
        )
        result.path_to = lambda key: result.files[key]
        return result

    monkeypatch.setattr(
        result_loading.TaskResult, "from_file", staticmethod(parse)
    )

    companion = load_companion_scf_result(_loaded(dos, potential=potential))
    assert companion is not None
    assert companion.output_path == scf.resolve()
    assert companion.potential_path == potential


def test_companion_scf_skips_unrelated_or_unreadable_outputs(tmp_path, monkeypatch):
    dos = tmp_path / "Fe_DOS.out"
    scf = tmp_path / "other.out"
    dos.touch()
    scf.touch()

    def parse(_path):
        raise ValueError("not an SCF output")

    monkeypatch.setattr(
        result_loading.TaskResult, "from_file", staticmethod(parse)
    )
    assert load_companion_scf_result(
        _loaded(dos, potential=tmp_path / "Fe.pot_new")
    ) is None
    assert load_companion_scf_result(_loaded(dos)) is None
    assert load_companion_scf_result(
        _loaded(dos, task="scf", potential=tmp_path / "Fe.pot_new")
    ) is None


def test_loading_dos_also_imports_scf_but_selects_dos(tmp_path, monkeypatch):
    dos_path = tmp_path / "Fe_DOS.out"
    scf_path = tmp_path / "Fe_SCF.out"
    dos_path.write_text("dos")
    scf_path.write_text("scf")
    potential = tmp_path / "Fe.pot_new"
    dos = _loaded(dos_path, potential=potential)
    scf = _loaded(scf_path, task="scf", potential=potential)
    monkeypatch.setattr(file_flows, "_read_output", lambda *_: dos)
    monkeypatch.setattr(
        file_flows, "load_companion_scf_result", lambda _loaded: scf
    )
    monkeypatch.setattr(file_flows, "_finish_output_load", lambda *_args: None)
    controller = WorkspaceController()
    selected = []
    controller.resultSelectionRequested.connect(selected.append)

    assert file_flows.load_output(
        controller, RecentFiles(tmp_path / "recent.json"), dos_path, None
    )
    records = controller.result_store.results
    assert [record.task_name for record in records] == ["dos", "scf"]
    assert selected == [records[0].id]


def test_companion_failure_does_not_prevent_primary_output(tmp_path, monkeypatch):
    dos_path = tmp_path / "Fe_DOS.out"
    dos_path.write_text("dos")
    monkeypatch.setattr(
        file_flows, "_read_output", lambda *_: _loaded(dos_path)
    )

    def fail(_loaded):
        raise OSError("missing or broken SCF output")

    monkeypatch.setattr(file_flows, "load_companion_scf_result", fail)
    monkeypatch.setattr(file_flows, "_finish_output_load", lambda *_args: None)
    controller = WorkspaceController()

    assert file_flows.load_output(
        controller, RecentFiles(tmp_path / "recent.json"), dos_path, None
    )
    assert [record.task_name for record in controller.result_store.results] == ["dos"]
