from __future__ import annotations

from dataclasses import dataclass

import pytest
from ase import Atoms

from guy4ase.gui.application.workspace import WorkspaceState
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.input_parameters.tasks import (
    WorkflowStage,
    WorkflowTaskRole,
    guided_task_definition,
    workflow_tasks,
)
from guy4ase.gui.workflow.model import (
    ActionIcon,
    AvailableAction,
    AvailableActionGroup,
    Build2D,
    Build2DKind,
    ContinueRecent,
    CreateStructure,
    CreateStructureKind,
    Load,
    LoadKind,
    RunTask,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    WorkflowPlan,
    WorkflowSection,
)
from guy4ase.gui.workflow.planner import WorkflowPlanner
from guy4ase.gui.workspace_semantics import EmptySpheresAction


@dataclass
class Workspace:
    atoms: object | None = None
    status: str | None = None
    converged: bool = False
    kind: str | None = "3d"
    build_2d: bool = False
    spheres_action: EmptySpheresAction | None = None
    restart_required: bool = False

    def structure_kind(self):
        return self.kind

    def can_build_2d(self):
        return self.build_2d

    def scf_status(self):
        return self.status

    def is_scf_converged(self):
        return self.converged

    def empty_spheres_action(self):
        return self.spheres_action

    def structure_change_requires_scf_restart(self):
        return self.restart_required


@dataclass
class RecentSnapshot:
    structures: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    last_kind: str | None = None

    def paths(self, kind):
        if kind == "structure":
            return self.structures
        if kind == "output":
            return self.outputs
        return ()


class FormulaAtoms:
    def __init__(self, formula="Fe"):
        self.formula = formula

    def get_chemical_formula(self):
        return self.formula


def _commands(plan, section):
    group = plan.group(section)
    return () if group is None else tuple(action.command for action in group.actions)


def _scf_action(plan):
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    return next(
        action for action in calculate.actions if action.command == RunTask("scf")
    )


def test_initial_plan_uses_typed_commands_and_planned_recent_menu():
    history = RecentSnapshot(
        structures=("/tmp/Fe.cif",),
        outputs=("/tmp/scf.out", "/tmp/older.out"),
        last_kind="output",
    )
    plan = WorkflowPlanner().initial_plan(history)

    assert tuple(group.section for group in plan.groups) == (
        WorkflowSection.CREATE,
        WorkflowSection.LOAD,
    )
    assert _commands(plan, WorkflowSection.CREATE) == (
        CreateStructure(CreateStructureKind.THREE_D),
        CreateStructure(CreateStructureKind.PROTOTYPE),
        CreateStructure(CreateStructureKind.SURFACE),
        CreateStructure(CreateStructureKind.TWO_D),
    )
    assert _commands(plan, WorkflowSection.LOAD) == (
        Load(LoadKind.ONLINE_STRUCTURE),
        Load(LoadKind.STRUCTURE),
        Load(LoadKind.OUTPUT),
        Load(LoadKind.OUTPUT_DIRECTORY),
        ContinueRecent("output", "/tmp/scf.out"),
    )

    load = plan.group(WorkflowSection.LOAD)
    assert load is not None
    output = next(
        action for action in load.actions if action.command == Load(LoadKind.OUTPUT)
    )
    continue_action = load.actions[-1]
    assert output.icon is ActionIcon.RESULT
    directory_action = next(
        action for action in load.actions
        if action.command == Load(LoadKind.OUTPUT_DIRECTORY)
    )
    assert directory_action.title == "Open SPR-KKR Output Directory"
    assert directory_action.icon is ActionIcon.OPEN
    assert continue_action.description == ""
    assert continue_action.icon is ActionIcon.CONTINUE
    assert continue_action.tooltip == "/tmp/scf.out"
    assert tuple(group.title for group in continue_action.menu) == (
        "Structures",
        "Outputs",
    )
    assert tuple(item.command.path for item in continue_action.menu[0].items) == (
        "/tmp/Fe.cif",
    )
    assert tuple(item.command.path for item in continue_action.menu[1].items) == (
        "/tmp/scf.out",
        "/tmp/older.out",
    )
    assert all(
        item.tooltip == item.command.path
        for group in continue_action.menu
        for item in group.items
    )


def test_initial_recent_menu_keeps_empty_kind_visible():
    plan = WorkflowPlanner().initial_plan(
        RecentSnapshot(structures=("/tmp/Fe.cif",), last_kind="structure")
    )
    load = plan.group(WorkflowSection.LOAD)
    assert load is not None
    recent_action = load.actions[-1]

    assert recent_action.menu[0].items
    assert recent_action.menu[1].items == ()
    assert recent_action.menu[1].empty_text == "(No recent files)"


def test_current_structure_plan_has_canonical_group_order_without_output_loader():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), build_2d=True)
    )

    assert tuple(group.section for group in plan.groups) == (
        WorkflowSection.CALCULATE,
        WorkflowSection.VIEW,
        WorkflowSection.CREATE,
        WorkflowSection.OTHER,
    )
    assert plan.group(WorkflowSection.LOAD) is None
    assert all(
        command != Load(LoadKind.OUTPUT)
        for group in plan.groups
        for command in (action.command for action in group.actions)
    )


