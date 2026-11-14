"""Qt renderer for an already-resolved Guided workflow plan."""
from __future__ import annotations

from PyQt6.QtCore import QSize, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPalette
from PyQt6.QtWidgets import (
    QLabel,
    QMenu,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.style import SPACE_LG, SPACE_SM, heading_font
from ase2sprkkr_gui.gui.widgets.action_card import configure_action_card
from ase2sprkkr_gui.gui.workflow.model import ActionIcon, AvailableAction, WorkflowPlan


class WorkflowActionsWidget(QWidget):
    """Render a workflow plan and emit its semantic commands unchanged."""

    commandRequested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plan: WorkflowPlan | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE_LG)

    @property
    def plan(self) -> WorkflowPlan | None:
        return self._plan

    def set_plan(self, plan: WorkflowPlan) -> None:
        """Replace the rendered actions with ``plan`` exactly as ordered."""
        self._clear()
        self._plan = plan
        for group in plan.groups:
            group_widget = QWidget(self)
            group_layout = QVBoxLayout(group_widget)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(SPACE_SM)

            label = QLabel(group.title, group_widget)
            label.setObjectName("workflowActionGroupLabel")
            label.setForegroundRole(QPalette.ColorRole.WindowText)
            label.setFont(heading_font(label.font(), "section"))
            group_layout.addWidget(label)

            for action in group.actions:
                group_layout.addWidget(self._action_button(action, group_widget))
            self._layout.addWidget(group_widget)

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # ``deleteLater()`` only schedules destruction. Detach the retired
                # subtree immediately so it no longer participates in QObject
                # discovery or presentation while the deferred delete is pending.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _action_button(
        self,
        action: AvailableAction,
        parent: QWidget,
    ) -> QPushButton | QToolButton:
        if action.menu:
            button = QToolButton(parent)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            button.setMenu(self._action_menu(action, button))
            icon_size = QSize(24, 24)
            minimum_height = 52
            menu_button = True
        else:
            button = QPushButton(parent)
            icon_size = None
            minimum_height = 68
            menu_button = False

        if action.tooltip is not None:
            button.setToolTip(action.tooltip)

        configure_action_card(
            button,
            action.title,
            action.description,
            self._icon(action.icon),
            category=action.category,
            icon_size=icon_size,
            minimum_height=minimum_height,
            menu_button=menu_button,
            subtle=action.category == "neutral",
        )
        button.clicked.connect(
            lambda _checked=False, command=action.command: self.commandRequested.emit(
                command
            )
        )
        return button

    def _action_menu(self, action: AvailableAction, parent: QWidget) -> QMenu:
        menu = QMenu(parent)
        for group in action.menu:
            submenu = QMenu(group.title, menu)
            if group.items:
                for item in group.items:
                    menu_action = QAction(item.title, submenu)
                    if item.tooltip is not None:
                        menu_action.setToolTip(item.tooltip)
                    menu_action.triggered.connect(
                        lambda _checked=False, command=item.command: self.commandRequested.emit(
                            command
                        )
                    )
                    submenu.addAction(menu_action)
            else:
                assert group.empty_text is not None
                empty = QAction(group.empty_text, submenu)
                empty.setEnabled(False)
                submenu.addAction(empty)
            menu.addMenu(submenu)
        return menu

    def _icon(self, icon: ActionIcon) -> QIcon:
        standard = {
            ActionIcon.OPEN: QStyle.StandardPixmap.SP_DialogOpenButton,
            ActionIcon.DOWNLOAD: QStyle.StandardPixmap.SP_ArrowDown,
            ActionIcon.FILE: QStyle.StandardPixmap.SP_FileIcon,
            ActionIcon.RESULT: QStyle.StandardPixmap.SP_FileDialogContentsView,
            ActionIcon.VIEW: QStyle.StandardPixmap.SP_FileDialogContentsView,
            ActionIcon.CONTINUE: QStyle.StandardPixmap.SP_ArrowForward,
            ActionIcon.RESET: QStyle.StandardPixmap.SP_BrowserReload,
        }
        resource = {
            ActionIcon.RUN: "system-run.svg",
            ActionIcon.EMPTY_SPHERES: "run-build-clean.svg",
            ActionIcon.NEW_CALCULATION: "run-build-clean.svg",
            ActionIcon.BULK_CRYSTAL: "bulk_crystal.png",
            ActionIcon.DATABASE: "database.svg",
            ActionIcon.SURFACE: "surface_2d.svg",
            ActionIcon.INTERFACE: "structure_interface.png",
        }
        if icon is ActionIcon.SHELL:
            return QIcon.fromTheme(
                "utilities-terminal",
                self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
            )
        if icon in resource:
            return QIcon(str(icon_path(resource[icon])))
        return self.style().standardIcon(standard[icon])
