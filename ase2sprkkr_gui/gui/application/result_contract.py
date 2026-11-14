"""Formal capabilities required from results recorded in calculation history."""
from __future__ import annotations

from typing import Protocol


class ResultCapabilities(Protocol):
    """Result identity and provenance capabilities consumed by ``ResultStore``."""

    @property
    def task_name(self) -> str:
        """Stable backend/operation task identity."""
        ...

    produces_potential: bool
    """Whether the result produces a potential usable by later calculations."""
