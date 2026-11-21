"""Embedding creation must establish its native host before SCF setup."""
from __future__ import annotations

import pytest
from ase.build import bulk
from ase2sprkkr import InputParameters, Potential, SPRKKRAtoms

from ase2sprkkr_gui.ase.embedding import EmbeddingDraft, embedding_source
from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.dialogs.structures import embedding as embedding_dialog
from ase2sprkkr_gui.gui.flows import calculation, files, structures


@pytest.mark.parametrize("source_kind", [
    "python_bulk", "native_host", "geometry_cluster", "layered_geometry",
])
def test_created_cluster_reuses_native_host_during_scf(monkeypatch, tmp_path, source_kind):
    source = bulk("Fe", "bcc", a=2.87, cubic=True)
    original_host = None
    if source_kind == "native_host":
        original_host = SPRKKRAtoms.promote_ase_atoms(source).potential
    elif source_kind == "geometry_cluster":
        draft = EmbeddingDraft(source)
        draft.include([draft.center])
        source = draft.to_atoms()
    elif source_kind == "layered_geometry":
        from ase2sprkkr.sprkkr.atoms_region import AtomsRegion

        source = SPRKKRAtoms(
            "Fe3", positions=[[0, 0, 0], [0, 0, 2], [0, 0, 4]],
            cell=[2, 2, 6], pbc=[True, True, False],
        )
        cell = source.cell.copy()
        cell[2] /= 3
        for index, name in enumerate(("left", "central", "right")):
            AtomsRegion(name, slice(index, index + 1), cell.copy(),
                        pbc=[True, True, name != "central"], atoms=source)
    controller = WorkspaceController(WorkspaceState(atoms=source))
    hosts = []

    def accept_cluster(candidate, _parent):
        host, existing = embedding_source(candidate)
        assert isinstance(host, Potential)
        hosts.append(host)
        draft = EmbeddingDraft(host, existing)
        draft.include([draft.center])
        return draft.to_atoms()

    def unexpected_host_prompt(*_args, **_kwargs):
        pytest.fail("A cluster created in the GUI must already have its host potential")

    monkeypatch.setattr(embedding_dialog, "select_build_embedding_structure", accept_cluster)
    monkeypatch.setattr(files.QFileDialog, "getOpenFileName", unexpected_host_prompt)
    result = structures.build_embedding_structure(controller, None)
    assert result is controller.atoms
    assert controller.can_run_embedding()
    assert result.embedding_host is hosts[0]
    if source_kind == "layered_geometry":
        assert set(hosts[0].atoms.regions) == {"left", "central", "right"}
        for name, region in source.regions.items():
            assert region.atoms is source
            assert hosts[0].atoms.regions[name].atoms is hosts[0].atoms
    if original_host is not None:
        assert hosts[0] is original_host
    else:
        # Creating a START host must not mutate the original structure.
        assert not isinstance(source, SPRKKRAtoms) or not source.has_potential()

    parameters = InputParameters.create("SCF")
    monkeypatch.setattr(calculation, "select_guided_input_parameters",
                        lambda *_args, **_kwargs: parameters)
    launched = []
    real_run_calculation = calculation.run_calculation
    monkeypatch.setattr(calculation, "run_calculation",
                        lambda *_args, **_kwargs: launched.append(controller.atoms) or "run")
    messages = []
    monkeypatch.setattr(calculation.QMessageBox, "information",
                        lambda _parent, title, message: messages.append((title, message)))
    # A freshly generated START host can be saved/edited but not used for
    # an embedded SCF calculation until its own periodic SCF was run.
    assert real_run_calculation(
        controller, RecentFiles(tmp_path / "recent.json"), None,
    ) is None
    assert messages and messages[0][0] == "Host SCF Required"
    assert not launched
    hosts[0].SCF_INFO.SCFSTATUS = "CONVERGED"
    assert calculation.configure_and_run_task(
        controller, RecentFiles(tmp_path / "recent.json"), None,
        "scf", dataset_default_mode="auto",
    ) == "run"
    assert launched == [result]
    assert controller.atoms.embedding_host is hosts[0]


def test_converged_cluster_offers_post_scf_tasks_instead_of_scf():
    from ase2sprkkr_gui.gui.workflow.model import WorkflowSection, RunTask
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner

    host = SPRKKRAtoms.promote_ase_atoms(
        bulk("Fe", "bcc", a=2.87, cubic=True)
    ).potential
    host.SCF_INFO.SCFSTATUS = "CONVERGED"
    draft = EmbeddingDraft(host)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    cluster.potential.SCF_INFO.SCFSTATUS = "CONVERGED"
    controller = WorkspaceController(WorkspaceState(atoms=cluster))

    plan = WorkflowPlanner().for_workspace(controller)
    calculate = plan.group(WorkflowSection.CALCULATE)
    commands = [action.command for action in calculate.actions]
    assert RunTask("scf") not in commands
    assert RunTask("dos") in commands
    assert "SCF status: CONVERGED" in plan.subtitle