def test_calculation_order_follows_guided_task_metadata():
    before = WorkflowPlanner().for_workspace(
        Workspace(
            atoms=FormulaAtoms(),
            spheres_action=EmptySpheresAction.RECALCULATE,
        )
    )
    assert _commands(before, WorkflowSection.CALCULATE) == (
        UpdateEmptySpheres(),
        RunTask("scf"),
    )

    after = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), converged=True)
    )
    assert _commands(after, WorkflowSection.CALCULATE) == tuple(
        RunTask(definition.backend_task)
        for definition in workflow_tasks(WorkflowStage.POST_SCF)
    )


def test_registry_presentation_is_used_without_local_task_catalogue():
    definition = guided_task_definition("dos")
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), converged=True)
    )
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    action = next(
        item
        for item in calculate.actions
        if item.command == RunTask(definition.backend_task)
    )
    assert action.title == definition.workflow.label
    assert action.description == definition.workflow.description


def test_scf_workflow_behavior_is_declared_by_semantic_role():
    definition = guided_task_definition("scf")
    assert definition.workflow.role is WorkflowTaskRole.SCF
    assert all(
        candidate.workflow.role is not WorkflowTaskRole.SCF
        for candidate in workflow_tasks(WorkflowStage.POST_SCF)
    )


def test_run_task_keeps_backend_lookup_key_opaque_and_unmodified():
    assert RunTask("SCF").backend_task == "SCF"
    assert RunTask("scf").backend_task == "scf"
    with pytest.raises(ValueError, match="non-empty string"):
        RunTask("   ")


def test_continue_recent_is_semantic_and_validates_kind():
    command = ContinueRecent("structure", "/tmp/Fe.cif")
    assert command.kind == "structure"
    assert command.path == "/tmp/Fe.cif"
    with pytest.raises(ValueError, match="continuation kind"):
        ContinueRecent("input", "/tmp/input.inp")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "description"),
    (
        ("ITR", "Resume from iterating SCF using the current potential"),
        ("ITR-BULK", "Resume from converging bulk using the current potential"),
        (
            "ITR-L-BULK",
            "Resume from converging left bulk using the current potential",
        ),
        (
            "ITR-R-BULK",
            "Resume from converging right bulk using the current potential",
        ),
        (
            "ITR-I-ZONE",
            "Resume from converging interaction zone using the current potential",
        ),
    ),
)
def test_interrupted_scf_preserves_exact_stage(status, description):
    action = _scf_action(
        WorkflowPlanner().for_workspace(Workspace(atoms=FormulaAtoms(), status=status))
    )
    assert action.title == "Continue SCF"
    assert action.description == description


def test_unknown_scf_status_remains_visible_for_forward_compatibility():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), status="future-status")
    )

    assert "SCF status: FUTURE-STATUS" in plan.subtitle
    assert UseForNewCalculation() in _commands(plan, WorkflowSection.OTHER)


def test_initial_2d_scf_uses_contextual_description():
    action = _scf_action(
        WorkflowPlanner().for_workspace(Workspace(atoms=FormulaAtoms(), kind="2d"))
    )
    assert action.description == "Converge bulk region(s), then the interaction zone"


def test_empty_sphere_recommendation_is_consumed_from_workspace_policy():
    plan = WorkflowPlanner().for_workspace(
        Workspace(
            atoms=FormulaAtoms(),
            spheres_action=EmptySpheresAction.ADD,
        )
    )
    assert _commands(plan, WorkflowSection.CALCULATE)[0] == UpdateEmptySpheres()

    restart = WorkflowPlanner().for_workspace(
        Workspace(
            atoms=FormulaAtoms(),
            status="ITR",
            spheres_action=EmptySpheresAction.RECALCULATE,
            restart_required=True,
        )
    )
    assert all(
        not isinstance(command, UpdateEmptySpheres)
        for command in _commands(restart, WorkflowSection.CALCULATE)
    )


def test_real_controller_pending_restart_maps_to_fresh_scf_plan():
    controller = WorkspaceController(
        WorkspaceState(
            atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True),
            restarted=True,
        )
    )

    plan = WorkflowPlanner().for_workspace(controller)

    assert "SCF status: not converged" in plan.subtitle
    assert _scf_action(plan).command == RunTask("scf")
    assert _scf_action(plan).title == guided_task_definition("scf").workflow.label
    assert UseForNewCalculation() not in _commands(plan, WorkflowSection.OTHER)
    assert _commands(plan, WorkflowSection.OTHER)[-1] == StartOver()


def test_real_controller_build_2d_capability_drives_derived_structure_commands():
    controller = WorkspaceController(
        WorkspaceState(atoms=Atoms("Fe", cell=(2.8, 2.8, 2.8), pbc=True))
    )

    plan = WorkflowPlanner().for_workspace(controller)

    assert _commands(plan, WorkflowSection.CREATE) == (
        Build2D(Build2DKind.SURFACE),
        Build2D(Build2DKind.STRUCTURE),
    )


def test_workflow_plan_rejects_duplicate_sections():
    action = AvailableAction(
        StartOver(),
        "Start Over",
        "Choose a different structure",
        "destructive",
        ActionIcon.RESET,
    )
    first = AvailableActionGroup(WorkflowSection.OTHER, "Other", (action,))
    second = AvailableActionGroup(WorkflowSection.OTHER, "Again", (action,))

    with pytest.raises(ValueError, match="each section at most once"):
        WorkflowPlan("subtitle", (first, second))
