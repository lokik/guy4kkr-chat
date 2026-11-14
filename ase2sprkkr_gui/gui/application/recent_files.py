"""Observable persistent recent-file history without window dependencies."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PyQt6.QtCore import QObject, pyqtSignal

from ase2sprkkr_gui.gui.application.atomic_io import atomic_write_json
from ase2sprkkr_gui.gui.application.config import config_home

RecentKind = Literal["structure", "input", "output"]
RECENT_KINDS: tuple[RecentKind, ...] = ("structure", "input", "output")

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecentFilesSnapshot:
    """Immutable read snapshot of all recent-file history and selection state."""

    structure: tuple[str, ...]
    input: tuple[str, ...]
    output: tuple[str, ...]
    last_kind: RecentKind | None

    def paths(self, kind: RecentKind) -> tuple[str, ...]:
        """Return the paths captured for one recent-file kind."""
        return {
            "structure": self.structure,
            "input": self.input,
            "output": self.output,
        }[kind]


def default_recent_files_path() -> Path:
    """Return the per-user history path used by the application."""
    return config_home() / "recent_files.json"


def _canonical_path(file_path: str | Path) -> str:
    """Return a stable absolute path suitable for persisted history."""
    return str(Path(file_path).expanduser().resolve())


class RecentFiles(QObject):
    """Load, normalize, persist and publish bounded recent-file lists."""

    changed = pyqtSignal()

    def __init__(
        self,
        path: Path | None = None,
        *,
        limit: int = 10,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if limit < 1:
            raise ValueError("Recent-file limit must be positive.")
        self.path = path or default_recent_files_path()
        self.limit = limit
        self._files: dict[RecentKind, list[str]] = {
            kind: [] for kind in RECENT_KINDS
        }
        self.last_kind: RecentKind | None = None

    def paths(self, kind: RecentKind) -> tuple[str, ...]:
        """Return an immutable snapshot for one file kind."""
        return tuple(self._files[kind])

    @property
    def snapshot(self) -> dict[str, tuple[str, ...]]:
        """Return the established paths-only snapshot API."""
        return {kind: tuple(self._files[kind]) for kind in RECENT_KINDS}

    def read_snapshot(self) -> RecentFilesSnapshot:
        """Capture paths and recent-launch selection in one immutable value."""
        return RecentFilesSnapshot(
            structure=tuple(self._files["structure"]),
            input=tuple(self._files["input"]),
            output=tuple(self._files["output"]),
            last_kind=self.last_kind,
        )

    @staticmethod
    def _normalize(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(
            dict.fromkeys(_canonical_path(str(item)) for item in value)
        )

    def load(self) -> None:
        """Load history; corrupt or unreadable caches behave as empty."""
        self._files = {kind: [] for kind in RECENT_KINDS}
        self.last_kind = None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return

        if isinstance(data, list):  # legacy structure-only format
            self._files["structure"] = self._normalize(data)[: self.limit]
            return
        if not isinstance(data, dict):
            return
        values = data.get("recent_files")
        if isinstance(values, dict):
            for kind in RECENT_KINDS:
                self._files[kind] = self._normalize(values.get(kind))[: self.limit]
        last_kind = data.get("last_recent_kind")
        if last_kind in {"structure", "output"}:
            self.last_kind = last_kind

    def save(self) -> None:
        """Persist history and log a cache-write failure without breaking file I/O."""
        try:
            atomic_write_json(
                self.path,
                {
                    "recent_files": self._files,
                    "last_recent_kind": self.last_kind,
                },
            )
        except OSError:
            _logger.exception("Failed to save recent files to %s", self.path)

    def remember(self, kind: RecentKind, file_path: str | Path) -> None:
        """Move a canonical path to the front and persist the bounded history."""
        normalized = _canonical_path(file_path)
        recent = self._files[kind]
        previous = tuple(recent)
        previous_last_kind = self.last_kind
        recent[:] = [item for item in recent if item != normalized]
        recent.insert(0, normalized)
        del recent[self.limit :]
        if kind in {"structure", "output"}:
            self.last_kind = kind
        if tuple(recent) == previous and self.last_kind == previous_last_kind:
            return
        self.save()
        self.changed.emit()

    def forget(self, kind: RecentKind, file_path: str | Path) -> None:
        """Remove one canonical path and persist only if the history changed."""
        normalized = _canonical_path(file_path)
        previous = self._files[kind]
        retained = [item for item in previous if item != normalized]
        if retained == previous:
            return
        self._files[kind] = retained
        self._repair_last_kind()
        self.save()
        self.changed.emit()

    def remove_missing(self, kinds: Iterable[RecentKind] = RECENT_KINDS) -> None:
        """Remove paths which no longer exist and persist any change."""
        changed = False
        for kind in kinds:
            retained = [path for path in self._files[kind] if Path(path).exists()]
            if retained != self._files[kind]:
                self._files[kind] = retained
                changed = True
        if changed:
            self._repair_last_kind()
            self.save()
            self.changed.emit()

    def _repair_last_kind(self) -> None:
        if self.last_kind is not None and not self._files[self.last_kind]:
            if self._files["output"]:
                self.last_kind = "output"
            elif self._files["structure"]:
                self.last_kind = "structure"
            else:
                self.last_kind = None
