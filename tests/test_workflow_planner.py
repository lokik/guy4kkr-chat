from __future__ import annotations

from dataclasses import dataclass

import pytest
from ase import Atoms

from ase2sprkkr_gui.gui.application.workspace import WorkspaceState
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.input_parameters.tasks import (
    WorkflowStage,
    WorkflowTaskRole,
    guided_task_definition,
    workflow_tasks,
)
from ase2sprkkr_gui.gui.workflow.model import (
    ActionIcon,
    ActionMenuItem,
    AvailableAction,
    AvailableActionGroup,
    Build2D,
    Build2DKind,
    BuildEmbedding,
    ExplainEmbedding,
    ContinueRecent,
    LoadAllRecentResults,
    RepeatRecentInput,
    CreateStructure,
    CreateStructureKind,
    EditStructure,
    Load,
    LoadKind,
    LoadHostPotential,
    AttachHostPotential,
    CreateHostPotential,
    RunTask,
    ReconvergeScf,
    SaveStructure,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    VisualizeStructure,
    WorkflowPlan,
    WorkflowSection,
)
from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner
from ase2sprkkr_gui.gui.workspace_semantics import EmptySpheresAction


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
    inputs: tuple[str, ...] = ()
    last_kind: str | None = None

    def paths(self, kind):
        if kind == "structure":
            return self.structures
        if kind == "output":
            return self.outputs
        if kind == "input":
            return self.inputs
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

    assert plan.subtitle == ""
    assert tuple(group.section for group in plan.groups) == (
        WorkflowSection.CREATE,
        WorkflowSection.LOAD,
        WorkflowSection.CUSTOM,
    )
    assert _commands(plan, WorkflowSection.CREATE) == (
        CreateStructure(CreateStructureKind.THREE_D),
        CreateStructure(CreateStructureKind.PROTOTYPE),
        CreateStructure(CreateStructureKind.SHELL),
        CreateStructure(CreateStructureKind.SURFACE),
        CreateStructure(CreateStructureKind.TWO_D),
        ExplainEmbedding(),
    )
    assert _commands(plan, WorkflowSection.LOAD) == (
        Load(LoadKind.ONLINE_STRUCTURE),
        Load(LoadKind.STRUCTURE),
        Load(LoadKind.OUTPUT),
        ContinueRecent("output", "/tmp/scf.out"),
    )

    load = plan.group(WorkflowSection.LOAD)
    assert load is not None
    output = next(
        action for action in load.actions if action.command == Load(LoadKind.OUTPUT)
    )
    continue_action = load.actions[-1]
    assert output.icon is ActionIcon.RESULT
    assert continue_action.description == ""
    assert continue_action.icon is ActionIcon.CONTINUE
    assert continue_action.tooltip == "/tmp/scf.out"
    assert tuple(group.title for group in continue_action.menu) == (
        "Structures",
        "Results",
    )
    assert tuple(item.command.path for item in continue_action.menu[0].items) == (
        "/tmp/Fe.cif",
    )
    assert tuple(item.command.path for item in continue_action.menu[1].items) == (
        "/tmp/scf.out",
        "/tmp/older.out",
    )
    assert continue_action.menu[0].footer is None
    assert continue_action.menu[1].footer == ActionMenuItem(
        LoadAllRecentResults(), "Load all results",
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
    assert recent_action.menu[1].footer is None


def test_recent_input_is_repeated_from_custom_not_continue():
    plan = WorkflowPlanner().initial_plan(RecentSnapshot(
        inputs=("/tmp/first.inp", "/tmp/second.inp"),
        outputs=("/tmp/result.out",),
        last_kind="input",
    ))
    load = plan.group(WorkflowSection.LOAD)
    assert load is not None
    assert isinstance(load.actions[-1].command, ContinueRecent)
    assert load.actions[-1].command.kind == "output"
    assert [group.title for group in load.actions[-1].menu] == [
        "Structures", "Results",
    ]

    custom = plan.group(WorkflowSection.CUSTOM)
    assert custom is not None
    repeat = custom.actions[1]
    assert repeat.title == "Repeat calculation"
    assert repeat.command == RepeatRecentInput("/tmp/first.inp")
    assert [item.command for item in repeat.menu[0].items] == [
        RepeatRecentInput("/tmp/first.inp"),
        RepeatRecentInput("/tmp/second.inp"),
    ]


def test_current_structure_plan_has_canonical_group_order_without_output_loader():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), build_2d=True)
    )

    assert tuple(group.section for group in plan.groups) == (
        WorkflowSection.CALCULATE,
        WorkflowSection.CUSTOM,
        WorkflowSection.VIEW,
        WorkflowSection.CREATE,
        WorkflowSection.OTHER,
    )
    assert plan.group(WorkflowSection.LOAD) is None
    assert plan.group(WorkflowSection.VIEW).title == "Structure"
    assert _commands(plan, WorkflowSection.VIEW) == (
        EditStructure(),
        VisualizeStructure(),
        SaveStructure(),
    )
    assert all(
        command != Load(LoadKind.OUTPUT)
        for group in plan.groups
        for command in (action.command for action in group.actions)
    )


