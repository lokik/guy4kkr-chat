"""Persist project associations and file manifests for imported outputs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from kkrunner.files import FileManifest

from guy4ase.gui.application.atomic_io import atomic_write_json


@dataclass(frozen=True)
class ImportedReference:
    """A parsed external output and its project, not an executed run."""

    project_id: str | None
    files: FileManifest | None = None
    task: str | None = None


def assignment_path(projects) -> Path:
    return projects.directory.parent / "imported_result_projects.json"


def result_key(record) -> str | None:
    """Stable identity based on output path and captured file digest."""
    if record.output_path is None:
        return None
    version = record.output_version
    digest = getattr(version, "digest", None) if version is not None else None
    return f"{Path(record.output_path).expanduser().resolve()}::{digest or ''}"


def references(projects) -> dict[str, ImportedReference]:
    """Read current records and legacy project-only assignments."""
    try:
        values = json.loads(assignment_path(projects).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(values, dict):
        raise ValueError("Invalid imported-result project associations")
    result = {}
    for key, value in values.items():
        if isinstance(value, dict):
            project_id = value.get("project_id")
            files = value.get("files")
            task = value.get("task")
            if files is not None and not isinstance(files, dict):
                raise ValueError(f"Invalid imported-result manifest for {key}")
            result[str(key)] = ImportedReference(
                None if project_id is None else str(project_id),
                FileManifest(**files) if files is not None else None,
                None if task is None else str(task),
            )
        elif value is None or isinstance(value, str):
            result[str(key)] = ImportedReference(value)
        else:
            raise ValueError(f"Invalid imported-result association for {key}")
    return result


def assignments(projects) -> dict[str, str | None]:
    """Compatibility projection for project assignments."""
    return {key: ref.project_id for key, ref in references(projects).items()}


def assign(projects, records, project_id: str) -> int:
    """Save parsed file manifests together with project assignments."""
    projects.project(project_id)
    mapping = references(projects)
    count = 0
    for record in records:
        key = result_key(record)
        if key is None:
            continue
        task = getattr(record, "task_name", None)
        mapping[key] = ImportedReference(
            project_id=project_id,
            files=getattr(record, "file_manifest", None),
            task=None if task is None else str(task),
        )
        count += 1
    if count:
        _save_references(projects, mapping)
    return count


def reference_id(key: str) -> str:
    """Stable identity for an external file reference, never an execution run ID."""
    return "external:" + sha256(key.encode("utf-8")).hexdigest()


def reassign_references(
    projects, reference_ids, destination: str | None, *, expected_project_ids
) -> None:
    """Move file references without changing their captured file manifests."""
    if destination is not None:
        projects.project(destination)
    mapping = references(projects)
    identities = {reference_id(key): key for key in mapping}
    for ref_id in reference_ids:
        key = identities.get(ref_id)
        if key is None:
            raise KeyError(ref_id)
        if mapping[key].project_id != expected_project_ids[ref_id]:
            raise ValueError(f"Project assignment changed for {ref_id}")
    for ref_id in reference_ids:
        key = identities[ref_id]
        ref = mapping[key]
        mapping[key] = ImportedReference(destination, ref.files, ref.task)
    _save_references(projects, mapping)


def remove_reference(projects, ref_id: str) -> None:
    """Forget only the project reference, not the physical output file."""
    mapping = references(projects)
    for key in tuple(mapping):
        if reference_id(key) == ref_id:
            del mapping[key]
            _save_references(projects, mapping)
            return
    raise KeyError(ref_id)


def _manifest_to_json(manifest: FileManifest) -> dict:
    """Serialize file identity without reinterpreting any parsed SPR-KKR paths."""
    data = asdict(manifest)
    for version in (*data["input_versions"], *data["output_versions"]):
        version["path"] = str(version["path"])
    return data


def _save_references(projects, mapping: dict[str, ImportedReference]) -> None:
    path = assignment_path(projects)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Legacy project-only entries remain readable, without inventing a manifest.
    values = {
        key: (
            {
                "project_id": ref.project_id,
                "files": _manifest_to_json(ref.files),
                "task": ref.task,
            }
            if ref.files is not None else ref.project_id
        )
        for key, ref in mapping.items()
    }
    atomic_write_json(path, values)
