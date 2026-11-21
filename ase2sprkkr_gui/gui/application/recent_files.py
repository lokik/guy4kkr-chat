"""Observable persistent recent-file history without window dependencies."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
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
        self.remember_many(((kind, file_path),))

    def remember_many(
        self,
        entries: Iterable[tuple[RecentKind, str | Path]],
        *,
        preserve_last_kind: bool = False,
    ) -> None:
        """Register related files with one persistence write and change signal."""
        previous = self.read_snapshot()
        for kind, file_path in entries:
            normalized = _canonical_path(file_path)
            recent = self._files[kind]
            recent[:] = [item for item in recent if item != normalized]
            recent.insert(0, normalized)
            del recent[self.limit :]
            if not preserve_last_kind and kind in {"structure", "output"}:
                self.last_kind = kind
        if self.read_snapshot() != previous:
            self.save()
            self.changed.emit()

    def remember_result(
        self,
        output_path: str | Path | None,
        *,
        potential_path: str | Path | None = None,
    ) -> None:
        """Record a result and its successfully loaded potential as one update.

        The output is registered last so Continue still defaults to the result,
        rather than the associated structure.
        """
        entries: list[tuple[RecentKind, str | Path]] = []
        if potential_path is not None:
            entries.append(("structure", potential_path))
        if output_path is not None:
            entries.append(("output", output_path))
        self.remember_many(entries)

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

    def remove_known_missing(
        self,
        snapshot: RecentFilesSnapshot,
        missing: Mapping[RecentKind, tuple[str, ...]],
    ) -> bool:
        """Apply a background check atomically, only to unchanged history.

        The worker must never touch this QObject or repeat filesystem checks
        on the GUI thread. Emit one change for the entire cleanup.
        """
        if snapshot != self.read_snapshot():
            return False
        changed = False
        for kind in RECENT_KINDS:
            absent = set(missing.get(kind, ()))
            if not absent:
                continue
            retained = [path for path in self._files[kind] if path not in absent]
            if len(retained) != len(self._files[kind]):
                self._files[kind] = retained
                changed = True
        if changed:
            self._repair_last_kind()
            self.save()
            self.changed.emit()
        return changed

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

def find_missing_recent_paths(
    snapshot: RecentFilesSnapshot,
) -> dict[RecentKind, tuple[str, ...]]:
    """Inspect a copied history off the GUI thread; never create Qt widgets.

    Only definitive missing-file errors qualify for removal. A temporarily
    unavailable or permission-denied network mount retains its history.
    """
    missing: dict[RecentKind, tuple[str, ...]] = {}
    for kind in RECENT_KINDS:
        absent = []
        for path in snapshot.paths(kind):
            try:
                Path(path).stat()
            except (FileNotFoundError, NotADirectoryError):
                absent.append(path)
            except OSError:
                # An inaccessible filesystem is not proof the file was deleted.
                continue
        if absent:
            missing[kind] = tuple(absent)
    return missing
