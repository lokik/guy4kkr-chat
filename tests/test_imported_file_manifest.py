"""Parsed imported outputs retain a real file manifest across project operations."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kkrunner.files import FileState
from ase2sprkkr.outputs import TaskResult
from guy4ase.gui.application.result_store import ResultStore
from kkrunner.projects import ProjectRepository

from guy4ase.gui.application.imported_project_results import (
    assign, assignments, reference_id, references, reassign_references,
)
from guy4ase.gui.application.persistent_jobs import PersistentJobSource


def _record(folder: Path, stem: str, potential: Path):
    output = folder / f"{stem}.out"
    inp = folder / f"{stem}.inp"
    converged = folder / f"{stem}.pot_new"
    dos = folder / f"{stem}.dos"
    for file in (output, inp, converged, dos):
        file.write_text(file.name)
    parsed = TaskResult(
        None, None, str(folder), output_file=str(output), task_name="SCF",
    )
    parsed.files.add_file("input", inp.name)
    parsed.files.add_file("potential", potential.name)
    parsed.files.add_file("converged", converged.name)
    parsed.files.add_file("DOS", dos.name, "dos")
    return ResultStore().add_external_result(
        parsed, atoms=None, input_parameters=None,
        directory=str(folder), output_path=output,
        potential_path=converged,
    )


def _source(projects):
    store = SimpleNamespace(runs=lambda: (), get=lambda ref: None)
    return PersistentJobSource(SimpleNamespace(store=store), projects=projects)


def test_import_captures_parser_files_and_persists_manifest(tmp_path):
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Experiment")
    start_potential = tmp_path / "start.pot"
    start_potential.write_text("shared input")
    record = _record(tmp_path, "run", start_potential)
    assert record.file_manifest is not None
    assert assign(projects, (record,), project.id) == 1

    reloaded = references(ProjectRepository(tmp_path / "projects"))
    assert len(reloaded) == 1
    key, ref = next(iter(reloaded.items()))
    assert ref.project_id == project.id
    assert ref.task == "scf"
    assert assignments(projects) == {key: project.id}
    manifest = ref.files
    assert manifest is not None
    assert manifest.stdout.local_path == str(record.output_path)
    assert {Path(entry.local_path).name for entry in manifest.inputs} == {
        "run.inp", "start.pot",
    }
    assert {Path(entry.local_path).name for entry in manifest.outputs} == {
        "run.pot_new", "run.dos",
    }
    assert {version.path.name for version in manifest.output_versions} == {
        "run.out", "run.pot_new", "run.dos",
    }
    assert manifest.state is FileState.CURRENT

    source = _source(projects)
    imported = source.job(reference_id(key))
    assert imported.task == "scf"
    plan = source.referenced_file_deletion(imported.id)
    assert set(plan.files) == {
        str(record.output_path), str(tmp_path / "run.inp"),
        str(tmp_path / "run.pot_new"), str(tmp_path / "run.dos"),
        str(start_potential),
    }


def test_shared_imported_input_is_protected_and_reassignment_preserves_manifest(tmp_path):
    projects = ProjectRepository(tmp_path / "projects")
    first = projects.create("Original")
    second = projects.create("Destination")
    potential = tmp_path / "start.pot"
    potential.write_text("shared")
    a = _record(tmp_path, "a", potential)
    b = _record(tmp_path, "b", potential)
    assert assign(projects, (a, b), first.id) == 2
    key_a = next(key for key in references(projects) if key.startswith(str(a.output_path)))
    ref_id = reference_id(key_a)
    reassign_references(
        projects, (ref_id,), second.id,
        expected_project_ids={ref_id: first.id},
    )
    ref = references(projects)[key_a]
    assert ref.project_id == second.id
    assert ref.files is not None
    source = _source(projects)
    plan = source.referenced_file_deletion(ref_id)
    assert str(potential) in plan.shared
    assert str(potential) not in plan.files
    assert str(a.output_path) in plan.files

    a.output_path.write_text("replaced")
    checked = source.check_result_files(ref_id)
    assert checked.result_files_verified
    assert checked.result_files_state == FileState.OVERWRITTEN.value


def test_legacy_reference_remains_readable_and_uses_output_fallback(tmp_path):
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Old")
    output = tmp_path / "legacy.out"
    output.write_text("legacy")
    from guy4ase.gui.application.atomic_io import atomic_write_json
    from guy4ase.gui.application.imported_project_results import assignment_path

    key = f"{output}::"
    atomic_write_json(assignment_path(projects), {key: project.id})
    assert references(projects)[key].files is None
    source = _source(projects)
    plan = source.referenced_file_deletion(reference_id(key))
    assert plan.files == (str(output),)
