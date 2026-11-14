"""Architecture checks for reusable persistent-job browsing."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "ase2sprkkr_gui" / "gui"


def _tree(relative_path: str) -> ast.AST:
    return ast.parse((GUI / relative_path).read_text())


def _imports(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    return imported


def _constructed_names(tree: ast.AST) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_persistent_jobs_widget_is_presentation_only():
    tree = _tree("widgets/persistent_jobs.py")
    imports = _imports(tree)

    assert "ase2sprkkr_gui.gui.dialogs.attached_run" not in imports
    assert "ase2sprkkr_gui.gui.misc.modal_task" not in imports
    assert "ase2sprkkr_gui.gui.application.persistent_jobs" in imports

    imported_source_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "ase2sprkkr_gui.gui.application.persistent_jobs"
        for alias in node.names
    }
    assert imported_source_names == {"PersistentJob"}


def test_persistent_job_dialogs_receive_controller_instead_of_constructing_it():
    for relative_path in (
        "dialogs/calculation_history.py",
        "dialogs/project_browser.py",
    ):
        tree = _tree(relative_path)
        assert "PersistentJobsController" not in _constructed_names(tree)
        assert "ase2sprkkr_gui.gui.misc.modal_task" not in _imports(tree)
        assert "ase2sprkkr_gui.gui.dialogs.attached_run" not in _imports(tree)


def test_persistent_jobs_controller_is_the_monitor_orchestration_boundary():
    tree = _tree("controllers/persistent_jobs.py")
    imports = _imports(tree)

    assert "ase2sprkkr_gui.gui.application.persistent_jobs" in imports
    assert "ase2sprkkr_gui.gui.widgets.persistent_jobs" in imports
    assert "ase2sprkkr_gui.gui.dialogs.attached_run" in imports

    widget_tree = _tree("widgets/persistent_jobs.py")
    assert "ase2sprkkr_gui.gui.controllers.persistent_jobs" not in _imports(widget_tree)
