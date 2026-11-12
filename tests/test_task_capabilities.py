from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/guy4ase-test-matplotlib")

from ase import Atoms
from ase2sprkkr import SPRKKRAtoms
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import calculation as calculation_flow
from guy4ase.gui.input_parameters.bindings import resolve_option
from guy4ase.gui.input_parameters.tasks import (
    WorkflowStage,
    guided_task_definition,
    guided_task_definitions,
    workflow_tasks,
)
from guy4ase.main import GuiApplication


def _scf_atoms(status="CONVERGED"):
    atoms = SPRKKRAtoms.promote_ase_atoms(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
        symmetry=False,
    )
    atoms._potential = SimpleNamespace(
        SCF_INFO=SimpleNamespace(SCFSTATUS=lambda: status)
    )
    return atoms


def test_guided_registry_integrates_with_backend_definitions():
    definitions = guided_task_definitions()
    assert definitions
    assert len({definition.backend_task for definition in definitions}) == len(definitions)

    for definition in definitions:
        parameters = InputParameters.create(definition.backend_task)
        assert parameters.task_name.lower() == definition.backend_task
        for is_2d in (False, True):
            for path in definition.build_spec(is_2d=is_2d).all_paths():
                resolve_option(parameters, path)


def test_bsf_guided_family_uses_concrete_backend_tasks():
    definition = guided_task_definition("bsf")

    assert definition.backend_task == "bsfek"
    assert definition.backend_tasks == ("bsfek", "bsfkk")
    assert guided_task_definition("bsfek") is definition
    assert guided_task_definition("bsfkk") is definition
    assert definition.accepts_backend_task("BSFEK")
    assert definition.accepts_backend_task("BSFKK")

    for backend_task in definition.backend_tasks:
        parameters = InputParameters.create(backend_task)
        for path in definition.build_spec().all_paths():
            resolve_option(parameters, path)


def test_guided_workflow_stages_are_presentation_metadata():
    scf = guided_task_definition("SCF")
    assert scf.workflow.stage is WorkflowStage.SCF
    assert workflow_tasks(WorkflowStage.SCF) == (scf,)
    assert all(
        definition.workflow.stage is WorkflowStage.POST_SCF
        for definition in workflow_tasks(WorkflowStage.POST_SCF)
    )


def test_calculation_readiness_is_task_agnostic():
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            input_parameters=InputParameters.create("TORQUE"),
            directory="calculation",
        )
    )

    assert controller.can_calculate()


def test_use_for_new_calculation_does_not_disable_expert_task():
    controller = WorkspaceController(
        WorkspaceState(
            atoms=_scf_atoms(),
            input_parameters=InputParameters.create("TORQUE"),
            directory="calculation",
        )
    )

    assert controller.can_calculate()

    controller.use_for_new_calculation(
        expected_structure_generation=controller.structure_generation
    )

    assert controller.scf_status() == "START"
    assert controller.can_calculate()


def test_run_calculation_does_not_apply_guided_stage_policy(monkeypatch, tmp_path):
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            input_parameters=InputParameters.create("TORQUE"),
            directory=str(tmp_path),
        )
    )

    class RunWindow:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.shown = False
            self.started = False
            self.closed = False

        def show(self):
            self.shown = True

        def start(self):
            self.started = True

        def close(self):
            self.closed = True

    monkeypatch.setattr(calculation_flow, "SprkkrRunWindow", RunWindow)

    window = calculation_flow.run_calculation(
        controller,
        RecentFiles(tmp_path / "recent.json"),
        object(),
        select_profile=False,
    )

    assert window is not None
    assert window.shown
    assert window.started
    assert not window.closed
    assert window.kwargs["request"].input_parameters.task_name.lower() == "torque"


def test_expert_run_action_uses_generic_calculation_readiness(tmp_path):
    application = QApplication.instance() or QApplication([])
    gui = GuiApplication(
        workspace=WorkspaceState(),
        recent_files_path=tmp_path / "recent.json",
    )
    expert = gui.create_main_window()
    expert.controller.replace_structure(
        Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True)
    )
    expert.controller.change_directory(str(tmp_path))
    expert.controller.replace_input_parameters(InputParameters.create("TORQUE"))
    application.processEvents()

    assert expert.run_calculation_action.isEnabled()
    expert.close()