def test_calculation_order_follows_default_preferred_tasks():
    from ase2sprkkr_gui.gui.input_parameters.task_preferences import supported_task_names

    before = WorkflowPlanner().for_workspace(
        Workspace(
            atoms=FormulaAtoms(),
            spheres_action=EmptySpheresAction.RECALCULATE,
        )
    )
    assert _commands(before, WorkflowSection.CALCULATE) == (
        UpdateEmptySpheres(), RunTask("scf"),
    )
    assert ReconvergeScf() not in _commands(before, WorkflowSection.OTHER)

    after = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), converged=True)
    )
    assert _commands(after, WorkflowSection.CALCULATE) == tuple(
        RunTask(name.lower()) for name in supported_task_names() if name != "SCF"
    )
    assert ReconvergeScf() in _commands(after, WorkflowSection.OTHER)
    assert UseForNewCalculation() in _commands(after, WorkflowSection.OTHER)


def test_scf_readiness_precedes_preferred_task_selection():
    from types import SimpleNamespace

    def with_preference(name, converged):
        settings = SimpleNamespace(effective_preferred_tasks=lambda: (name,))
        return WorkflowPlanner(settings=settings).for_workspace(
            Workspace(atoms=FormulaAtoms(), converged=converged)
        )

    # Choosing only DOS cannot hide the required SCF step.
    assert _commands(
        with_preference("DOS", converged=False), WorkflowSection.CALCULATE
    ) == (RunTask("scf"),)

    # Choosing only SCF cannot resurrect that action after convergence.
    after = with_preference("SCF", converged=True)
    commands = _commands(after, WorkflowSection.CALCULATE)
    assert RunTask("scf") not in commands
    assert RunTask("dos") in commands


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
    assert RepeatRecentInput("/tmp/input.inp").path == "/tmp/input.inp"
    with pytest.raises(ValueError, match="continuation kind"):
        ContinueRecent("invalid", "/tmp/bad")  # type: ignore[arg-type]


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



@pytest.mark.parametrize("status", ("ITR", "ITERATING", "ITR-BULK"))
def test_periodic_iteration_only_offers_continue_scf(status):
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), status=status, kind="3d")
    )
    assert _commands(plan, WorkflowSection.CALCULATE) == (RunTask("scf"),)
    assert _scf_action(plan).title == "Continue SCF"


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
        BuildEmbedding(),
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


def test_embedded_structure_plan_offers_cluster_scf_and_save_without_host_potential():
    class EmbeddingWorkspace(Workspace):
        def can_build_embedding(self):
            return True

        def can_run_embedding(self):
            return False

    atoms = FormulaAtoms()
    atoms.embedding_host = object()  # Geometry exists, but POTFIL is not attached.
    plan = WorkflowPlanner().for_workspace(
        EmbeddingWorkspace(atoms=atoms, kind="0d", build_2d=False)
    )
    assert RunTask("scf") in _commands(plan, WorkflowSection.CALCULATE)
    assert "host POTFIL" in _scf_action(plan).description
    assert _commands(plan, WorkflowSection.CREATE) == (
        AttachHostPotential(), LoadHostPotential(), CreateHostPotential(), BuildEmbedding(),
    )
    assert _commands(plan, WorkflowSection.VIEW)[-1] == SaveStructure()


