"""Persist associations for imported outputs, independent of execution jobs."""
from __future__ import annotations

import json
from hashlib import sha256
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


def assignments(projects) -> dict[str, str | None]:
    file = assignment_path(projects)
    try:
        values = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(values, dict):
        raise ValueError("Invalid imported-result project associations")
    return {str(k): None if v is None else str(v) for k, v in values.items()}


def assign(projects, records, project_id: str) -> int:
    """Assign output references to one existing project."""
    projects.project(project_id)
    mapping = assignments(projects)
    keys = [key for record in records if (key := result_key(record)) is not None]
    if not keys:
        return 0
    mapping.update({key: project_id for key in keys})
    _save_assignments(projects, mapping)
    return len(keys)


def reference_id(key: str) -> str:
    """Stable identity for an external file reference, never an execution run ID."""
    return "external:" + sha256(key.encode("utf-8")).hexdigest()


def reassign_references(
    projects, reference_ids, destination: str | None, *, expected_project_ids
) -> None:
    """Move file references without changing an actual calculation run."""
    if destination is not None:
        projects.project(destination)
    mapping = assignments(projects)
    identities = {reference_id(key): key for key in mapping}
    for ref_id in reference_ids:
        key = identities.get(ref_id)
        if key is None:
            raise KeyError(ref_id)
        if mapping[key] != expected_project_ids[ref_id]:
            raise ValueError(f"Project assignment changed for {ref_id}")
    for ref_id in reference_ids:
        mapping[identities[ref_id]] = destination
    _save_assignments(projects, mapping)


def remove_reference(projects, ref_id: str) -> None:
    """Forget only the project reference, not the physical output file."""
    mapping = assignments(projects)
    for key in tuple(mapping):
        if reference_id(key) == ref_id:
            del mapping[key]
            _save_assignments(projects, mapping)
            return
    raise KeyError(ref_id)


def _save_assignments(projects, mapping: dict[str, str | None]) -> None:
    path = assignment_path(projects)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, mapping)
