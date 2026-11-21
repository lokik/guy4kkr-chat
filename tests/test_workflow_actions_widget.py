from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
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
    LoadAllRecentResults,
    RepeatRecentInput,
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


def test_action_shortcuts_follow_typed_commands_and_hide_on_narrow_cards():
    app = _app()
    from ase2sprkkr_gui.gui.workflow.model import (
        CreateStructure, CreateStructureKind, EditStructure, Load, LoadKind,
        SaveStructure,
    )
    widget = WorkflowActionsWidget()
    commands = (
        (CreateStructure(CreateStructureKind.THREE_D), "New crystal", "Ctrl+N"),
        (Load(LoadKind.STRUCTURE), "Load structure", "Ctrl+O"),
        (EditStructure(), "Edit structure", "Ctrl+E"),
        (SaveStructure(), "Save structure", "Ctrl+S"),
    )
    widget.set_plan(WorkflowPlan(
        "subtitle",
        (
            AvailableActionGroup(
                WorkflowSection.OTHER, "Actions", tuple(
                    AvailableAction(command, title, "Description", "structure", ActionIcon.EDIT)
                    for command, title, _shortcut in commands
                )
            ),
        ),
    ))
    buttons = widget.findChildren(QPushButton)
    assert len(buttons) == len(commands)
    for button, (_command, title, shortcut) in zip(buttons, commands):
        assert button.accessibleName() == title
        assert button.shortcut().toString() == shortcut
        hint = button.findChild(QLabel, "workflowShortcutHint")
        assert hint is not None and hint.text() == shortcut
        assert "Shortcut: " + shortcut in button.toolTip()
        button.resize(600, 80)
        app.processEvents()
        assert not hint.isHidden()
        button.resize(180, 80)
        app.processEvents()
        assert hint.isHidden()
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


