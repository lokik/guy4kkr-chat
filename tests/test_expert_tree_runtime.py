import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

from ase2sprkkr_gui.gui.input_parameters.specs.schema import FieldPlacement
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_runtime import ExpertTreeRuntime
from ase2sprkkr_gui.gui.widgets.input_parameters.expert_tree_structure import ValueShape
from ase2sprkkr_gui.gui.widgets.input_parameters.scalar import RealEditor


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def make_tree():
    tree = QTreeWidget()
    tree.setColumnCount(3)
    root = QTreeWidgetItem(["root"])
    child = QTreeWidgetItem(["child"])
    tree.addTopLevelItem(root)
    root.addChild(child)
    return tree, root, child


def make_editor(tree, dependencies=()):
    editor = RealEditor(nullable=True, parent=tree)
    editor.dependencies = dependencies
    return editor


def test_runtime_tracks_option_rows_bidirectionally(application):
    tree, root, child = make_tree()
    runtime = ExpertTreeRuntime(tree)
    first = ("SCF", "NITER")
    second = ("SCF", "MIX")
    first_shape = ValueShape("leaf", "integer")
    second_shape = ValueShape("leaf", "real")

    runtime.register_option(first, child, first_shape)
    assert runtime.option_item(first) is child
    assert runtime.option_path_for_item(child) == first
    assert runtime.option_path_for_item(root) is None
    assert runtime.option_shape(first) == first_shape

    runtime.register_option(second, child, second_shape)
    assert runtime.option_item(first) is None
    assert runtime.option_shape(first) is None
    assert runtime.option_item(second) is child
    assert runtime.option_path_for_item(child) == second
    assert runtime.option_shape(second) == second_shape

    runtime.unregister_subtree(root, include_root=False)
    assert runtime.option_item(second) is None
    assert runtime.option_path_for_item(child) is None
    assert runtime.option_shape(second) is None
    tree.close()


def test_runtime_registers_editor_dependencies(application):
    tree, _root, child = make_tree()
    editor = make_editor(tree, (("ENERGY", "GRID"),))
    tree.setItemWidget(child, 2, editor)
    placement = FieldPlacement(("ENERGY", "NE"), "NE")
    runtime = ExpertTreeRuntime(tree)

    runtime.register_editor(editor, child, placement)

    assert runtime.editors_depending_on((("ENERGY", "NE"),))[0].editor is editor
    assert runtime.editors_depending_on((("ENERGY", "GRID"),))[0].editor is editor
    assert runtime.editors_depending_on((("SCF", "NITER"),)) == ()
    tree.close()


def test_runtime_prunes_replaced_editor_and_its_validation_error(application):
    messages = []
    tree, _root, child = make_tree()
    first = make_editor(tree)
    tree.setItemWidget(child, 2, first)
    runtime = ExpertTreeRuntime(tree, errors_changed=messages.append)
    runtime.register_editor(first, child, FieldPlacement(("SCF", "MIX"), "MIX"))
    runtime.set_error(child, "MIX", "bad value")
    publications = len(messages)

    replacement = make_editor(tree)
    tree.setItemWidget(child, 2, replacement)

    assert runtime.live_editors() == ()
    assert not runtime.has_errors
    assert runtime.error_messages == ()
    assert messages[-1] == ()
    assert len(messages) == publications + 1
    tree.close()


def test_runtime_aggregates_and_removes_subtree_errors(application):
    messages = []
    tree, root, child = make_tree()
    runtime = ExpertTreeRuntime(tree, errors_changed=messages.append)

    # Errors are allowed to arrive while a newly created editor is being
    # refreshed, before it has been registered. Subtree cleanup must still
    # remove them deterministically.
    runtime.set_error(child, "NITER", "bad value")
    assert runtime.has_errors
    assert runtime.error_messages == ("NITER: bad value",)
    assert messages[-1] == ("NITER: bad value",)

    publications = len(messages)
    runtime.unregister_subtree(root, include_root=False)
    assert not runtime.has_errors
    assert messages[-1] == ()
    assert len(messages) == publications + 1
    tree.close()


def test_runtime_does_not_publish_when_error_value_is_unchanged(application):
    messages = []
    tree, _root, child = make_tree()
    runtime = ExpertTreeRuntime(tree, errors_changed=messages.append)

    runtime.set_error(child, "NITER", "bad value")
    runtime.set_error(child, "NITER", "bad value")

    assert messages == [("NITER: bad value",)]
    tree.close()