def test_no_host_recovery_action_for_an_invalid_orphan_cluster():
    class CorruptCluster(Workspace):
        def can_build_embedding(self):
            return False

        def can_run_embedding(self):
            return False

    plan = WorkflowPlanner().for_workspace(
        CorruptCluster(atoms=FormulaAtoms(), kind="0d")
    )
    assert plan.group(WorkflowSection.CREATE) is None
    assert _commands(plan, WorkflowSection.CALCULATE) == ()
    assert EditStructure() not in _commands(plan, WorkflowSection.VIEW)
    assert "host" in plan.subtitle.lower()


def test_native_host_does_not_offer_redundant_attachment():
    class ReadyCluster(Workspace):
        def can_build_embedding(self):
            return True

        def can_run_embedding(self):
            return True

    atoms = FormulaAtoms()
    atoms.embedding_host = object()
    plan = WorkflowPlanner().for_workspace(
        ReadyCluster(atoms=atoms, kind="0d")
    )
    assert _commands(plan, WorkflowSection.CREATE) == (BuildEmbedding(),)


def test_cluster_task_filter_requires_explicit_task_support(monkeypatch):
    from types import SimpleNamespace
    from ase2sprkkr_gui.gui.input_parameters.task_preferences import displayed_tasks
    from ase2sprkkr_gui.gui.workflow import planner as planning

    class Registry(dict):
        def names(self):
            return tuple(self)

    fake_registry = Registry({
        name: SimpleNamespace(name=name, executable=executable, supports=supports)
        for name, executable, supports in (
            ("SCF", "kkrscf", {"3d", "2d", "embedded"}),
            ("DOS", "kkrgen", {"3d", "2d", "embedded"}),
            ("XAS", "kkrgen", {"3d", "2d"}),
            ("ARPES", "kkrspec", {"3d", "2d"}),
            ("BSFEK", "kkrgen", {"3d", "2d"}),
            ("JXC", "kkrgen", {"3d", "2d"}),
        )
    })
    monkeypatch.setattr(planning.InputParameters, "task_registry", fake_registry)
    assert displayed_tasks("embedded", ("XAS", "SCF", "DOS")) == (
        "SCF", "DOS",
    )


def test_read_only_clupot_offers_explicit_attachment_and_replacement():
    class Hostless(Workspace):
        unresolved_cluster_path = "/tmp/imported.clu"
        atoms = None

    workspace = Hostless(atoms=None)
    plan = WorkflowPlanner().for_workspace(workspace)
    create = _commands(plan, WorkflowSection.CREATE)
    assert create == (AttachHostPotential(), LoadHostPotential(), CreateHostPotential())
    assert _commands(plan, WorkflowSection.CALCULATE) == ()
    assert "read-only" in plan.subtitle.lower()
    assert "imported.clu" in plan.subtitle


def test_default_bsf_is_one_action_for_both_native_modes():
    plan = WorkflowPlanner().for_workspace(
        Workspace(atoms=FormulaAtoms(), converged=True)
    )
    calculate = plan.group(WorkflowSection.CALCULATE)
    assert calculate is not None
    bsf = [action for action in calculate.actions
           if action.command == RunTask("bsf")]
    assert len(bsf) == 1
    assert bsf[0].title == "Calculate BSF"
    assert not any(
        action.command in (RunTask("bsfek"), RunTask("bsfkk"))
        for action in calculate.actions
    )



def test_repeat_calculation_is_always_present_for_loaded_and_empty_workspaces():
    planner = WorkflowPlanner()
    empty = planner.initial_plan()
    repeat = empty.group(WorkflowSection.CUSTOM).actions[1]
    assert repeat.command == RepeatRecentInput(None)
    assert repeat.menu[0].items == ()
    assert repeat.menu[0].empty_text == "(No recent inputs)"

    history = RecentSnapshot(inputs=("/tmp/Fe_scf.inp",))
    loaded = planner.for_workspace(Workspace(atoms=FormulaAtoms()), recent=history)
    repeat = loaded.group(WorkflowSection.CUSTOM).actions[1]
    assert repeat.command == RepeatRecentInput("/tmp/Fe_scf.inp")
    assert repeat.menu[0].items[0].command == repeat.command
