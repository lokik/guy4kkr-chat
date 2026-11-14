"""Plan explicit local-file removal for persisted runs and imported results.

A manifest lists references rather than exclusive ownership.  The preview
separates files referenced only by this record from shared local files and
files that must never be offered for deletion.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class FileDeletionSnapshot:
    """File identity and modification state shown when deletion was confirmed."""

    path: str
    modified_ns: int
    size: int
    device: int
    inode: int


@dataclass(frozen=True)
class FileDeletionPlan:
    """A read-only preview; authoritative references are checked again on delete."""

    files: tuple[str, ...]              # Local, ordinary, unshared files
    shared: tuple[str, ...]             # Local, ordinary, also referenced elsewhere
    unsafe: tuple[str, ...]             # Symlinks, directories, special files
    missing: tuple[str, ...]
    remote: tuple[str, ...]
    snapshots: tuple[FileDeletionSnapshot, ...] = ()
    shared_snapshots: tuple[FileDeletionSnapshot, ...] = ()
    shared_referrers: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def selectable_files(self) -> tuple[str, ...]:
        """Individual local files that may be checked in the dialog."""
        return tuple(sorted((*self.files, *self.shared)))

    @property
    def selectable_snapshots(self) -> tuple[FileDeletionSnapshot, ...]:
        return (*self.snapshots, *self.shared_snapshots)

    def referrers(self, path: str) -> tuple[str, ...]:
        return dict(self.shared_referrers).get(path, ())


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
    reference_details: Mapping[str, Iterable[str]] | None = None,
) -> FileDeletionPlan:
    """Review regular files, marking shared references without silently deleting them.

    All paths are normalized before comparing references. The caller supplies
    descriptions of other records for the UI; they do not control eligibility.
    """
    protected = {os.path.realpath(path) for path in other_references}
    referrers = {
        os.path.realpath(path): tuple(sorted(set(labels)))
        for path, labels in (reference_details or {}).items()
    }
    files: list[str] = []
    shared: list[str] = []
    unsafe: list[str] = []
    missing: list[str] = []
    snapshots: list[FileDeletionSnapshot] = []
    shared_snapshots: list[FileDeletionSnapshot] = []
    shared_details: list[tuple[str, tuple[str, ...]]] = []

    for path in sorted({_absolute(item, os.curdir) for item in candidates}):
        item = Path(path)
        if item.is_symlink():
            unsafe.append(path)
            continue
        try:
            info = os.stat(path, follow_symlinks=False)
        except FileNotFoundError:
            missing.append(path)
            continue
        if not stat.S_ISREG(info.st_mode):
            unsafe.append(path)
            continue
        snapshot = FileDeletionSnapshot(
            path, info.st_mtime_ns, info.st_size, info.st_dev, info.st_ino,
        )
        real_path = os.path.realpath(path)
        if real_path in protected:
            shared.append(path)
            shared_snapshots.append(snapshot)
            shared_details.append((path, referrers.get(real_path, ())))
        else:
            files.append(path)
            snapshots.append(snapshot)

    return FileDeletionPlan(
        tuple(files), tuple(shared), tuple(unsafe), tuple(missing),
        tuple(sorted(set(remote_references))), tuple(snapshots),
        tuple(shared_snapshots), tuple(shared_details),
    )


def delete_local_files(
    files: Iterable[str],
    *,
    snapshots: Iterable[FileDeletionSnapshot] = (),
) -> None:
    """Preflight every selected file before unlinking any of them.

    The caller has already rechecked the authoritative run references. Each
    path is verified again immediately before deletion. This minimizes partial
    cleanup if a file has changed since the user reviewed its timestamp.
    """
    selected = tuple(files)
    expected = {snapshot.path: snapshot for snapshot in snapshots}

    def verify(filename: str) -> None:
        try:
            info = os.stat(filename, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise OSError(f"Selected file disappeared since confirmation: {filename}") from exc
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"Refusing to delete a non-regular file: {filename}")
        if expected:
            snapshot = expected.get(filename)
            if snapshot is None or (
                info.st_mtime_ns, info.st_size, info.st_dev, info.st_ino
            ) != (
                snapshot.modified_ns, snapshot.size, snapshot.device, snapshot.inode
            ):
                raise OSError(f"File changed since confirmation: {filename}")

    for filename in selected:
        verify(filename)
    for filename in selected:
        verify(filename)
        Path(filename).unlink()
