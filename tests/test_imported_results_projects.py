"""Directory import and project association regressions."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from kkrunner.projects import ProjectRepository

from ase2sprkkr_gui.gui.application.imported_project_results import assign, assignments
from ase2sprkkr_gui.gui.application.recent_files import RecentFiles
from ase2sprkkr_gui.gui.application.result_loading import LoadedResult
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.flows import files as file_flows


def _app():
    return QApplication.instance() or QApplication([])


def test_imported_result_project_assignment_persists(tmp_path):
    repo = ProjectRepository(tmp_path / "projects")
    project = repo.create("Experiment")
    path = tmp_path / "run.out"
    path.write_text("test")
    record = SimpleNamespace(output_path=path, output_version=None)
    assert assign(repo, [record], project.id) == 1
    assert list(assignments(ProjectRepository(tmp_path / "projects")).values()) == [
        project.id
    ]


def test_directory_import_skips_unparseable_files_and_keeps_workspace(
    tmp_path, monkeypatch,
):
    _application = _app()
    controller = WorkspaceController()
    history = RecentFiles(tmp_path / "recent.json")
    folder = tmp_path / "results"
    folder.mkdir()
    for name in ("b.out", "a.out", "notes.log"):
        (folder / name).write_text(name)
    seen = []

    def fake_load(path):
        seen.append(path.name)
        if path.name == "notes.log":
            raise ValueError("not an SPR-KKR output")
        return SimpleNamespace(path=path)

    adopted = []
    monkeypatch.setattr(file_flows, "load_result_file", fake_load)
    monkeypatch.setattr(
        file_flows, "run_modal_task",
        lambda parent, task, **kwargs: task(),
    )
    monkeypatch.setattr(
        controller, "adopt_external_result",
        lambda loaded, *, select_result: adopted.append((loaded.path.name, select_result)),
    )
    monkeypatch.setattr(file_flows.QMessageBox, "warning", lambda *a, **kw: None)
    monkeypatch.setattr(file_flows.QMessageBox, "information", lambda *a, **kw: None)
    directory_before = controller.directory

    imported = file_flows.load_output_directory(controller, history, folder, None)

    assert [path.name for path in imported] == ["a.out", "b.out"]
    assert seen == ["a.out", "b.out", "notes.log"]
    assert adopted == [("a.out", False), ("b.out", True)]
    assert controller.directory == directory_before


def test_assigning_tracked_result_moves_existing_run_without_imported_duplicate(
    tmp_path, monkeypatch,
):
    from PyQt6.QtWidgets import QDialog, QMessageBox
    from ase2sprkkr_gui.gui.dialogs.assign_results import (
        AssignResultsDialog, assign_results_to_project,
    )

    _application = _app()
    projects = ProjectRepository(tmp_path / "projects")
    source_project = projects.create("Old")
    target = projects.create("Target")
    record = SimpleNamespace(persistent_ref="run-1", output_path=tmp_path / "run.out")
    result_store = SimpleNamespace(result=lambda result_id: record)
    job = SimpleNamespace(project_id=source_project.id, imported_path=None)
    calls = []
    run_source = SimpleNamespace(
        job=lambda ref: job if ref == "run-1" else None,
        reassign_runs=lambda *args, **kw: calls.append((args, kw)),
    )

    def choose_target(dialog):
        dialog.project.setCurrentIndex(dialog.project.findData(target.id))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AssignResultsDialog, "exec", choose_target)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    assert assign_results_to_project(
        projects, result_store, (1,), run_source=run_source
    )
    assert len(calls) == 1
    assert calls[0][0] == (projects, ("run-1",), target.id)
    assert calls[0][1]["expected_project_ids"] == {"run-1": source_project.id}
    assert assignments(projects) == {}


def test_project_browser_file_import_uses_existing_output_loader(
    tmp_path, monkeypatch,
):
    from PyQt6.QtWidgets import QFileDialog, QWidget
    from ase2sprkkr_gui.main import GuiApplication

    _application = _app()
    projects = ProjectRepository(tmp_path / "projects")
    project = projects.create("Experiment")
    output = tmp_path / "old-output.out"
    output.write_text("stored output")
    record = SimpleNamespace(output_path=output, output_version=None)
    loaded_calls, reloaded = [], []
    browser = QWidget()
    app = SimpleNamespace(
        _project_browser=browser, projects=projects, recent_files=object(),
        controller=SimpleNamespace(
            result_store=SimpleNamespace(results=(record,)),
        ),
        persistent_jobs=SimpleNamespace(reload=lambda: reloaded.append(True)),
    )
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *args: (str(output), "SPR-KKR Output Files"),
    )
    monkeypatch.setattr(
        file_flows, "load_output",
        lambda controller, recent, filename, parent: loaded_calls.append(filename) or True,
    )
    GuiApplication._add_result_to_project(app, project.id)

    assert loaded_calls == [str(output)]
    assert list(assignments(projects).values()) == [project.id]
    assert reloaded == [True]
    browser.close()