def test_completed_embedded_scf_output_unlocks_post_scf_tasks_when_clupot_still_iterating(
    tmp_path,
):
    """An SCF OUT reporting convergence overrides native ITERATING in memory."""
    from ase2sprkkr.outputs.readers.scf import ScfResult
    from ase2sprkkr_gui.gui.application.result_loading import load_result
    from ase2sprkkr_gui.gui.workflow.model import WorkflowSection, RunTask
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner

    host = SPRKKRAtoms.promote_ase_atoms(
        bulk("Fe", "bcc", a=2.87, cubic=True)
    ).potential
    host.SCF_INFO.SCFSTATUS = "CONVERGED"
    draft = EmbeddingDraft(host)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    native_cluster = cluster.potential
    native_cluster.SCF_INFO.SCFSTATUS = "ITERATING"
    assert not cluster.sprkkr_is_scf_converged()

    parameters = InputParameters.create("SCF")
    parameters.CONTROL.CLUTYPE = "embedded"
    parameters.CONTROL.POTFIL = "host.pot"
    parameters.CONTROL.POTFIL_CLU = "cluster.pot"
    result = ScfResult(parameters, None, tmp_path)
    result.iterations = [{"converged": lambda: True}]
    result.require_current_file = lambda _path: None
    result._read_potential = lambda _path: native_cluster

    loaded = load_result(result, fallback_directory=tmp_path)
    assert loaded.atoms is cluster
    assert loaded.potential_error is None
    assert loaded.atoms.sprkkr_is_scf_converged()
    assert loaded.atoms.info["sprkkr_embedding_scf_status"] == "CONVERGED"
    assert loaded.atoms.embedding_host is host

    workspace = WorkspaceController(WorkspaceState(atoms=loaded.atoms))
    plan = WorkflowPlanner().for_workspace(workspace)
    commands = [action.command for action in plan.group(WorkflowSection.CALCULATE).actions]
    assert RunTask("scf") not in commands
    assert RunTask("dos") in commands
    assert "SCF status: CONVERGED" in plan.subtitle




@pytest.mark.parametrize(
    ("cluster_status", "host_status", "allow_scf", "allow_post_scf"),
    (
        ("START", "CONVERGED", True, False),
        ("ITERATING", "CONVERGED", True, True),
        ("CONVERGED", "CONVERGED", False, True),
        ("ITERATING", "START", False, False),
    ),
)
def test_embedded_iteration_allows_post_scf_without_changing_native_status(
    cluster_status, host_status, allow_scf, allow_post_scf,
):
    """Native ITERATING is usable for supported post-SCF tasks after reopening.

    The planner must not infer or persist CONVERGED, and a START host remains
    unusable as embedding boundary conditions.
    """
    from ase2sprkkr_gui.gui.workflow.model import WorkflowSection, RunTask
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner

    host = SPRKKRAtoms.promote_ase_atoms(
        bulk("Fe", "bcc", a=2.87, cubic=True)
    ).potential
    host.SCF_INFO.SCFSTATUS = host_status

    def open_cluster():
        cluster = EmbeddingDraft(host)
        cluster.include([cluster.center])
        atoms = cluster.to_atoms()
        atoms.potential.SCF_INFO.SCFSTATUS = cluster_status
        return WorkspaceController(WorkspaceState(atoms=atoms))

    for _ in range(2):
        # Independent workspace sessions must present the same actions solely
        # from the stored native status, not previous result-parser state.
        workspace = open_cluster()
        plan = WorkflowPlanner().for_workspace(workspace)
        actions = plan.group(WorkflowSection.CALCULATE).actions
        commands = [action.command for action in actions]
        assert (RunTask("scf") in commands) is allow_scf
        assert (RunTask("dos") in commands) is allow_post_scf
        if cluster_status == "ITERATING" and allow_scf:
            scf = next(action for action in actions if action.command == RunTask("scf"))
            assert scf.title == "Continue SCF"
            assert "SCF status: iterating SCF" in plan.subtitle
        assert workspace.scf_status() == cluster_status
        assert workspace.atoms.potential.SCF_INFO.SCFSTATUS() == cluster_status
        assert host.SCF_INFO.SCFSTATUS() == host_status


