from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _method_calls(path: Path, class_name: str, method_name: str) -> set[str]:
    tree = ast.parse(path.read_text())
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    return {
        node.func.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_gui_application_composes_result_presenter_without_owning_refresh():
    main_path = ROOT / "ase2sprkkr_gui" / "main.py"
    calls = _method_calls(main_path, "GuiApplication", "_wire_result_actions")

    assert "set_model" not in calls
    assert "set_result" not in calls
    assert "set_results" not in calls
    assert "set_workspace_state" not in calls

    source = main_path.read_text()
    assert "ResultActionsPresenter(" in source
    assert "present_result_tree" not in source


def test_result_presenter_is_the_authoritative_refresh_owner():
    path = ROOT / "ase2sprkkr_gui" / "gui" / "presenters" / "result_actions.py"
    source = path.read_text()

    assert "controller.structureChanged.connect(self.refresh)" in source
    assert "controller.resultChanged.connect(self.refresh)" in source
    assert "present_result_tree(" in source
