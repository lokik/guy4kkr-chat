"""Directory import and project association regressions."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from ase2sprkkr.execution import ProjectRepository

from guy4ase.gui.application.imported_project_results import assign, assignments
from guy4ase.gui.application.recent_files import RecentFiles
from guy4ase.gui.application.result_loading import LoadedResult
from guy4ase.gui.application.workspace_controller import WorkspaceController
from guy4ase.gui.flows import files as file_flows


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
