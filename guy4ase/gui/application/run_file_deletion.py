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

from kkrunner.files.queries import remote_file_cleanup


@dataclass(frozen=True)
class FileDeletionSnapshot:
    """File identity and modification state shown when deletion was confirmed."""

    path: str
    modified_ns: int
    size: int
    device: int
    inode: int
    kind: str = "file"
    contents: tuple[tuple[str, str, int, int, int, int], ...] = ()


def snapshot_from_review(item: dict) -> FileDeletionSnapshot:
    """Preserve the exact tree the user saw, including symlinks and dates."""
    contents = tuple(
        (child["path"], child["kind"], child["mtime_ns"],
         child["size"], child["device"], child["inode"])
        for child in item.get("contents", ())
    )
    return FileDeletionSnapshot(
        item["path"], item["mtime_ns"], item["size"],
        item["device"], item["inode"], item.get("kind", "file"), contents,
    )


def expected_identity(snapshot: FileDeletionSnapshot) -> dict:
    """The target compares all descendants before recursive deletion."""
    return {
        "kind": snapshot.kind, "mtime_ns": snapshot.modified_ns,
        "size": snapshot.size, "device": snapshot.device, "inode": snapshot.inode,
        "contents": [
            {"path": path, "kind": kind, "mtime_ns": mtime,
             "size": size, "device": device, "inode": inode}
            for path, kind, mtime, size, device, inode in snapshot.contents
        ],
    }


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
    directories: tuple[str, ...] = ()
    shared_directories: tuple[str, ...] = ()
    directory_snapshots: tuple[FileDeletionSnapshot, ...] = ()
    shared_directory_snapshots: tuple[FileDeletionSnapshot, ...] = ()

    @property
    def selectable_files(self) -> tuple[str, ...]:
        """Individual local files that may be checked in the dialog."""
        return tuple(sorted((
            *self.files, *self.shared, *self.directories, *self.shared_directories,
        )))

    @property
    def selectable_snapshots(self) -> tuple[FileDeletionSnapshot, ...]:
        return (
            *self.snapshots, *self.shared_snapshots,
            *self.directory_snapshots, *self.shared_directory_snapshots,
        )

    def referrers(self, path: str) -> tuple[str, ...]:
        return dict(self.shared_referrers).get(path, ())


@dataclass(frozen=True)
class RemoteFileReview:
    """Remote identities observed asynchronously; no SSH work occurs in the dialog."""

    host: str
    snapshots: tuple[FileDeletionSnapshot, ...]
    shared: tuple[str, ...] = ()
    referrers: tuple[tuple[str, tuple[str, ...]], ...] = ()
    unavailable: tuple[tuple[str, str], ...] = ()

    def referrers_for(self, path: str) -> tuple[str, ...]:
        return dict(self.referrers).get(path, ())


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
    """Collect exact target-side manifest paths for an optional SSH cleanup."""
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


def _references_for(
    path: str, directory: bool, other_references: Iterable[str],
) -> tuple[str, ...]:
    """A directory is shared when another record refers to a descendant.

    Also protect an individual file if another run references an ancestor
    directory, because that run may own the entire directory's contents.
    """
    real = os.path.realpath(path)
    matches = []
    for candidate in other_references:
        reference = os.path.realpath(candidate)
        if reference == real or (
            directory and os.path.commonpath((real, reference)) == real
        ) or os.path.commonpath((real, reference)) == reference:
            matches.append(candidate)
    return tuple(matches)


def plan_file_deletion(
    candidates: Iterable[str],
    *,
    other_references: Iterable[str],
    remote_references: Iterable[str] = (),
    reference_details: Mapping[str, Iterable[str]] | None = None,
) -> FileDeletionPlan:
    """Preview manifest files and directories, including complete directory trees."""
    other_references = tuple(other_references)
    referrers = {
        os.path.realpath(path): tuple(sorted(set(labels)))
        for path, labels in (reference_details or {}).items()
    }
    files: list[str] = []
    shared: list[str] = []
    directories: list[str] = []
    shared_directories: list[str] = []
    unsafe: list[str] = []
    missing: list[str] = []
    snapshots: list[FileDeletionSnapshot] = []
    shared_snapshots: list[FileDeletionSnapshot] = []
    directory_snapshots: list[FileDeletionSnapshot] = []
    shared_directory_snapshots: list[FileDeletionSnapshot] = []
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
        is_dir = stat.S_ISDIR(info.st_mode)
        if not (stat.S_ISREG(info.st_mode) or is_dir):
            unsafe.append(path)
            continue
        # A symlink on the path to a declared directory could redirect
        # recursive deletion. Do not offer that entry for deletion.
        if any(parent.is_symlink() for parent in item.parents):
            unsafe.append(path)
            continue
        if is_dir:
            reviewed = remote_file_cleanup((path,))[0]
            if reviewed["status"] != "ok":
                unsafe.append(path)
                continue
            snapshot = snapshot_from_review(reviewed)
        else:
            snapshot = FileDeletionSnapshot(
                path, info.st_mtime_ns, info.st_size, info.st_dev, info.st_ino,
            )
        matches = _references_for(path, is_dir, other_references)
        if matches:
            labels = sorted({
                label
                for reference in matches
                for label in referrers.get(os.path.realpath(reference), ())
            })
            shared_details.append((path, tuple(labels)))
            if is_dir:
                shared_directories.append(path)
                shared_directory_snapshots.append(snapshot)
            else:
                shared.append(path)
                shared_snapshots.append(snapshot)
        elif is_dir:
            directories.append(path)
            directory_snapshots.append(snapshot)
        else:
            files.append(path)
            snapshots.append(snapshot)

    return FileDeletionPlan(
        tuple(files), tuple(shared), tuple(unsafe), tuple(missing),
        tuple(sorted(set(remote_references))), tuple(snapshots),
        tuple(shared_snapshots), tuple(shared_details),
        tuple(directories), tuple(shared_directories),
        tuple(directory_snapshots), tuple(shared_directory_snapshots),
    )


def delete_local_files(
    files: Iterable[str],
    *,
    snapshots: Iterable[FileDeletionSnapshot] = (),
) -> None:
    """Preflight every selected path, then remove files or complete directories.

    Recursive targets are only explicitly reviewed directory entries; never
    infer a recursive deletion from a path merely containing selected files.
    """
    selected = tuple(files)
    expected = {snap.path: snap for snap in snapshots}
    if set(selected) != set(expected):
        raise ValueError("Deletion requires an identity snapshot for every selected target")

    # Verify *all* selected trees before deleting anything.
    for path in selected:
        observed = remote_file_cleanup((path,))[0]
        snapshot = expected[path]
        if (observed["status"] != "ok"
                or expected_identity(snapshot) != {
                    key: observed[key] for key in (
                        "kind", "mtime_ns", "size", "device", "inode", "contents",
                    )
                }):
            raise OSError(f"Selected file or directory changed since confirmation: {path}")

    # A selected directory already contains selected descendants. Removing
    # children separately would invalidate the parent snapshot.
    directories = tuple(
        path for path in selected if expected[path].kind == "directory"
    )
    roots = tuple(
        path for path in selected
        if not any(
            path != directory and os.path.commonpath((path, directory)) == directory
            for directory in directories
        )
    )
    approved = {path: expected_identity(expected[path]) for path in roots}
    outcomes = remote_file_cleanup(roots, expected=approved)
    for result in outcomes:
        if result["status"] != "deleted":
            raise OSError(
                f"Could not delete {result['path']}: "
                f"{result.get('message') or result['status']}"
            )
