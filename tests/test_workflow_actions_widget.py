from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

from ase2sprkkr_gui.gui.widgets.workflow_actions import WorkflowActionsWidget
from ase2sprkkr_gui.gui.workflow.model import (
    ActionIcon,
    ActionMenuGroup,
    ActionMenuItem,
    AvailableAction,
    AvailableActionGroup,
    ContinueRecent,
    StartOver,
    WorkflowPlan,
    WorkflowSection,
)


def _app():
    return QApplication.instance() or QApplication([])


def _single_action_plan(*, group="Group", title="Action", category="neutral"):
    return WorkflowPlan(
        "subtitle",
        (
            AvailableActionGroup(
                WorkflowSection.OTHER,
                group,
                (
                    AvailableAction(
                        StartOver(),
                        title,
                        "Description",
                        category,
                        ActionIcon.RESET,
                    ),
                ),
            ),
        ),
    )


def test_renderer_preserves_plan_group_order_and_presentation():
    _app()
    widget = WorkflowActionsWidget()
    first = AvailableAction(
        StartOver(),
        "First action",
        "First description",
        "neutral",
        ActionIcon.RESET,
    )
    second = AvailableAction(
        StartOver(),
        "Second action",
        "Second description",
        "destructive",
        ActionIcon.RESET,
    )
    plan = WorkflowPlan(
        "subtitle",
        (
            AvailableActionGroup(WorkflowSection.VIEW, "First group", (first,)),
            AvailableActionGroup(WorkflowSection.OTHER, "Second group", (second,)),
        ),
    )

    widget.set_plan(plan)

    assert widget.plan is plan
    labels = widget.findChildren(QLabel, "workflowActionGroupLabel")
    assert [label.text() for label in labels] == ["First group", "Second group"]
    buttons = widget.findChildren(QPushButton)
    assert [button.accessibleName() for button in buttons] == [
        "First action",
        "Second action",
    ]
    assert [button.accessibleDescription() for button in buttons] == [
        "First description",
        "Second description",
    ]
    widget.close()


def test_renderer_emits_typed_command_instead_of_interpreting_title():
    _app()
    widget = WorkflowActionsWidget()
    command = StartOver()
    widget.set_plan(
        WorkflowPlan(
            "subtitle",
            (
                AvailableActionGroup(
                    WorkflowSection.OTHER,
                    "Whatever",
                    (
                        AvailableAction(
                            command,
                            "Arbitrary copy",
                            "Copy may change without changing semantics",
                            "destructive",
                            ActionIcon.RESET,
                        ),
                    ),
                ),
            )
        )
    )
    emitted = []
    widget.commandRequested.connect(emitted.append)

    button = widget.findChild(QPushButton)
    assert button is not None
    button.click()

    assert emitted == [command]
    widget.close()


def test_renderer_menu_is_fully_driven_by_plan():
    _app()
    primary = ContinueRecent("output", "/tmp/SCF.out")
    structure = ContinueRecent("structure", "/tmp/Fe.cif")
    widget = WorkflowActionsWidget()
    widget.set_plan(
        WorkflowPlan(
            "subtitle",
            (
                AvailableActionGroup(
                    WorkflowSection.LOAD,
                    "Load",
                    (
                        AvailableAction(
                            primary,
                            "Continue: SCF.out",
                            "",
                            "load",
                            ActionIcon.CONTINUE,
                            tooltip="/tmp/SCF.out",
                            menu=(
                                ActionMenuGroup(
                                    "Structures",
                                    (
                                        ActionMenuItem(
                                            structure,
                                            "Fe.cif",
                                            "/tmp/Fe.cif",
                                        ),
                                    ),
                                    empty_text="(No recent files)",
                                ),
                                ActionMenuGroup(
                                    "Outputs",
                                    (),
                                    empty_text="Nothing here",
                                ),
                            ),
                        ),
                    ),
                ),
            )
        )
    )
    emitted = []
    widget.commandRequested.connect(emitted.append)

    button = widget.findChild(QToolButton)
    assert button is not None
    assert button.toolTip() == "/tmp/SCF.out"
    menu = button.menu()
    assert menu is not None
    assert [action.text() for action in menu.actions()] == ["Structures", "Outputs"]

    structures = menu.actions()[0].menu()
    assert structures is not None
    structure_action = structures.actions()[0]
    assert structure_action.text() == "Fe.cif"
    assert structure_action.toolTip() == "/tmp/Fe.cif"
    structure_action.trigger()
    assert emitted == [structure]

    outputs = menu.actions()[1].menu()
    assert outputs is not None
    assert len(outputs.actions()) == 1
    assert outputs.actions()[0].text() == "Nothing here"
    assert not outputs.actions()[0].isEnabled()

    button.click()
    assert emitted == [structure, primary]
    widget.close()


def test_group_labels_follow_application_palette():
    application = _app()
    original_palette = application.palette()
    try:
        for window_color, text_color in (
            (QColor("#202020"), QColor("#ffffff")),
            (QColor("#ffffff"), QColor("#202020")),
        ):
            palette = QPalette(original_palette)
            palette.setColor(QPalette.ColorRole.Window, window_color)
            palette.setColor(QPalette.ColorRole.WindowText, text_color)
            application.setPalette(palette)
            widget = WorkflowActionsWidget()
            widget.set_plan(_single_action_plan())

            label = widget.findChild(QLabel, "workflowActionGroupLabel")
            assert label is not None
            assert label.palette().color(QPalette.ColorRole.WindowText) == text_color
            widget.close()
    finally:
        application.setPalette(original_palette)


def test_replacing_plan_retires_old_groups():
    application = _app()
    widget = WorkflowActionsWidget()
    widget.set_plan(_single_action_plan(group="Old", title="Old action"))
    label = widget.findChild(QLabel, "workflowActionGroupLabel")
    assert label is not None
    old_group = label.parentWidget()

    widget.set_plan(_single_action_plan(group="New", title="New action"))

    assert old_group.isHidden()
    application.processEvents()
    visible_labels = [
        current.text()
        for current in widget.findChildren(QLabel, "workflowActionGroupLabel")
        if not current.isHidden()
    ]
    assert visible_labels == ["New"]
    widget.close()
