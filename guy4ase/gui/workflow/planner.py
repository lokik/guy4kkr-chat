"""Single Qt-free owner of Guided workflow availability and ordering."""
from __future__ import annotations

from typing import Any, Protocol

from guy4ase.gui.input_parameters.tasks import (
    WorkflowStage,
    WorkflowTaskRole,
    workflow_tasks,
)
from guy4ase.gui.presentation import (
    ActionCategory,
    empty_spheres_action_title,
)
from guy4ase.gui.recent_presentation import (
    RecentHistorySnapshot,
    RecentLaunchPresentation,
    recent_launch_presentation,
)
from guy4ase.gui.workflow.model import (
    ActionIcon,
    ActionMenuGroup,
    ActionMenuItem,
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
    VisualizeStructure,
    WorkflowCommand,
    WorkflowPlan,
    WorkflowSection,
)
from guy4ase.gui.workflow.scf_status import (
    ScfProgress,
    classify_scf_progress,
    scf_progress_label,
)
from guy4ase.gui.workspace_semantics import EmptySpheresAction as _EmptySpheresAction
from guy4ase.physics.composition import structure_formula
from guy4ase.physics.lattice import StructureKind


class WorkflowWorkspace(Protocol):
    """Read contract consumed from ``WorkspaceController``."""

    @property
    def atoms(self) -> Any: ...

    def structure_kind(self) -> StructureKind | None: ...

    def can_build_2d(self) -> bool: ...

    def scf_status(self) -> str | None: ...

    def is_scf_converged(self) -> bool: ...

    def empty_spheres_action(self) -> _EmptySpheresAction | None: ...

    def structure_change_requires_scf_restart(self) -> bool: ...


def _action(
    command: WorkflowCommand,
    title: str,
    description: str,
    category: ActionCategory,
    icon: ActionIcon,
    *,
    tooltip: str | None = None,
    menu: tuple[ActionMenuGroup, ...] = (),
) -> AvailableAction:
    return AvailableAction(
        command, title, description, category, icon, tooltip=tooltip, menu=menu
    )


def _recent_menu(
    presentation: RecentLaunchPresentation,
) -> tuple[ActionMenuGroup, ...]:
    """Adapt shared recent presentation data to workflow commands."""
    return tuple(
        ActionMenuGroup(
            group.title,
            tuple(
                ActionMenuItem(
                    ContinueRecent(group.kind, item.path),
                    item.label,
                    item.tooltip,
                )
                for item in group.items
            ),
            empty_text=group.empty_text,
        )
        for group in presentation.groups
    )


