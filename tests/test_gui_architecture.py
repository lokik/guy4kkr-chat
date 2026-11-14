"""Stable architectural and component-contract checks for the GUI."""
import ast
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ase2sprkkr_gui-test-matplotlib")

import numpy as np
import pytest
from ase import Atoms
from ase2sprkkr.common.grammar_types import Energy, Real
from ase2sprkkr.input_parameters.input_parameters import InputParameters
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.ase.element_assignment import ElementAssignmentDraft
from ase2sprkkr_gui.gui.input_parameters.field_binding import SessionFieldBinding
from ase2sprkkr_gui.gui.input_parameters.session import InputParametersSession
from ase2sprkkr_gui.gui.input_parameters.specs.schema import field
from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.widgets.input_parameters.registry import editor_for_type
from ase2sprkkr_gui.gui.widgets.structures.element_assignment import QLetterRow

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "ase2sprkkr_gui" / "gui"


def _gui_graph():
    """Return the static import graph between modules inside ``ase2sprkkr_gui.gui``."""
    modules = {}
    for path in GUI.rglob("*.py"):
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        package = path.name == "__init__.py"
        if package:
            module = module.removesuffix(".__init__")
        modules[module] = (path, package)

    graph = {module: set() for module in modules}
    for module, (path, package) in modules.items():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = importlib.util.resolve_name(
                        "." * node.level + base,
                        module if package else module.rpartition(".")[0],
                    )
                targets = [base] + [
                    base + "." + alias.name for alias in node.names
                ]
            else:
                continue
            graph[module].update(target for target in targets if target in modules)
    return graph


def _reachable(graph, start):
    """Return all GUI modules reachable from ``start`` in the import graph."""
    reached = set()
    pending = list(graph[start])
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        pending.extend(graph[module] - reached)
    return reached


def test_gui_dependencies_are_acyclic_and_follow_layers():
    """Keep broad layer boundaries without pinning individual implementations."""
    graph = _gui_graph()
    for module, targets in graph.items():
        if module.startswith("ase2sprkkr_gui.gui.widgets"):
            assert not any(
                target.startswith(
                    (
                        "ase2sprkkr_gui.gui.controllers",
                        "ase2sprkkr_gui.gui.dialogs",
                        "ase2sprkkr_gui.gui.flows",
                    )
                )
                for target in targets
            ), module
        if module.startswith("ase2sprkkr_gui.gui.flows"):
            assert not any(
                target in {
                    "ase2sprkkr_gui.gui.dialogs.main_window",
                    "ase2sprkkr_gui.gui.dialogs.workflow_window",
                }
                for target in targets
            ), module
        if module.startswith("ase2sprkkr_gui.gui.input_parameters"):
            assert not any(
                target.startswith(("ase2sprkkr_gui.gui.dialogs", "ase2sprkkr_gui.gui.widgets"))
                for target in targets
            ), module
        if module.startswith("ase2sprkkr_gui.gui.application"):
            assert not any(
                target.startswith(
                    (
                        "ase2sprkkr_gui.gui.controllers",
                        "ase2sprkkr_gui.gui.dialogs",
                        "ase2sprkkr_gui.gui.widgets",
                        "ase2sprkkr_gui.gui.flows",
                        "ase2sprkkr_gui.gui.workflow",
                        "ase2sprkkr_gui.gui.presentation",
                        "ase2sprkkr_gui.gui.recent_presentation",
                    )
                )
                for target in targets
            ), module
        if module.startswith("ase2sprkkr_gui.gui.workflow"):
            assert not any(
                target.startswith(
                    (
                        "ase2sprkkr_gui.gui.controllers",
                        "ase2sprkkr_gui.gui.dialogs",
                        "ase2sprkkr_gui.gui.widgets",
                        "ase2sprkkr_gui.gui.flows",
                    )
                )
                for target in targets
            ), module
        if module in {
            "ase2sprkkr_gui.gui.presentation",
            "ase2sprkkr_gui.gui.recent_presentation",
        }:
            assert not any(
                target.startswith(
                    (
                        "ase2sprkkr_gui.gui.application",
                        "ase2sprkkr_gui.gui.controllers",
                        "ase2sprkkr_gui.gui.dialogs",
                        "ase2sprkkr_gui.gui.widgets",
                        "ase2sprkkr_gui.gui.flows",
                        "ase2sprkkr_gui.gui.workflow",
                        "ase2sprkkr_gui.gui.input_parameters",
                    )
                )
                for target in targets
            ), module
        if module == "ase2sprkkr_gui.gui.workspace_semantics":
            assert not targets, module

    visited = set()

    def visit(module, trail):
        assert module not in trail, " -> ".join((*trail, module))
        if module in visited:
            return
        for target in graph[module]:
            visit(target, (*trail, module))
        visited.add(module)

    for module in graph:
        visit(module, ())


def test_workflow_renderer_has_no_application_state_dependency():
    """Renderer dependencies stay presentation-only, including transitively."""
    dependencies = _reachable(
        _gui_graph(),
        "ase2sprkkr_gui.gui.widgets.workflow_actions",
    )
    assert not any(
        module.startswith("ase2sprkkr_gui.gui.application") for module in dependencies
    )


