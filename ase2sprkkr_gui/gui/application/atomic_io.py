"""Atomic filesystem writes shared by small persistence stores."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _fsync_directory(directory: Path) -> None:
    """Best-effort durability barrier for a directory entry update."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            # Some platforms/filesystems do not support fsync on directories.
            pass
    finally:
        os.close(descriptor)


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Atomically replace *path* after flushing file and directory metadata.

    The temporary file lives next to the destination so :func:`os.replace` is
    an atomic same-filesystem operation. A write/flush failure therefore leaves
    an existing destination untouched. This protects file integrity only; it
    deliberately does not serialize concurrent writers.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
        _fsync_directory(destination.parent)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    indent: int | None = 2,
) -> None:
    """Serialize JSON and atomically replace *path*."""
    atomic_write_text(path, json.dumps(data, indent=indent))
