"""Guided task parameters belong to the calculation, not to the workspace."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from ase import Atoms
from ase2sprkkr import InputParameters

from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.flows import calculation as calculation_flow


@pytest.mark.parametrize("with_expert_document", [False, True])
def test_guided_task_keeps_expert_workspace_inputs_untouched(
    monkeypatch, tmp_path, with_expert_document,
):
    expert = InputParameters.create("SCF") if with_expert_document else None
    controller = WorkspaceController(WorkspaceState(
        atoms=Atoms("Fe", cell=[2.8, 2.8, 2.8], pbc=True),
        input_parameters=expert, directory=str(tmp_path),
    ))
    baseline = controller.input_parameters_generation
    dirty = controller.has_unsaved_input_parameters
    params = InputParameters.create("DOS")
    captured = {}

    monkeypatch.setattr(calculation_flow, "select_guided_input_parameters",
                        lambda *_args, **_kwargs: params)

    def fake_run(_controller, _recent_files, _parent, **kwargs):
        captured.update(kwargs)
        return "monitor"

    monkeypatch.setattr(calculation_flow, "run_calculation", fake_run)
    assert calculation_flow.configure_and_run_task(
        controller, RecentFiles(tmp_path / "recent.json"), None,
        "dos", dataset_default_mode="auto",
    ) == "monitor"
    request = captured["request_override"]
    assert request.atoms is controller.atoms
    assert request.state_id == controller.state_id
    assert request.input_parameters.task_name.lower() == "dos"
    assert request.input_parameters is not params
    assert controller.input_parameters is expert
    assert controller.input_parameters_generation == baseline
    assert controller.has_unsaved_input_parameters is dirty


def test_cancelled_guided_dialog_never_creates_workspace_input(monkeypatch, tmp_path):
    controller = WorkspaceController(WorkspaceState(
        atoms=Atoms("Fe", cell=[2.8, 2.8, 2.8], pbc=True)
    ))
    baseline = controller.input_parameters_generation
    monkeypatch.setattr(calculation_flow, "select_guided_input_parameters",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        calculation_flow, "run_calculation",
        lambda *_args, **_kwargs: pytest.fail("Cancelled Guided task must not launch"),
    )
    assert calculation_flow.configure_and_run_task(
        controller, RecentFiles(tmp_path / "recent.json"), None,
        "dos", dataset_default_mode="auto",
    ) is None
    assert controller.input_parameters is None
    assert controller.input_parameters_generation == baseline


def test_recomputed_guided_result_stays_out_of_workspace(monkeypatch, tmp_path):
    expert = InputParameters.create("SCF")
    params = InputParameters.create("DOS")
    controller = WorkspaceController(WorkspaceState(
        atoms=Atoms("Fe", cell=[2.8, 2.8, 2.8], pbc=True),
        input_parameters=expert, directory=str(tmp_path),
    ))
    baseline = controller.input_parameters_generation
    monkeypatch.setattr(
        controller.result_store, "result",
        lambda _id: SimpleNamespace(input_parameters=params),
    )

    class GuidedDialog:
        DialogCode = SimpleNamespace(Accepted=1)

        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def parameters(self):
            return params

    monkeypatch.setattr(calculation_flow, "GuidedInputParametersDialog", GuidedDialog)
    captured = {}

    def fake_run(_controller, _recent, _parent, **kwargs):
        captured.update(kwargs)
        return "monitor"

    monkeypatch.setattr(calculation_flow, "run_calculation", fake_run)
    assert calculation_flow.recompute_result(
        controller, RecentFiles(tmp_path / "recent.json"), None, 17,
    ) == "monitor"
    assert captured["request_override"].input_parameters.task_name.lower() == "dos"
    assert controller.input_parameters is expert
    assert controller.input_parameters_generation == baseline


def test_guided_configuration_rejects_structure_changed_during_dialog(
    monkeypatch, tmp_path,
):
    controller = WorkspaceController(WorkspaceState(
        atoms=Atoms("Fe", cell=[2.8, 2.8, 2.8], pbc=True)
    ))

    def change_while_editing(*_args, **_kwargs):
        controller.replace_structure(Atoms("Cu", cell=[3, 3, 3], pbc=True))
        return InputParameters.create("DOS")

    messages = []
    monkeypatch.setattr(calculation_flow, "select_guided_input_parameters",
                        change_while_editing)
    monkeypatch.setattr(
        calculation_flow.QMessageBox, "warning",
        lambda _parent, title, message: messages.append((title, message)),
    )
    monkeypatch.setattr(
        calculation_flow, "run_calculation",
        lambda *_args, **_kwargs: pytest.fail("Stale structure must not be submitted"),
    )
    assert calculation_flow.configure_and_run_task(
        controller, RecentFiles(tmp_path / "recent.json"), None,
        "dos", dataset_default_mode="auto",
    ) is None
    assert messages and messages[0][0] == "Structure Changed"
    assert controller.input_parameters is None


def test_one_off_embedded_task_still_requires_usable_host(monkeypatch, tmp_path):
    """Bypassing the workspace input document must not bypass host checks."""
    from ase.build import bulk
    from ase2sprkkr import SPRKKRAtoms
    from ase2sprkkr_gui.ase.embedding import EmbeddingDraft

    host = SPRKKRAtoms.promote_ase_atoms(
        bulk("Fe", "bcc", a=2.87, cubic=True)
    ).potential
    host.SCF_INFO.SCFSTATUS = "START"
    draft = EmbeddingDraft(host)
    draft.include([draft.center])
    controller = WorkspaceController(WorkspaceState(atoms=draft.to_atoms()))
    request = calculation_flow._one_off_task_request(
        controller, InputParameters.create("SCF"),
        expected_structure_generation=controller.structure_generation,
        parent=None,
    )
    messages = []
    monkeypatch.setattr(
        calculation_flow.QMessageBox, "information",
        lambda _parent, title, message: messages.append((title, message)),
    )
    assert calculation_flow.run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), None,
        select_profile=False, request_override=request,
    ) is None
    assert messages and messages[0][0] == "Host SCF Required"
    assert controller.input_parameters is None


def test_reconverge_scf_uses_current_potential_without_resetting_workspace(
    monkeypatch, tmp_path,
):
    controller = WorkspaceController(WorkspaceState(
        atoms=Atoms("Fe", cell=[2.8, 2.8, 2.8], pbc=True),
        directory=str(tmp_path),
    ))
    initial_state_id = controller.state_id
    initial_generation = controller.structure_generation
    parameters = InputParameters.create("SCF")
    monkeypatch.setattr(
        calculation_flow, "select_guided_input_parameters",
        lambda *_args, **_kwargs: parameters,
    )
    captured = {}
    monkeypatch.setattr(
        calculation_flow, "run_calculation",
        lambda *_args, **kwargs: captured.update(kwargs) or "run",
    )

    assert calculation_flow.configure_and_run_task(
        controller, RecentFiles(tmp_path / "recent.json"), None,
        "scf", dataset_default_mode="auto", restart_scf=True,
    ) == "run"
    request = captured["request_override"]
    assert request.restart_scf is True
    assert request.atoms is controller.atoms
    assert request.state_id == initial_state_id
    assert controller.structure_generation == initial_generation
    assert not controller.restarted
    assert controller.input_parameters is None