class WorkflowPlanner:
    """Build the complete ordered Guided workflow presentation plan."""

    def initial_plan(
        self,
        recent: RecentHistorySnapshot | None = None,
    ) -> WorkflowPlan:
        create = AvailableActionGroup(
            WorkflowSection.CREATE,
            "Create structure",
            (
                _action(
                    CreateStructure(CreateStructureKind.THREE_D),
                    "Create a 3D Structure",
                    "Build a periodic bulk crystal",
                    "structure",
                    ActionIcon.FILE,
                ),
                _action(
                    CreateStructure(CreateStructureKind.PROTOTYPE),
                    "Create Structure from Prototype Database",
                    "Start from a crystallographic structure prototype",
                    "structure",
                    ActionIcon.FILE,
                ),
                _action(
                    CreateStructure(CreateStructureKind.SURFACE),
                    "Create a 2D Surface",
                    "Build a surface with vacuum on one side",
                    "structure",
                    ActionIcon.FILE,
                ),
                _action(
                    CreateStructure(CreateStructureKind.TWO_D),
                    "Create a 2D Structure",
                    "Build an interface or transitional layer",
                    "structure",
                    ActionIcon.FILE,
                ),
            ),
        )
        load_actions = [
            _action(
                Load(LoadKind.ONLINE_STRUCTURE),
                "Download Structure from Online Database",
                "Search an online crystallographic database",
                "load",
                ActionIcon.DOWNLOAD,
            ),
            _action(
                Load(LoadKind.STRUCTURE),
                "Load a Structure",
                "Open a supported atomic structure file",
                "load",
                ActionIcon.OPEN,
            ),
            _action(
                Load(LoadKind.OUTPUT),
                "Load SPR-KKR Output",
                "Add a completed calculation to the result history",
                "load",
                ActionIcon.RESULT,
            ),
            _action(
                Load(LoadKind.OUTPUT_DIRECTORY),
                "Open SPR-KKR Output Directory",
                "Import existing calculation outputs from a directory into Results",
                "load",
                ActionIcon.OPEN,
            ),
        ]
        recent_presentation = (
            recent_launch_presentation(recent) if recent is not None else None
        )
        launch = None if recent_presentation is None else recent_presentation.primary
        if launch is not None:
            load_actions.append(
                _action(
                    ContinueRecent(launch.kind, launch.path),
                    launch.title,
                    "",
                    "load",
                    ActionIcon.CONTINUE,
                    tooltip=launch.path,
                    menu=_recent_menu(recent_presentation),
                )
            )
        return WorkflowPlan(
            "Start by creating a new atomic structure or loading an existing one.",
            (
                create,
                AvailableActionGroup(
                    WorkflowSection.LOAD,
                    "Load structure",
                    tuple(load_actions),
                ),
            ),
        )

    def for_workspace(
        self,
        workspace: WorkflowWorkspace,
        *,
        recent: RecentHistorySnapshot | None = None,
    ) -> WorkflowPlan:
        atoms = workspace.atoms
        if atoms is None:
            return self.initial_plan(recent)

        status = workspace.scf_status()
        progress = classify_scf_progress(
            status,
            converged=workspace.is_scf_converged(),
        )
        converged = progress is ScfProgress.CONVERGED
        groups: list[AvailableActionGroup] = []
        calculate: list[AvailableAction] = []

        if not converged and not workspace.structure_change_requires_scf_restart():
            empty_spheres = workspace.empty_spheres_action()
            if empty_spheres is not None:
                calculate.append(
                    _action(
                        UpdateEmptySpheres(),
                        empty_spheres_action_title(empty_spheres),
                        "Find empty spheres explicitly before the SCF calculation",
                        "structure",
                        ActionIcon.EMPTY_SPHERES,
                    )
                )

        stage = WorkflowStage.POST_SCF if converged else WorkflowStage.SCF
        for definition in workflow_tasks(stage):
            title = definition.workflow.label
            description = definition.workflow.description
            if definition.workflow.role is WorkflowTaskRole.SCF:
                if progress.can_continue:
                    title = "Continue SCF"
                    description = (
                        f"Resume from {scf_progress_label(progress)} "
                        "using the current potential"
                    )
                elif workspace.structure_kind() == "2d":
                    description = "Converge bulk region(s), then the interaction zone"
            calculate.append(
                _action(
                    RunTask(definition.backend_task),
                    title,
                    description,
                    "calculation",
                    ActionIcon.RUN,
                )
            )

        if calculate:
            groups.append(
                AvailableActionGroup(
                    WorkflowSection.CALCULATE,
                    "Calculate",
                    tuple(calculate),
                )
            )

        groups.append(
            AvailableActionGroup(
                WorkflowSection.VIEW,
                "View",
                (
                    _action(
                        VisualizeStructure(),
                        "Visualize Structure",
                        "Open the current structure in the configured ASE viewer",
                        "neutral",
                        ActionIcon.VIEW,
                    ),
                ),
            )
        )

        if workspace.can_build_2d():
            groups.append(
                AvailableActionGroup(
                    WorkflowSection.CREATE,
                    "Create derived structure",
                    (
                        _action(
                            Build2D(Build2DKind.SURFACE),
                            "Create a 2D Surface",
                            "Derive a surface from the current 3D structure",
                            "structure",
                            ActionIcon.FILE,
                        ),
                        _action(
                            Build2D(Build2DKind.STRUCTURE),
                            "Create a 2D Structure",
                            "Derive an interface or transitional layer",
                            "structure",
                            ActionIcon.FILE,
                        ),
                    ),
                )
            )

        other: list[AvailableAction] = []
        if progress is not ScfProgress.NOT_STARTED:
            other.append(
                _action(
                    UseForNewCalculation(),
                    "Use for New Calculation",
                    "Keep the current potential as starting density for a new SCF sequence",
                    "destructive",
                    ActionIcon.NEW_CALCULATION,
                )
            )
        other.append(
            _action(
                StartOver(),
                "Start Over",
                "Choose or load a different structure",
                "destructive",
                ActionIcon.RESET,
            )
        )
        groups.append(
            AvailableActionGroup(
                WorkflowSection.OTHER,
                "And now something completely different...",
                tuple(other),
            )
        )

        formula = structure_formula(atoms)
        return WorkflowPlan(
            (
                f"Current structure: {formula}  •  "
                f"SCF status: {scf_progress_label(progress, status)}"
            ),
            tuple(groups),
        )
