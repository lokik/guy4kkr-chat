"""Qt-independent presentation policy for recently used files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Protocol

RecentFileKind = Literal["structure", "input", "output"]
RecentLaunchKind = Literal["structure", "output"]
RECENT_MENU_EMPTY_TEXT = "(No recent files)"


class RecentHistorySnapshot(Protocol):
    """Immutable read contract consumed by recent-file presentation policy."""

    @property
    def last_kind(self) -> str | None: ...

    def paths(self, kind: RecentFileKind) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class RecentLaunch:
    """One recent structure/output that may be continued."""

    kind: RecentLaunchKind
    path: str

    def __post_init__(self) -> None:
        if self.kind not in {"structure", "output"}:
            raise ValueError("Recent launch kind must be 'structure' or 'output'.")

    @property
    def title(self) -> str:
        return f"Continue: {Path(self.path).name}"


@dataclass(frozen=True)
class RecentMenuItem:
    """Presentation data for one recent-file menu entry."""

    path: str
    label: str
    tooltip: str


@dataclass(frozen=True)
class RecentLaunchGroup:
    """One named group in the shared Continue-recent menu."""

    title: str
    kind: RecentLaunchKind
    items: tuple[RecentMenuItem, ...]
    empty_text: str = RECENT_MENU_EMPTY_TEXT


@dataclass(frozen=True)
class RecentLaunchPresentation:
    """Complete shared presentation snapshot for continuing recent work."""

    primary: RecentLaunch | None
    groups: tuple[RecentLaunchGroup, ...]


def recent_path_label(path: str | Path, base: str | Path | None = None) -> str:
    """Prefer a short descendant path; never display ``..``-based relatives."""
    absolute = Path(path).expanduser().resolve()
    absolute_text = str(absolute)
    base_path = Path.cwd() if base is None else Path(base).expanduser().resolve()
    try:
        relative = absolute.relative_to(base_path)
    except ValueError:
        return absolute_text
    relative_text = str(relative)
    return relative_text if len(relative_text) < len(absolute_text) else absolute_text


def recent_menu_items(
    paths: Iterable[str | Path],
    *,
    base: str | Path | None = None,
) -> tuple[RecentMenuItem, ...]:
    """Build immutable menu presentation items from canonical recent paths."""
    return tuple(
        RecentMenuItem(
            path=str(path),
            label=recent_path_label(path, base),
            tooltip=str(path),
        )
        for path in paths
    )


def _preferred_recent_launch(snapshot: RecentHistorySnapshot) -> RecentLaunch | None:
    structures = snapshot.paths("structure")
    outputs = snapshot.paths("output")
    if not structures and not outputs:
        return None

    last_kind = snapshot.last_kind
    if last_kind == "structure" and structures:
        return RecentLaunch("structure", structures[0])
    if last_kind == "output" and outputs:
        return RecentLaunch("output", outputs[0])
    if outputs:
        return RecentLaunch("output", outputs[0])
    return RecentLaunch("structure", structures[0])


def recent_launch_presentation(
    snapshot: RecentHistorySnapshot,
    *,
    base: str | Path | None = None,
) -> RecentLaunchPresentation:
    """Build a complete Continue-recent presentation from one immutable snapshot."""
    groups = (
        RecentLaunchGroup(
            "Structures",
            "structure",
            recent_menu_items(snapshot.paths("structure"), base=base),
        ),
        RecentLaunchGroup(
            "Outputs",
            "output",
            recent_menu_items(snapshot.paths("output"), base=base),
        ),
    )
    return RecentLaunchPresentation(_preferred_recent_launch(snapshot), groups)