def test_renderer_continue_uses_two_half_height_flat_dropdowns():
    app = _app()
    primary = ContinueRecent("output", "/tmp/SCF.out")
    structure = ContinueRecent("structure", "/tmp/Fe.cif")
    widget = WorkflowActionsWidget()
    widget.set_plan(
        WorkflowPlan(
            "subtitle",
            (
                AvailableActionGroup(
                    WorkflowSection.LOAD, "Load",
                    (
                        AvailableAction(
                            primary, "Continue: SCF.out", "", "load",
                            ActionIcon.CONTINUE, tooltip="/tmp/SCF.out",
                            menu=(
                                ActionMenuGroup(
                                    "Structures",
                                    (ActionMenuItem(structure, "Fe.cif", "/tmp/Fe.cif"),),
                                    empty_text="(No recent files)",
                                ),
                                ActionMenuGroup(
                                    "Results", (), empty_text="Nothing here",
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    emitted = []
    widget.commandRequested.connect(emitted.append)
    widget.resize(360, 220)
    widget.show()
    app.processEvents()

    card = widget.findChild(QPushButton)
    assert card is not None
    assert card.toolTip() == "/tmp/SCF.out"
    structures = card.findChild(QToolButton, "continueStructuresMenuButton")
    results = card.findChild(QToolButton, "continueResultsMenuButton")
    assert structures is not None and results is not None
    assert structures.width() >= 68 and results.width() >= 68
    assert structures.height() + results.height() == card.height()
    assert structures.geometry().bottom() + 1 == results.geometry().top()
    assert structures.text() == "" and results.text() == ""
    assert structures.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert results.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert structures.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert results.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert structures.accessibleName() == "Choose recent structures"
    assert results.accessibleName() == "Choose recent results"

    assert [action.text() for action in structures.menu().actions()] == ["Fe.cif"]
    structure_action = structures.menu().actions()[0]
    assert structure_action.toolTip() == "/tmp/Fe.cif"
    structure_action.trigger()
    assert emitted == [structure]

    assert [action.text() for action in results.menu().actions()] == ["Nothing here"]
    assert not results.menu().actions()[0].isEnabled()

    card.click()
    assert emitted == [structure, primary]
    widget.close()


def test_recent_results_menu_has_separated_load_all_footer():
    app = _app()
    result = ContinueRecent("output", "/tmp/scf.out")
    widget = WorkflowActionsWidget()
    widget.set_plan(WorkflowPlan(
        "", (AvailableActionGroup(
            WorkflowSection.LOAD, "Load",
            (AvailableAction(
                result, "Continue: scf.out", "", "load", ActionIcon.CONTINUE,
                menu=(
                    ActionMenuGroup("Structures", (), empty_text="No structures"),
                    ActionMenuGroup(
                        "Results",
                        (ActionMenuItem(result, "scf.out", "/tmp/scf.out"),),
                        footer=ActionMenuItem(LoadAllRecentResults(), "Load all results"),
                    ),
                ),
            ),),
        ),),
    ))
    widget.show()
    app.processEvents()
    results = widget.findChild(QToolButton, "continueResultsMenuButton")
    assert results is not None
    actions = results.menu().actions()
    assert [action.text() for action in actions] == ["scf.out", "", "Load all results"]
    assert actions[1].isSeparator()
    emitted = []
    widget.commandRequested.connect(emitted.append)
    actions[-1].trigger()
    assert emitted == [LoadAllRecentResults()]
    widget.close()


def test_single_recent_input_group_opens_flat_menu():
    _app()
    command = RepeatRecentInput("/tmp/first.inp")
    widget = WorkflowActionsWidget()
    widget.set_plan(WorkflowPlan(
        "", (
            AvailableActionGroup(
                WorkflowSection.CUSTOM, "Custom",
                (AvailableAction(
                    command, "Repeat calculation", "From first.inp",
                    "calculation", ActionIcon.CONTINUE,
                    menu=(ActionMenuGroup(
                        "Inputs", (
                            ActionMenuItem(command, "first.inp", "/tmp/first.inp"),
                        ),
                    ),),
                ),),
            ),
        ),
    ))
    card = widget.findChild(QPushButton)
    assert card is not None
    widget.resize(350, 200)
    widget.show()
    _app().processEvents()
    button = card.findChild(QToolButton, "repeatCalculationMenuButton")
    assert button is not None
    assert button.width() >= 68
    assert button.height() == card.height()
    assert button.text() == ""
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert [a.text() for a in button.menu().actions()] == ["first.inp"]
    emitted = []
    widget.commandRequested.connect(emitted.append)
    button.menu().actions()[0].trigger()
    card.click()
    assert emitted == [command, command]
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


def test_tall_panel_keeps_groups_and_labels_compact():
    application = _app()
    widget = WorkflowActionsWidget()
    groups = tuple(
        AvailableActionGroup(
            section, title, _single_action_plan(title=title).groups[0].actions
        )
        for section, title in (
            (WorkflowSection.CREATE, "First"), (WorkflowSection.LOAD, "Second")
        )
    )
    widget.set_plan(WorkflowPlan("subtitle", groups))
    widget.resize(550, 1200)
    widget.show()
    application.processEvents()

    labels = widget.findChildren(QLabel, "workflowActionGroupLabel")
    panels = [label.parentWidget() for label in labels]
    assert panels[0].geometry().top() == 0
    for panel, label in zip(panels, labels):
        assert panel.height() == panel.sizeHint().height()
        assert label.height() == label.sizeHint().height()
    assert panels[1].geometry().bottom() < widget.height() / 2
    widget.close()

def test_cards_have_matching_heights_with_wrapped_and_missing_descriptions():
    application = _app()
    widget = WorkflowActionsWidget()
    widget.set_plan(WorkflowPlan(
        "subtitle",
        (
            AvailableActionGroup(
                WorkflowSection.CREATE,
                "Create",
                (
                    AvailableAction(
                        StartOver(), "Short", "One line", "structure", ActionIcon.RESET,
                    ),
                    AvailableAction(
                        StartOver(), "Long",
                        "A longer description that wraps into several lines at the minimum "
                        "column width, without changing the height of the other action cards.",
                        "structure", ActionIcon.RESET,
                    ),
                    AvailableAction(
                        StartOver(), "No description", "", "neutral", ActionIcon.RESET,
                    ),
                ),
            ),
            AvailableActionGroup(
                WorkflowSection.LOAD,
                "Load",
                (
                    AvailableAction(
                        ContinueRecent("output", "/tmp/SCF.out"),
                        "Recent", "", "load", ActionIcon.CONTINUE,
                        menu=(ActionMenuGroup("Recent", (), empty_text="None"),),
                    ),
                ),
            ),
        ),
    ))
    widget.resize(320, 750)
    widget.show()
    application.processEvents()

    buttons = widget.findChildren(QPushButton) + widget.findChildren(QToolButton)
    assert len(buttons) == 4
    assert len({button.height() for button in buttons}) == 1
    narrow_height = buttons[0].height()
    assert narrow_height >= 68

    widget.resize(600, 750)
    application.processEvents()
    assert len({button.height() for button in buttons}) == 1
    assert buttons[0].height() <= narrow_height
    widget.close()
