"""Ase2sprkkr metadata for backend tasks exposed through the Guided UI."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ase2sprkkr_gui.gui.input_parameters.specs import arpes, bsf, dos, jxc, scf, xas
from ase2sprkkr_gui.gui.input_parameters.specs.schema import TaskDialogSpec


class WorkflowStage(Enum):
    """High-level workflow stage at which a Guided task is presented."""

    SCF = "scf"
    POST_SCF = "post_scf"


class WorkflowTaskRole(Enum):
    """Ase2sprkkr workflow semantics independent of a backend task key."""

    GENERIC = "generic"
    SCF = "scf"


@dataclass(frozen=True)
class WorkflowPresentation:
    """Workflow-only presentation metadata for a Guided task."""

    label: str
    description: str
    stage: WorkflowStage
    role: WorkflowTaskRole = WorkflowTaskRole.GENERIC


@dataclass(frozen=True)
class GuidedTaskDefinition:
    """Ase2sprkkr-owned metadata for one Guided task family.

    ``backend_task`` is the task used to create a fresh ASE2SPRKKR input model.
    ``compatible_backend_tasks`` lists additional concrete backend tasks sharing
    the same Guided editor. ``aliases`` are Ase2sprkkr presentation keys only and
    must never be passed to ASE2SPRKKR as task identities.
    """

    backend_task: str
    spec_builder: Callable[[bool], TaskDialogSpec]
    workflow: WorkflowPresentation
    compatible_backend_tasks: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    @property
    def backend_tasks(self) -> tuple[str, ...]:
        return (self.backend_task, *self.compatible_backend_tasks)

    def accepts_backend_task(self, task: str) -> bool:
        normalized = str(task).strip().lower()
        return normalized in self.backend_tasks

    def build_spec(self, *, is_2d: bool = False) -> TaskDialogSpec:
        spec = self.spec_builder(is_2d)
        spec.primary_pages()
        return spec


_TASKS = (
    GuidedTaskDefinition(
        "scf",
        scf.build_spec,
        WorkflowPresentation(
            "Converge SCF",
            "Prepare and run a self-consistent calculation",
            WorkflowStage.SCF,
            WorkflowTaskRole.SCF,
        ),
    ),
    GuidedTaskDefinition(
        "xas",
        xas.build_spec,
        WorkflowPresentation(
            "Calculate XAS",
            "X-ray absorption spectroscopy",
            WorkflowStage.POST_SCF,
        ),
    ),
    GuidedTaskDefinition(
        "arpes",
        arpes.build_spec,
        WorkflowPresentation(
            "Calculate ARPES",
            "Angle-resolved photoemission spectroscopy",
            WorkflowStage.POST_SCF,
        ),
    ),
    GuidedTaskDefinition(
        "dos",
        dos.build_spec,
        WorkflowPresentation(
            "Calculate DOS",
            "Electronic density of states",
            WorkflowStage.POST_SCF,
        ),
    ),
    GuidedTaskDefinition(
        "bsfek",
        bsf.build_spec,
        WorkflowPresentation(
            "Calculate BSF",
            "Bloch spectral function along an E–k path or on a k–k plane",
            WorkflowStage.POST_SCF,
        ),
        compatible_backend_tasks=("bsfkk",),
        aliases=("bsf",),
    ),
    GuidedTaskDefinition(
        "jxc",
        jxc.build_spec,
        WorkflowPresentation(
            "Calculate JXC",
            "Exchange coupling and Dzyaloshinskii–Moriya interactions",
            WorkflowStage.POST_SCF,
        ),
    ),
)
_TASKS_BY_NAME = {
    name: definition
    for definition in _TASKS
    for name in (*definition.backend_tasks, *definition.aliases)
}


def guided_task_definition(task: str) -> GuidedTaskDefinition:
    """Return Ase2sprkkr metadata for a task supported by the Guided UI."""
    normalized = str(task).strip().lower()
    try:
        return _TASKS_BY_NAME[normalized]
    except KeyError as exc:
        raise ValueError(
            f"No guided setup is defined for task {str(task).upper()}."
        ) from exc


def guided_task_definitions() -> tuple[GuidedTaskDefinition, ...]:
    """Return all Guided task definitions in presentation order."""
    return _TASKS


def is_guided_task(task: str) -> bool:
    """Return whether Ase2sprkkr provides a Guided editor for ``task``."""
    return str(task).strip().lower() in _TASKS_BY_NAME


def workflow_tasks(stage: WorkflowStage) -> tuple[GuidedTaskDefinition, ...]:
    """Return tasks presented at ``stage``.

    This is presentation policy only. It must never be used as a backend launch
    restriction: Expert mode may run any task accepted by ASE2SPRKKR.
    """
    return tuple(
        definition for definition in _TASKS if definition.workflow.stage is stage
    )
