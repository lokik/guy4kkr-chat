"""Verify that structure creation uses distinct packaged icons."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.widgets.workflow_actions import WorkflowActionsWidget
from ase2sprkkr_gui.gui.workflow.model import (
    ActionIcon, Build2D, Build2DKind, CreateStructure, CreateStructureKind,
    WorkflowSection,
)
from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner


@pytest.mark.parametrize(
    ("name", "icon"),
    (
        ("bulk_crystal.png", ActionIcon.BULK_CRYSTAL),
        ("database.svg", ActionIcon.DATABASE),
        ("surface_2d.svg", ActionIcon.SURFACE),
        ("structure_interface.png", ActionIcon.INTERFACE),
    ),
)
def test_packaged_structure_icons_render(name, icon):
    application = QApplication.instance() or QApplication([])
    path = icon_path(name)
    assert path.is_file()
    renderer = WorkflowActionsWidget()
    qt_icon = renderer._icon(icon)
    assert not qt_icon.isNull()
    assert not qt_icon.pixmap(32, 32).isNull()
    renderer.close()


def test_planner_assigns_semantic_structure_icons():
    planner = WorkflowPlanner()
    plan = planner.initial_plan()
    create = plan.group(WorkflowSection.CREATE)
    assert create is not None
    icons = {a.command: a.icon for a in create.actions}
    assert icons[CreateStructure(CreateStructureKind.THREE_D)] is ActionIcon.BULK_CRYSTAL
    assert icons[CreateStructure(CreateStructureKind.PROTOTYPE)] is ActionIcon.DATABASE
    assert icons[CreateStructure(CreateStructureKind.SURFACE)] is ActionIcon.SURFACE
    assert icons[CreateStructure(CreateStructureKind.TWO_D)] is ActionIcon.INTERFACE
