"""Plan explicit local-file removal for persisted runs and imported results.

A manifest describes paths, not exclusive ownership.  Only individual regular
files explicitly referenced by the selected record may be removed; references
held by any other run or imported result protect the corresponding file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FileDeletionSnapshot:
    """File identity and modification state shown to the user at confirmation."""

    path: str
    modified_ns: int
    size: int
    device: int
    inode: int


@dataclass(frozen=True)
class FileDeletionPlan:
    """A read-only preview; it is recalculated before an actual deletion."""

    files: tuple[str, ...]
    shared: tuple[str, ...]
    unsafe: tuple[str, ...]
    missing: tuple[str, ...]
    remote: tuple[str, ...]
    snapshots: tuple[FileDeletionSnapshot, ...] = ()


def _absolute(path: str, directory: str) -> str:
    return os.path.abspath(os.path.join(directory, os.fspath(path)))


def referenced_local_paths(manifest, directory: str) -> tuple[str, ...]:
    """All local manifest paths, including input, cache and captured versions."""
    if manifest is None:
        return ()
    entries = (
        *manifest.inputs, *manifest.outputs, *(cache.file for cache in manifest.caches),
        manifest.stdin, manifest.stdout, manifest.stderr,
    )
    paths = [
        _absolute(entry.local_path, directory)
        for entry in entries
        if entry is not None and entry.local_path is not None
    ]
    paths.extend(
        _absolute(version.path, directory)
        for version in (*manifest.input_versions, *manifest.output_versions)
    )
    return tuple(sorted(set(paths)))


def referenced_remote_paths(manifest) -> tuple[str, ...]:
    """Report remote references; GUI cleanup does not have remote deletion rights."""
    if manifest is None:
        return ()
    entries = (
        *manifest.inputs, *manifest.outputs, *(cache.file for cache in manifest.caches),
        manifest.stdin, manifest.stdout, manifest.stderr,
    )
    return tuple(sorted({
        entry.remote_path for entry in entries
        if entry is not None and entry.remote_path is not None
    }))


def plan_file_deletion(
    candidates: Iterable[str],
    *,
    other_references: Iterable[str],
    remote_references: Iterable[str] = (),
) -> FileDeletionPlan:
    """Select only existing, unshared, ordinary files for an explicit cleanup."""
    protected = {os.path.realpath(path) for path in other_references}
    files: list[str] = []
    snapshots: list[FileDeletionSnapshot] = []
    shared: list[str] = []
    unsafe: list[str] = []
    missing: list[str] = []
    for path in sorted({_absolute(item, os.curdir) for item in candidates}):
        item = Path(path)
        if os.path.realpath(path) in protected:
            shared.append(path)
        elif item.is_symlink():
            unsafe.append(path)
        elif not item.exists():
            missing.append(path)
        elif not item.is_file():
            unsafe.append(path)
        else:
            try:
                stat = os.stat(item, follow_symlinks=False)
            except FileNotFoundError:
                missing.append(path)
                continue
            snapshots.append(FileDeletionSnapshot(
                path, stat.st_mtime_ns, stat.st_size, stat.st_dev, stat.st_ino,
            ))
            files.append(path)
    return FileDeletionPlan(
        tuple(files), tuple(shared), tuple(unsafe), tuple(missing),
        tuple(sorted(set(remote_references))), tuple(snapshots),
    )


def delete_local_files(files: Iterable[str]) -> None:
    """Delete a confirmed preview. Never unlink a directory or a symlink."""
    for filename in files:
        path = Path(filename)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise OSError(f"Refusing to delete a non-regular file: {path}")
        path.unlink(missing_ok=True)
