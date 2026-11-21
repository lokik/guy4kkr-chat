"""Single Qt-free owner of Guided workflow availability and ordering."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from ase2sprkkr import InputParameters
from ase2sprkkr_gui.gui.input_parameters.task_preferences import (
    all_task_names, displayed_tasks, supported_task_names,
)
from ase2sprkkr_gui.gui.input_parameters.tasks import (
    WorkflowTaskRole, guided_task_definition, is_guided_task,
)
from ase2sprkkr_gui.gui.presentation import (
    ActionCategory,
    empty_spheres_action_title,
    structure_kind_label,
)
from ase2sprkkr_gui.gui.recent_presentation import (
    RecentHistorySnapshot,
    RecentLaunchPresentation,
    recent_launch_presentation,
    recent_menu_items,
)
from ase2sprkkr_gui.gui.workflow.model import (
    ActionIcon,
    ActionMenuGroup,
    ActionMenuItem,
    AvailableAction,
    AvailableActionGroup,
    Build2D,
    Build2DKind,
    BuildEmbedding,
    ExplainEmbedding,
    ConvergeHostScf,
    ContinueRecent,
    LoadAllRecentResults,
    RepeatRecentInput,
    CreateStructure,
    CreateStructureKind,
    Load,
    LoadKind,
    RunTask,
    ReconvergeScf,
    CustomTask,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    VisualizeStructure,
    EditStructure,
    SaveStructure,
    LoadHostPotential,
    AttachHostPotential,
    CreateHostPotential,
    WorkflowCommand,
    WorkflowPlan,
    WorkflowSection,
)
from ase2sprkkr_gui.gui.workflow.scf_status import (
    ScfProgress,
    classify_scf_progress,
    scf_progress_label,
)
from ase2sprkkr_gui.gui.workspace_semantics import EmptySpheresAction as _EmptySpheresAction
from ase2sprkkr_gui.physics.composition import structure_formula
from ase2sprkkr_gui.physics.lattice import StructureKind


class WorkflowWorkspace(Protocol):
    """Read contract consumed from ``WorkspaceController``."""

    @property
    def atoms(self) -> Any: ...

    def structure_kind(self) -> StructureKind | None: ...

    def can_build_2d(self) -> bool: ...

    def can_build_embedding(self) -> bool: ...

    def can_run_embedding(self) -> bool: ...

    def embedding_host_scf_status(self) -> str | None: ...

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
            footer=(
                ActionMenuItem(LoadAllRecentResults(), "Load all results")
                if group.kind == "output" and group.items else None
            ),
        )
        for group in presentation.groups
    )


def _custom_group(
    has_structure: bool,
    recent: RecentHistorySnapshot | None = None,
) -> AvailableActionGroup:
    actions = [
        _action(
            CustomTask(),
            "Custom calculation" if has_structure else "Custom input file",
            "Choose any registered SPR-KKR task; edit or save input without requiring Guided support.",
            "calculation", ActionIcon.FILE,
        )
    ]
    # A repeatable input is independent of the active structure.
    inputs = recent_menu_items(recent.paths("input")) if recent is not None else ()
    actions.append(_action(
        RepeatRecentInput(inputs[0].path if inputs else None),
        "Repeat calculation",
        f"From {Path(inputs[0].path).name}" if inputs else "No recent input files",
        "calculation", ActionIcon.CONTINUE,
        tooltip=inputs[0].path if inputs else None,
        menu=(ActionMenuGroup(
            "Inputs",
            tuple(
                ActionMenuItem(
                    RepeatRecentInput(item.path), item.label, item.tooltip
                )
                for item in inputs
            ),
            empty_text="(No recent inputs)",
        ),),
    ))
    return AvailableActionGroup(WorkflowSection.CUSTOM, "Custom", tuple(actions))

class WorkflowPlanner:
    """Build the complete ordered Guided workflow presentation plan."""

    def __init__(self, settings=None) -> None:
        self.settings = settings

    def _preferred(self) -> tuple[str, ...]:
        return (
            supported_task_names() if self.settings is None
            else self.settings.effective_preferred_tasks()
        )

    def initial_plan(
        self,
        recent: RecentHistorySnapshot | None = None,
        *,
        read_only_cluster: str | None = None,
    ) -> WorkflowPlan:
        if read_only_cluster is not None:
            return WorkflowPlan(
                f"CLUPOT loaded read-only: {read_only_cluster}. "
                "Attach its host POTFIL before editing or calculating.",
                (
                    AvailableActionGroup(
                        WorkflowSection.CREATE, "Create / attach host",
                        (
                            _action(
                                AttachHostPotential(), "Attach Matching Host Potential",
                                "Complete this CLUPOT with an existing matching host POTFIL",
                                "structure", ActionIcon.OPEN,
                            ),
                            _action(
                                LoadHostPotential(), "Load Host as Structure",
                                "Replace this cluster with the selected periodic host",
                                "structure", ActionIcon.OPEN,
                            ),
                            _action(
                                CreateHostPotential(), "Create Host Potential",
                                "Build a matching periodic host and generate its POTFIL",
                                "structure", ActionIcon.BULK_CRYSTAL,
                            ),
                        ),
                    ),
                    AvailableActionGroup(
                        WorkflowSection.LOAD, "Load another structure",
                        (
                            _action(
                                Load(LoadKind.STRUCTURE), "Load a Structure",
                                "Open another structure instead of this CLUPOT",
                                "load", ActionIcon.OPEN,
                            ),
                        ),
                    ),
                    _custom_group(False, recent),
                ),
            )
        create_actions = (
            _action(
                CreateStructure(CreateStructureKind.THREE_D),
                "Create a 3D Structure",
                "Build a periodic bulk crystal",
                "structure",
                ActionIcon.BULK_CRYSTAL,
            ),
            _action(
                CreateStructure(CreateStructureKind.PROTOTYPE),
                "Create Structure from Prototype Database",
                "Start from a crystallographic structure prototype",
                "structure",
                ActionIcon.DATABASE,
            ),
            _action(
                CreateStructure(CreateStructureKind.SHELL),
                "Create by Python Shell",
                "Build an ASE structure interactively in Python",
                "structure",
                ActionIcon.SHELL,
            ),
            _action(
                CreateStructure(CreateStructureKind.SURFACE),
                "Create a 2D Surface",
                "Build a surface with vacuum on one side",
                "structure",
                ActionIcon.SURFACE,
            ),
            _action(
                CreateStructure(CreateStructureKind.TWO_D),
                "Create a 2D Structure",
                "Build an interface or transitional layer",
                "structure",
                ActionIcon.INTERFACE,
            ),
        )
        if self.settings is None or self.settings.show_embedded_cluster_hint:
            create_actions += (
                _action(
                    ExplainEmbedding(), "Create Embedded Cluster",
                    "First prepare a periodic bulk or 2D host structure",
                    "structure", ActionIcon.EMBEDDING,
                ),
            )
        create = AvailableActionGroup(
            WorkflowSection.CREATE, "Create structure", create_actions
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
                "Load SPR-KKR Result",
                "Add a completed calculation to the result history",
                "load",
                ActionIcon.RESULT,
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
            "",
            (
                create,
                AvailableActionGroup(
                    WorkflowSection.LOAD,
                    "Load structure",
                    tuple(load_actions),
                ),
                _custom_group(False, recent),
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
            path = getattr(workspace, "unresolved_cluster_path", None)
            return self.initial_plan(
                recent,
                read_only_cluster=str(path) if path is not None else None,
            )

        status = workspace.scf_status()
        progress = classify_scf_progress(
            status,
            converged=workspace.is_scf_converged(),
        )
        converged = progress is ScfProgress.CONVERGED
        groups: list[AvailableActionGroup] = []
        calculate: list[AvailableAction] = []

        is_cluster = workspace.structure_kind() == "0d"
        invalid_cluster = is_cluster and getattr(atoms, "embedding_host", None) is None
        host_status = (
            getattr(workspace, "embedding_host_scf_status", lambda: None)()
            if is_cluster and not invalid_cluster else None
        )
        host_needs_initial_scf = host_status == "START"
        host_not_converged = host_status not in (None, "START", "CONVERGED")
        if not is_cluster and not converged and not workspace.structure_change_requires_scf_restart():
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

        if host_needs_initial_scf or host_not_converged:
            continuing = host_not_converged and host_status != "START"
            calculate.append(_action(
                ConvergeHostScf(),
                "Continue Host SCF" if continuing else "Converge Host SCF",
                ("Complete the periodic host SCF before running the embedded cluster."
                 if continuing else
                 "Converge the periodic host potential before calculating the cluster."),
                "calculation", ActionIcon.RUN,
            ))

        # Workflow readiness and preference are independent. Preserve the
        # native embedded ITERATING exception, which also permits DOS.
        if converged:
            eligible = tuple(name for name in all_task_names() if name != "SCF")
        elif is_cluster and progress is ScfProgress.ITERATING:
            eligible = all_task_names()
        else:
            eligible = ("SCF",)
        kind = "embedded" if is_cluster else workspace.structure_kind()
        names = (
            () if invalid_cluster or host_needs_initial_scf
            else displayed_tasks(kind, self._preferred(), eligible=eligible)
        )
        for name in names:
            if is_guided_task(name):
                definition = guided_task_definition(name)
                title = (
                    definition.workflow.label
                    if name.lower() == definition.backend_task
                    else f"Calculate {name}"
                )
                description = definition.workflow.description
                scf = definition.workflow.role is WorkflowTaskRole.SCF
            else:
                title = f"Calculate {name}"
                try:
                    definition = InputParameters.input_parameters_registry.definition_for_task(
                        InputParameters.task_registry[name]
                    )
                    description = getattr(definition, "info", "") or "Configure a native SPR-KKR task"
                except (AttributeError, KeyError, ValueError):
                    description = "Configure a native SPR-KKR task"
                scf = name == "SCF"
            if scf:
                if progress.can_continue:
                    title = "Continue SCF"
                    description = (
                        f"Resume from {scf_progress_label(progress)} "
                        "using the current potential"
                    )
                elif workspace.structure_kind() == "2d":
                    description = "Converge bulk region(s), then the interaction zone"
            if is_cluster and not getattr(workspace, "can_run_embedding", lambda: False)():
                description += " (requires a matching host POTFIL)"
            elif host_not_converged:
                description += " (warning: host SCF has not converged; results may be unreliable)"
            calculate.append(
                _action(
                    RunTask(name.lower()), title, str(description),
                    "calculation", ActionIcon.RUN,
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

        groups.append(_custom_group(True, recent))

        structure_actions = []
        if not invalid_cluster:
            structure_actions.append(
                _action(
                    EditStructure(),
                    "Edit Structure",
                    "Edit site occupations, lattice, geometry and embedded structures",
                    "structure",
                    ActionIcon.EDIT,
                )
            )
        structure_actions.append(
            _action(
                VisualizeStructure(),
                "Visualize Structure",
                "Open the current structure in the configured ASE viewer",
                "neutral",
                ActionIcon.VIEW,
            )
        )
        structure_actions.append(
            _action(
                SaveStructure(),
                "Save Structure",
                "Write the current structure to a file without calculating",
                "neutral",
                ActionIcon.SAVE,
            )
        )
        groups.append(
            AvailableActionGroup(
                WorkflowSection.VIEW,
                "Structure",
                tuple(structure_actions),
            )
        )

        derived: list[AvailableAction] = []
        if workspace.can_build_2d():
            derived.extend((
                _action(
                    Build2D(Build2DKind.SURFACE),
                    "Create a 2D Surface",
                    "Derive a surface from the current 3D structure",
                    "structure",
                    ActionIcon.SURFACE,
                ),
                _action(
                    Build2D(Build2DKind.STRUCTURE),
                    "Create a 2D Structure",
                    "Derive an interface or transitional layer",
                    "structure",
                    ActionIcon.INTERFACE,
                ),
            ))
        # Some test/third-party workspace adapters predate this capability.
        if not invalid_cluster and getattr(workspace, "can_build_embedding", lambda: False)():
            derived.append(_action(
                BuildEmbedding(),
                "Edit Embedded Cluster" if is_cluster else "Build Embedded Cluster",
                "Choose host cells, substitute sites and expand symmetry/relaxation shells",
                "structure",
                ActionIcon.EMBEDDING,
            ))
        missing_native_host = (
            is_cluster and not invalid_cluster
            and not getattr(workspace, "can_run_embedding", lambda: False)()
        )
        if missing_native_host:
            derived[:0] = [
                _action(
                    AttachHostPotential(), "Attach Matching Host Potential",
                    "Attach a matching host POTFIL to the embedded cluster",
                    "structure", ActionIcon.OPEN,
                ),
                _action(
                    LoadHostPotential(), "Load Host as Structure",
                    "Replace the embedded cluster with this periodic host",
                    "structure", ActionIcon.OPEN,
                ),
                _action(
                    CreateHostPotential(), "Create Host Potential",
                    "Generate a host POTFIL from the host geometry",
                    "structure", ActionIcon.BULK_CRYSTAL,
                ),
            ]
        if derived:
            groups.append(AvailableActionGroup(
                WorkflowSection.CREATE,
                "Create / attach host" if missing_native_host
                else "Derived structures", tuple(derived),
            ))

        other: list[AvailableAction] = []
        if is_cluster and not invalid_cluster and host_status not in (None, "START"):
            other.append(_action(
                ConvergeHostScf(restart_scf=True),
                "Re-converge Host SCF",
                "Restart the periodic host SCF from its current potential.",
                "calculation", ActionIcon.NEW_CALCULATION,
            ))
        if converged:
            other.append(_action(
                ReconvergeScf(),
                "Re-converge SCF",
                "Restart SCF from the current converged potential without first resetting the workspace.",
                "calculation", ActionIcon.NEW_CALCULATION,
            ))
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
        kind_label = structure_kind_label(workspace.structure_kind())
        kind_note = f"  •  Structure type: {kind_label}" if kind_label else ""
        host_note = (
            "  •  Host SCF: START (must be converged first)"
            if host_needs_initial_scf else
            f"  •  Host SCF: {host_status} (not converged; embedding results may be unreliable)"
            if host_not_converged else ""
        )
        return WorkflowPlan(
            ("Invalid embedded structure: the host reference is missing. "
             "Reload or rebuild it from the original host structure."
             if invalid_cluster else
             f"Current structure: {formula}{kind_note}  •  "
             f"SCF status: {scf_progress_label(progress, status)}{host_note}"),
            tuple(groups),
        )
