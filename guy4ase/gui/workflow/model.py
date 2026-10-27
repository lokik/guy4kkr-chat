"""Typed presentation contract between Guided workflow planning and Qt rendering."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal, Union

from guy4ase.gui.presentation import ActionCategory


class CreateStructureKind(Enum):
    THREE_D = auto()
    PROTOTYPE = auto()
    SURFACE = auto()
    TWO_D = auto()


class Build2DKind(Enum):
    SURFACE = auto()
    STRUCTURE = auto()


class LoadKind(Enum):
    ONLINE_STRUCTURE = auto()
    STRUCTURE = auto()
    OUTPUT = auto()
    OUTPUT_DIRECTORY = auto()


class WorkflowSection(Enum):
    CALCULATE = auto()
    VIEW = auto()
    CREATE = auto()
    LOAD = auto()
    OTHER = auto()


class ActionIcon(Enum):
    RUN = auto()
    EMPTY_SPHERES = auto()
    OPEN = auto()
    DOWNLOAD = auto()
    FILE = auto()
    RESULT = auto()
    VIEW = auto()
    CONTINUE = auto()
    NEW_CALCULATION = auto()
    RESET = auto()


ContinueRecentKind = Literal["structure", "output"]


@dataclass(frozen=True)
class RunTask:
    """Run a task using the opaque key accepted by the backend task API."""

    backend_task: str

    def __post_init__(self) -> None:
        if not isinstance(self.backend_task, str) or not self.backend_task.strip():
            raise ValueError("Workflow task key must be a non-empty string.")


@dataclass(frozen=True)
class UpdateEmptySpheres:
    pass


@dataclass(frozen=True)
class CreateStructure:
    kind: CreateStructureKind


@dataclass(frozen=True)
class Build2D:
    kind: Build2DKind


@dataclass(frozen=True)
class Load:
    kind: LoadKind


@dataclass(frozen=True)
class ContinueRecent:
    """Continue from a recent structure or output without presentation coupling."""

    kind: ContinueRecentKind
    path: str

    def __post_init__(self) -> None:
        if self.kind not in {"structure", "output"}:
            raise ValueError("Recent continuation kind must be 'structure' or 'output'.")


@dataclass(frozen=True)
class VisualizeStructure:
    pass


@dataclass(frozen=True)
class UseForNewCalculation:
    pass


@dataclass(frozen=True)
class StartOver:
    pass


WorkflowCommand = Union[
    RunTask,
    UpdateEmptySpheres,
    CreateStructure,
    Build2D,
    Load,
    ContinueRecent,
    VisualizeStructure,
    UseForNewCalculation,
    StartOver,
]


@dataclass(frozen=True)
class ActionMenuItem:
    """One command entry in an action's already-resolved popup menu."""

    command: WorkflowCommand
    title: str
    tooltip: str | None = None


@dataclass(frozen=True)
class ActionMenuGroup:
    """One named popup-menu group in a workflow action."""

    title: str
    items: tuple[ActionMenuItem, ...]
    empty_text: str | None = None

    def __post_init__(self) -> None:
        if not self.items and self.empty_text is None:
            raise ValueError("Empty workflow menu groups require fallback text.")


@dataclass(frozen=True)
class AvailableAction:
    command: WorkflowCommand
    title: str
    description: str
    category: ActionCategory
    icon: ActionIcon
    tooltip: str | None = None
    menu: tuple[ActionMenuGroup, ...] = ()


@dataclass(frozen=True)
class AvailableActionGroup:
    section: WorkflowSection
    title: str
    actions: tuple[AvailableAction, ...]

    def __post_init__(self) -> None:
        if not self.actions:
            raise ValueError("Workflow action groups must not be empty.")


@dataclass(frozen=True)
class WorkflowPlan:
    subtitle: str
    groups: tuple[AvailableActionGroup, ...]

    def __post_init__(self) -> None:
        sections = tuple(group.section for group in self.groups)
        if len(set(sections)) != len(sections):
            raise ValueError("Workflow plan must contain each section at most once.")

    def group(self, section: WorkflowSection) -> AvailableActionGroup | None:
        for group in self.groups:
            if group.section is section:
                return group
        return None