def test_failed_host_creation_never_opens_embedding_editor(monkeypatch):
    source = bulk("Fe", "bcc", a=2.87, cubic=True)
    controller = WorkspaceController(WorkspaceState(atoms=source))
    generation = controller.structure_generation

    def fail_host(_atoms):
        raise ValueError("Cannot create host")

    def unexpected_editor(*_args):
        pytest.fail("The editor cannot open before its native host exists")

    messages = []
    monkeypatch.setattr(Potential, "from_atoms", fail_host)
    monkeypatch.setattr(embedding_dialog, "select_build_embedding_structure", unexpected_editor)
    monkeypatch.setattr(structures.QMessageBox, "warning",
                        lambda _parent, _title, message: messages.append(message))
    assert structures.build_embedding_structure(controller, None) is None
    assert messages == ["Cannot create host"]
    assert controller.atoms is source
    assert controller.structure_generation == generation

def test_host_scf_result_updates_a_cluster_edited_while_host_was_running(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import numpy as np
    from ase2sprkkr_gui.gui.workflow.model import ConvergeHostScf
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner
    from ase2sprkkr_gui.gui.workflow.model import WorkflowSection, RunTask

    host = SPRKKRAtoms.promote_ase_atoms(
        bulk("Fe", "bcc", a=2.87, cubic=True)
    ).potential
    draft = EmbeddingDraft(host)
    draft.include([draft.center])
    cluster = draft.to_atoms()
    controller = WorkspaceController(WorkspaceState(atoms=cluster))
    plan = WorkflowPlanner().for_workspace(controller)
    assert [action.command for action in plan.group(WorkflowSection.CALCULATE).actions] == [
        ConvergeHostScf()
    ]
    assert "Host SCF: START" in plan.subtitle

    parameters = InputParameters.create("SCF")
    monkeypatch.setattr(calculation, "select_guided_input_parameters",
                        lambda *_args, **_kwargs: parameters)
    captured = {}
    def start(_controller, _recent, _parent, **kwargs):
        captured.update(kwargs)
        return "run"
    monkeypatch.setattr(calculation, "run_calculation", start)
    assert calculation.configure_and_run_host_scf(
        controller, RecentFiles(tmp_path / "recent.json"), None,
        dataset_default_mode="auto",
    ) == "run"

    request = captured["request_override"]
    assert request.potential is host
    assert request.atoms is host.atoms
    assert not request.restart_scf

    # While host SCF runs, the user edits the cluster. This must not prevent
    # adoption of the new host or overwrite the later edit.
    edited = controller.atoms.copy()
    edited.positions[0, 0] += 0.04
    controller.replace_structure(edited)
    expected_positions = edited.positions.copy()
    new_host = Potential.from_atoms(host.atoms.copy())
    new_host.SCF_INFO.SCFSTATUS = "CONVERGED"
    monkeypatch.setattr(controller, "adopt_external_result", lambda _loaded: "record")
    assert captured["on_result_loaded"](
        SimpleNamespace(result=SimpleNamespace(potential=new_host)), request
    ) == "record"
    assert controller.atoms.embedding_host is new_host
    np.testing.assert_allclose(controller.atoms.positions, expected_positions)
    assert not controller.is_scf_converged()

    # An independently changed host must not be overwritten by the old run.
    third_host = Potential.from_atoms(host.atoms.copy())
    current = controller.atoms.copy()
    current.embedding_host = third_host
    controller.replace_structure(current)
    assert not controller.replace_embedding_host_if_current(host, new_host)
    assert controller.atoms.embedding_host is third_host


@pytest.mark.parametrize("status", ["ITR", "CONVERGED"])
def test_partially_converged_host_actions_and_restart(status):
    from ase2sprkkr_gui.gui.workflow.model import (
        ConvergeHostScf, RunTask, WorkflowSection,
    )
    from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner

    host = SPRKKRAtoms.promote_ase_atoms(
        bulk("Fe", "bcc", a=2.87, cubic=True)
    ).potential
    host.SCF_INFO.SCFSTATUS = status
    draft = EmbeddingDraft(host)
    draft.include([draft.center])
    controller = WorkspaceController(WorkspaceState(atoms=draft.to_atoms()))
    plan = WorkflowPlanner().for_workspace(controller)
    calculate = plan.group(WorkflowSection.CALCULATE)
    commands = [action.command for action in calculate.actions]
    assert RunTask("scf") in commands
    if status == "ITR":
        assert ConvergeHostScf() in commands
        assert "may be unreliable" in next(
            action.description for action in calculate.actions
            if action.command == RunTask("scf")
        )
    else:
        assert ConvergeHostScf() not in commands
    assert ConvergeHostScf(restart_scf=True) in [
        action.command
        for action in plan.group(WorkflowSection.OTHER).actions
    ]
