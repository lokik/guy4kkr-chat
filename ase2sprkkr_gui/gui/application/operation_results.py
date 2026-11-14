"""Lightweight results produced by GUI-side operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class EmptySpheresCount:
    """Summary value for an explicit empty-sphere search."""

    count: int

    name: ClassVar[str] = "empty_spheres"
    display_name: ClassVar[str] = "Empty spheres found"
    info: ClassVar[str] = "Number of empty spheres found by the empty-sphere search."
    show_in_summary: ClassVar[bool] = True

    def value_label(self) -> str:
        return str(self.count)

    @staticmethod
    def actions() -> tuple[str, ...]:
        return ()


@dataclass(frozen=True)
class EmptySpheresResult:
    """Result of one explicit empty-sphere search/recalculation."""

    found: int

    task_name: ClassVar[str] = "empty_spheres"
    produces_potential: ClassVar[bool] = False

    @property
    def output_values(self) -> dict[str, EmptySpheresCount]:
        return {"empty_spheres": EmptySpheresCount(self.found)}
