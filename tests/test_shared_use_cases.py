from __future__ import annotations

from types import SimpleNamespace

import pytest
from ase import Atoms

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import (
    CalculationNotReady,
    WorkspaceController,
)
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.flows import input_editing as input_editing_flow
from guy4ase.gui.flows import structures as structure_flows


class _Parameters:
    def __init__(self, name: str) -> None:
        self.name = name

    def copy(self, *, copy_values: bool):
        assert copy_values
        return _Parameters(f"{self.name}-copy")


class _RunWindow:
    """Flow-level test double for the public run-window constructor contract."""

    def __init__(self, request, parent=None, *, on_finished=None, **_kwargs):
        self.request = request
        self.parent = parent
        self.on_finished = on_finished
        self.shown = False
        self.started = False

    def show(self):
        self.shown = True

    def start(self):
        self.started = True


def test_workspace_calculation_input_completeness_requires_all_inputs():
    controller = WorkspaceController(WorkspaceState())
    assert not controller.can_calculate()

    controller.replace_structure(Atoms("Fe"))
    assert not controller.can_calculate()

    controller.replace_input_parameters(_Parameters("scf"))
    assert not controller.can_calculate()

    controller.change_directory("calculation")
    assert controller.can_calculate()


def test_create_calculation_request_reports_missing_preconditions():
    controller = WorkspaceController(WorkspaceState())

    with pytest.raises(CalculationNotReady):
        controller.create_calculation_request()


def test_run_calculation_does_not_hide_parameter_copy_value_error(tmp_path):
    class BrokenParameters:
        def copy(self, *, copy_values: bool):
            assert copy_values
            raise ValueError("broken parameter copy")

    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=BrokenParameters(),
            directory=str(tmp_path),
        )
    )

    with pytest.raises(ValueError, match="broken parameter copy"):
        calculation_flow.run_calculation(
            controller,
            RecentFiles(),
            None,
            select_profile=False,
        )


def test_run_calculation_does_not_hide_result_adoption_errors(
    tmp_path, monkeypatch
):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters("scf"),
            directory=str(tmp_path),
        )
    )
    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", _RunWindow)

    def broken_adoption(_loaded, *, request):
        assert request.structure_id == controller.structure_id
        assert request.state_id == controller.state_id
        raise RuntimeError("broken adoption invariant")

    monkeypatch.setattr(
        controller,
        "adopt_calculation_result",
        broken_adoption,
    )

    window = calculation_flow.run_calculation(
        controller,
        RecentFiles(),
        None,
        select_profile=False,
    )
    assert window is not None
    assert window.shown
    assert window.started

    with pytest.raises(RuntimeError, match="broken adoption invariant"):
        window.on_finished(object())


def test_run_result_handoff_preserves_launch_provenance(tmp_path, monkeypatch):
    backend_result = SimpleNamespace(
        task_name="scf",
        produces_potential=False,
    )
    output_path = tmp_path / "Fe.out"
    loaded = LoadedResult(
        result=backend_result,
        output_path=output_path,
        potential_path=None,
        atoms=None,
        potential_error=None,
        directory=str(tmp_path),
    )
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe"),
            input_parameters=_Parameters("scf"),
            directory=str(tmp_path),
        )
    )
    history = RecentFiles(tmp_path / "recent.json")
    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", _RunWindow)

    window = calculation_flow.run_calculation(
        controller,
        history,
        None,
        select_profile=False,
    )
    assert window is not None
    assert window.started

    window.on_finished(loaded)

    assert controller.result is backend_result
    assert len(controller.result_store.results) == 1
    record = controller.result_store.results[0]
    assert record.result is backend_result
    assert record.input_state_id == window.request.state_id
    assert history.paths("output") == (str(output_path.resolve()),)


def test_edit_current_structure_reads_published_structure_and_commits_replacement():
    original = Atoms("Fe")
    controller = WorkspaceController(WorkspaceState(atoms=original))

    def edit(atoms, *, parent):
        assert parent is None
        assert atoms is not original
        assert atoms.get_chemical_symbols() == original.get_chemical_symbols()
        edited = atoms.copy()
        edited.symbols = "Cu"
        return edited

    assert structure_flows.edit_current_structure(
        controller,
        None,
        edit,
        error_title="Edit Error",
    )
    assert controller.atoms is not original
    assert original.get_chemical_symbols() == ["Fe"]
    assert controller.atoms.get_chemical_symbols() == ["Cu"]
    assert controller.restarted


def test_edit_current_input_parameters_commits_accepted_copy(monkeypatch):
    original_atoms = Atoms("Fe")
    original_parameters = _Parameters("original")
    edited_parameters = _Parameters("edited")
    controller = WorkspaceController(
        WorkspaceState(
            atoms=original_atoms,
            input_parameters=original_parameters,
        )
    )

    def edit(parameters, *, parent, show_changed_only, atoms):
        assert parent is None
        assert not show_changed_only
        assert parameters is not original_parameters
        assert parameters.name == "original-copy"
        assert atoms is original_atoms
        return edited_parameters

    monkeypatch.setattr(
        input_editing_flow,
        "edit_input_parameters",
        edit,
    )

    assert input_editing_flow.edit_current_input_parameters(
        controller,
        None,
    )
    assert controller.input_parameters is edited_parameters


def test_choose_working_directory_is_shared_flow(monkeypatch, tmp_path):
    controller = WorkspaceController(WorkspaceState())
    chosen = tmp_path / "calculation"
    monkeypatch.setattr(
        calculation_flow.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(chosen),
    )

    assert calculation_flow.choose_working_directory(
        controller,
        None,
    )
    assert controller.directory == str(chosen)


def test_edit_site_elements_rejects_missing_structure_before_draft(monkeypatch):
    controller = WorkspaceController(WorkspaceState())
    messages = []

    def fail_if_called(_atoms):
        raise AssertionError("ElementAssignmentDraft must not receive None")

    monkeypatch.setattr(structure_flows, "ElementAssignmentDraft", fail_if_called)
    monkeypatch.setattr(
        structure_flows.QMessageBox,
        "information",
        lambda _parent, title, text: messages.append((title, text)),
    )

    assert not structure_flows.edit_site_elements(controller, None)
    assert messages == [
        ("No Structure", "Load or create a structure first."),
    ]
