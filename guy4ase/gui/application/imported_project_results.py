"""Persist associations for imported outputs, independent of execution jobs."""
from __future__ import annotations

import json
from pathlib import Path

from guy4ase.gui.application.atomic_io import atomic_write_json


def assignment_path(projects) -> Path:
    return projects.directory.parent / "imported_result_projects.json"


def result_key(record) -> str | None:
    """Stable identity based on output path and captured file digest."""
    if record.output_path is None:
        return None
    version = record.output_version
    digest = getattr(version, "digest", None) if version is not None else None
    return f"{Path(record.output_path).expanduser().resolve()}::{digest or ''}"


def assignments(projects) -> dict[str, str]:
    file = assignment_path(projects)
    try:
        values = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(values, dict):
        raise ValueError("Invalid imported-result project associations")
    return {str(k): str(v) for k, v in values.items()}


def assign(projects, records, project_id: str) -> int:
    """Assign output references to one existing project."""
    projects.project(project_id)
    mapping = assignments(projects)
    keys = [key for record in records if (key := result_key(record)) is not None]
    if not keys:
        return 0
    mapping.update({key: project_id for key in keys})
    path = assignment_path(projects)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, mapping)
    return len(keys)
