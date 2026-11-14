"""Translate backend SCF status encoding into Guided workflow semantics."""
from __future__ import annotations

from enum import Enum, auto


class ScfProgress(Enum):
    """Semantic SCF progress consumed by Guided workflow presentation."""

    NOT_STARTED = auto()
    ITERATING = auto()
    BULK = auto()
    LEFT_BULK = auto()
    RIGHT_BULK = auto()
    INTERACTION_ZONE = auto()
    CONVERGED = auto()
    UNKNOWN = auto()

    @property
    def can_continue(self) -> bool:
        return self in {
            ScfProgress.ITERATING,
            ScfProgress.BULK,
            ScfProgress.LEFT_BULK,
            ScfProgress.RIGHT_BULK,
            ScfProgress.INTERACTION_ZONE,
        }


_BACKEND_STATUS = {
    "ITR": ScfProgress.ITERATING,
    "ITR-BULK": ScfProgress.BULK,
    "ITR-L-BULK": ScfProgress.LEFT_BULK,
    "ITR-R-BULK": ScfProgress.RIGHT_BULK,
    "ITR-I-ZONE": ScfProgress.INTERACTION_ZONE,
}

_PROGRESS_LABELS = {
    ScfProgress.NOT_STARTED: "not converged",
    ScfProgress.ITERATING: "iterating SCF",
    ScfProgress.BULK: "converging bulk",
    ScfProgress.LEFT_BULK: "converging left bulk",
    ScfProgress.RIGHT_BULK: "converging right bulk",
    ScfProgress.INTERACTION_ZONE: "converging interaction zone",
    ScfProgress.CONVERGED: "CONVERGED",
}


def classify_scf_progress(status: str | None, *, converged: bool) -> ScfProgress:
    """Map the current backend status representation to a semantic progress value."""
    if converged:
        return ScfProgress.CONVERGED
    if status is None:
        return ScfProgress.NOT_STARTED
    normalized = str(status).strip().upper()
    if not normalized or normalized == "START":
        return ScfProgress.NOT_STARTED
    return _BACKEND_STATUS.get(normalized, ScfProgress.UNKNOWN)


def scf_progress_label(progress: ScfProgress, status: str | None = None) -> str:
    """Return user-facing progress text while preserving unknown backend states."""
    if progress is ScfProgress.UNKNOWN:
        normalized = "" if status is None else str(status).strip().upper()
        return normalized or "unknown"
    return _PROGRESS_LABELS[progress]