def test_moved_semantics_are_not_reexported_from_old_modules():
    """Canonical moves must not leave accidental compatibility APIs behind."""
    action_card = importlib.import_module("ase2sprkkr_gui.gui.widgets.action_card")
    presentation = importlib.import_module("ase2sprkkr_gui.gui.presentation")
    recent_launcher = importlib.import_module("ase2sprkkr_gui.gui.widgets.recent_launcher")
    workspace_controller = importlib.import_module(
        "ase2sprkkr_gui.gui.application.workspace_controller"
    )

    assert not hasattr(action_card, "ActionCategory")
    assert not hasattr(presentation, "RecentLaunch")
    assert not hasattr(presentation, "recent_launch_presentation")
    assert not hasattr(recent_launcher, "recent_path_label")
    assert not hasattr(workspace_controller, "EmptySpheresAction")
    assert importlib.util.find_spec("ase2sprkkr_gui.gui.application.workspace_actions") is None


def test_result_widget_accepts_presentations_not_application_state():
    """Keep result-store/workspace orchestration outside the reusable Qt view."""
    widget_tree = ast.parse((GUI / "widgets" / "result_actions.py").read_text())
    widget_class = next(
        node
        for node in widget_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ResultActionsWidget"
    )
    widget_methods = {
        node.name for node in widget_class.body if isinstance(node, ast.FunctionDef)
    }
    assert "set_results" not in widget_methods
    assert "set_workspace_state" not in widget_methods

    forbidden_calls = {"set_results", "set_workspace_state"}
    for relative_path in (
        Path("dialogs/main_window.py"),
        Path("dialogs/workflow_window.py"),
    ):
        tree = ast.parse((GUI / relative_path).read_text())
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert calls.isdisjoint(forbidden_calls), relative_path


def test_editor_registry_dispatches_known_grammar_types():
    assert editor_for_type(Energy()) == "energy"
    assert editor_for_type(Real()) == "real"


def test_lightweight_input_parameter_modules_import_without_qt_or_dialogs():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from ase2sprkkr_gui.gui.input_parameters.expert_fields import EXPERT_FIELDS
from ase2sprkkr_gui.gui.input_parameters.tasks import guided_task_definition
assert EXPERT_FIELDS
assert guided_task_definition('scf').backend_task == 'scf'
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert not any(name.startswith('ase2sprkkr_gui.gui.dialogs.') for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_workflow_model_import_does_not_load_task_registry():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from ase2sprkkr_gui.gui.workflow.model import RunTask
assert RunTask('SCF').backend_task == 'SCF'
assert not any(name.startswith('ase2sprkkr_gui.gui.input_parameters') for name in sys.modules)
assert not any(name.startswith('PyQt6') for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_workflow_presentation_imports_without_qt_layers():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from ase2sprkkr_gui.gui.recent_presentation import RecentLaunch
from ase2sprkkr_gui.gui.workflow.model import RunTask
from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner
assert RecentLaunch and RunTask and WorkflowPlanner
assert not any(name.startswith('PyQt6') for name in sys.modules)
for prefix in (
    'ase2sprkkr_gui.gui.controllers.',
    'ase2sprkkr_gui.gui.dialogs.',
    'ase2sprkkr_gui.gui.widgets.',
    'ase2sprkkr_gui.gui.flows.',
):
    assert not any(name.startswith(prefix) for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_execution_cancellation_imports_without_qt_or_dialogs():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from ase2sprkkr_gui.gui.application.execution_cancellation import RunCancellation
assert RunCancellation
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert not any(name.startswith('ase2sprkkr_gui.gui.dialogs.') for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_domain_element_assignment_import_does_not_pull_in_gui():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import ase2sprkkr_gui.ase.element_assignment
assert not any(name.startswith('PyQt6') for name in sys.modules)
assert not any(name.startswith('ase2sprkkr_gui.gui') for name in sys.modules)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_all_gui_modules_import_in_a_fresh_process():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib
import pkgutil
import ase2sprkkr_gui.gui
for module in pkgutil.walk_packages(ase2sprkkr_gui.gui.__path__, 'ase2sprkkr_gui.gui.'):
    importlib.import_module(module.name)
""",
        ],
        cwd=ROOT,
        check=True,
        timeout=30,
    )


def test_session_binding_parameters_follows_the_working_snapshot():
    session = InputParametersSession(InputParameters.create("scf"))
    binding = SessionFieldBinding(
        session,
        field("SCF", "NITER", "Iterations"),
        "expert",
    )

    binding.set_value(42)
    first_snapshot = binding.parameters
    binding.set_value(17)

    assert first_snapshot.SCF.NITER() == 42
    assert binding.parameters is session.working_parameters
    assert binding.parameters.SCF.NITER() == 17


@pytest.mark.parametrize(
    "name",
    ["system-run.svg", "run-build-clean.svg", "labplot-xy-interpolation-curve.svg"],
)
def test_icons_are_found_after_relocation(name):
    assert icon_path(name).is_file()


def test_element_rows_use_callbacks_without_a_parent_dialog():
    app = QApplication.instance() or QApplication([])
    parents, messages = [], []

    def pick_element(parent):
        parents.append(parent)
        return "Co"

    atoms = Atoms("Fe", cell=np.eye(3), pbc=True)
    atoms.set_array("labels", np.asarray(["a"], dtype=object))
    draft = ElementAssignmentDraft(atoms)
    row = QLetterRow(
        draft,
        draft.sites[0],
        select_element=pick_element,
        on_validation=lambda label, message: messages.append((label, message)),
    )
    row.rows[0]["pick"].click()
    app.processEvents()
    assert parents == [row]
    assert row.rows[0]["elem"].text() == "Co"
    row.add_row()
    row.rows[1]["elem"].setText("Fe")
    assert messages[-1] == ("a", "Occupation too large for site a")
    row.close()
