"""Qt renderer for an already-resolved Guided workflow plan."""
from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QPalette
from PyQt6.QtWidgets import (
    QLabel,
    QLayout,
    QAbstractButton,
    QMenu,
    QPushButton,
    QStyle,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.misc.icons import badge_icon, task_icon
from ase2sprkkr_gui.gui.style import PANEL_RADIUS, SPACE_LG, SPACE_SM, heading_font
from ase2sprkkr_gui.gui.widgets.action_card import configure_action_card
from ase2sprkkr_gui.gui.workflow.model import (
    ActionIcon,
    ActionMenuGroup,
    AvailableAction,
    ConvergeHostScf,
    ContinueRecent,
    RepeatRecentInput,
    CreateStructure,
    CreateStructureKind,
    EditStructure,
    Load,
    LoadKind,
    RunTask,
    ReconvergeScf,
    CustomTask,
    SaveStructure,
    UpdateEmptySpheres,
    UseForNewCalculation,
    WorkflowPlan,
    WorkflowSection,
)


_CALCULATION_COMMANDS = (
    RunTask,
    ReconvergeScf,
    CustomTask,
    RepeatRecentInput,
    ConvergeHostScf,
    UpdateEmptySpheres,
    UseForNewCalculation,
)


def _action_column(action: AvailableAction) -> Literal["structure", "calculate"]:
    """Separate workflow actions by command semantics, never their display text."""
    return "calculate" if isinstance(action.command, _CALCULATION_COMMANDS) else "structure"


def _shortcut_for_command(command) -> str | None:
    """Reserve shortcuts by command identity, not translated action titles."""
    if isinstance(command, CreateStructure) and command.kind is CreateStructureKind.THREE_D:
        return "Ctrl+N"
    if isinstance(command, Load) and command.kind is LoadKind.STRUCTURE:
        return "Ctrl+O"
    if isinstance(command, EditStructure):
        return "Ctrl+E"
    if isinstance(command, SaveStructure):
        return "Ctrl+S"
    return None


class _ShortcutActionButton(QPushButton):
    """Action card with a right-aligned shortcut hint that collapses on resize."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.shortcut_hint: QLabel | None = None
        self._hint_required_width = 0

    def configure_hint(self, shortcut: str, title: str) -> None:
        hint = QLabel(shortcut, self)
        hint.setObjectName("workflowShortcutHint")
        hint.setForegroundRole(QPalette.ColorRole.Mid)
        hint.setStyleSheet(
            f"color: {self.palette().color(QPalette.ColorRole.Mid).name()};"
        )
        hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hint.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.layout().addWidget(hint, 0, Qt.AlignmentFlag.AlignRight)
        self.shortcut_hint = hint
        title_label = next(
            (label for label in self.findChildren(QLabel) if label.text() == title),
            None,
        )
        title_width = (
            title_label.fontMetrics().horizontalAdvance(title)
            if title_label is not None
            else self.fontMetrics().horizontalAdvance(title)
        )
        # Two margins, the icon, two gaps, the full unbroken title and hint.
        self._hint_required_width = (
            2 * SPACE_LG + 26 + 2 * SPACE_LG
            + title_width + hint.sizeHint().width() + SPACE_SM
        )
        self._update_hint_visibility()

    def _update_hint_visibility(self) -> None:
        if self.shortcut_hint is not None:
            self.shortcut_hint.setVisible(self.width() >= self._hint_required_width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_hint_visibility()


class _RecentActionButton(QPushButton):
    """Action card with generously sized recent-file dropdowns."""

    MENU_WIDTH = 76

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._recent_buttons: list[QToolButton] = []

    def add_recent_menu(self, name: str, icon: QIcon, menu: QMenu) -> None:
        button = QToolButton(self)
        button.setObjectName({
            "Structures": "continueStructuresMenuButton",
            "Results": "continueResultsMenuButton",
            "Inputs": "repeatCalculationMenuButton",
        }[name])
        button.setIcon(icon)
        button.setIconSize(QSize(20, 20))
        # InstantPopup already renders Qt's native down-arrow indicator.
        # Do not add a second triangle as button text.
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setMenu(menu)
        button.setToolTip(f"Recent {name.lower()}")
        button.setAccessibleName(f"Choose recent {name.lower()}")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        border = self.palette().color(QPalette.ColorRole.Mid).name()
        corner = (
            (f"border-top-right-radius: {PANEL_RADIUS}px;" if name != "Results" else "")
            + (f"border-bottom-right-radius: {PANEL_RADIUS}px;" if name != "Structures" else "")
        )
        button.setStyleSheet(
            f"QToolButton {{ background: transparent; border: none; "
            f"border-left: 1px solid {border}; padding: 0; {corner} }}"
            f"QToolButton:hover, QToolButton:pressed {{ "
            f"background: {self.palette().color(QPalette.ColorRole.Midlight).name()}; }}"
        )
        self._recent_buttons.append(button)
        self._position_recent_buttons()

    def _position_recent_buttons(self) -> None:
        count = len(self._recent_buttons)
        for index, button in enumerate(self._recent_buttons):
            top = self.height() * index // count
            bottom = self.height() * (index + 1) // count
            button.setGeometry(
                self.width() - self.MENU_WIDTH, top,
                self.MENU_WIDTH, bottom - top,
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_recent_buttons()


class WorkflowActionsWidget(QWidget):
    """Render a workflow plan and emit its semantic commands unchanged."""

    commandRequested = pyqtSignal(object)
    naturalCardHeightChanged = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        column: Literal["structure", "calculate"] | None = None,
        excluded_commands: tuple[type, ...] = (),
    ) -> None:
        super().__init__(parent)
        self._column = column
        self._excluded_commands = excluded_commands
        self._plan: WorkflowPlan | None = None
        self._action_buttons: list[QAbstractButton] = []
        self._natural_card_height = 68
        self._uniform_card_height: int | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SPACE_LG)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Propagate each new plan's minimum height to the enclosing scroll area.
        # Otherwise Qt can compress groups below their cards' minimum heights.
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

    @property
    def plan(self) -> WorkflowPlan | None:
        return self._plan

    @property
    def has_actions(self) -> bool:
        return self._plan is not None and any(
            self._visible_actions(group.actions)
            for group in self._plan.groups
        )

    def _visible_actions(
        self, actions: tuple[AvailableAction, ...]
    ) -> tuple[AvailableAction, ...]:
        return tuple(
            action for action in actions
            if (self._column is None or _action_column(action) == self._column)
            and not isinstance(action.command, self._excluded_commands)
        )

    def set_plan(self, plan: WorkflowPlan) -> None:
        """Render the actions belonging to this column, retaining their commands."""
        self._clear()
        self._plan = plan
        for group in plan.groups:
            actions = self._visible_actions(group.actions)
            if not actions:
                continue
            group_widget = QWidget(self)
            group_layout = QVBoxLayout(group_widget)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(SPACE_SM)

            heading = group.title
            if self._column == "structure" and group.section is WorkflowSection.VIEW:
                heading = ""
            elif self._column == "calculate" and group.section is WorkflowSection.CALCULATE:
                heading = ""
            elif self._column is not None and group.section is WorkflowSection.OTHER:
                heading = (
                    "Change structure" if self._column == "structure"
                    else "More calculations"
                )
            if heading:
                label = QLabel(heading, group_widget)
                label.setObjectName("workflowActionGroupLabel")
                label.setForegroundRole(QPalette.ColorRole.WindowText)
                label.setFont(heading_font(label.font(), "section"))
                group_layout.addWidget(label)

            for action in actions:
                button = self._action_button(action, group_widget)
                self._action_buttons.append(button)
                group_layout.addWidget(button)
            self._layout.addWidget(group_widget)
        self._equalize_action_heights()

    @property
    def natural_card_height(self) -> int:
        """Height needed by the longest card at this column's current width."""
        return self._natural_card_height

    def set_uniform_card_height(self, height: int) -> None:
        """Allow sibling workflow columns to use the same card height."""
        self._uniform_card_height = height
        self._apply_action_height()

    def _apply_action_height(self) -> None:
        height = max(self._natural_card_height, self._uniform_card_height or 0)
        for button in self._action_buttons:
            if button.minimumHeight() != height or button.maximumHeight() != height:
                button.setFixedHeight(height)

    def _equalize_action_heights(self) -> None:
        """Keep all cards equally tall while allowing descriptions to wrap."""
        height = 68
        width = self.contentsRect().width()
        for button in self._action_buttons:
            layout = button.layout()
            margins = layout.contentsMargins()
            icon = layout.itemAt(0).widget()
            text = layout.itemAt(1).widget()
            text_layout = text.layout()
            title = text.findChild(QLabel, "actionCardTitle")
            description = text.findChild(QLabel, "actionCardDescription")
            text_width = (
                width - margins.left() - margins.right()
                - layout.spacing() - icon.width()
            )
            if isinstance(button, _ShortcutActionButton):
                hint = button.shortcut_hint
                if hint is not None and width >= button._hint_required_width:
                    text_width -= layout.spacing() + hint.sizeHint().width()
            text_height = title.sizeHint().height()
            if description is not None:
                text_height += (
                    text_layout.spacing()
                    + description.heightForWidth(max(1, text_width))
                )
            height = max(
                height, 2 * SPACE_SM + 2 + max(icon.height(), text_height)
            )
        if self._natural_card_height != height:
            self._natural_card_height = height
            self.naturalCardHeightChanged.emit()
        self._apply_action_height()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._equalize_action_heights()

    def _clear(self) -> None:
        self._action_buttons.clear()
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
        shortcut = _shortcut_for_command(action.command)
        if (
            isinstance(action.command, ContinueRecent) and len(action.menu) == 2
            or isinstance(action.command, RepeatRecentInput) and len(action.menu) == 1
        ):
            button = _RecentActionButton(parent)
            icon_size = None
            minimum_height = 68
            menu_button = False
        elif action.menu:
            button = QToolButton(parent)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            button.setMenu(self._action_menu(action, button))
            icon_size = QSize(24, 24)
            minimum_height = 68
            menu_button = True
        else:
            button = _ShortcutActionButton(parent) if shortcut else QPushButton(parent)
            icon_size = None
            minimum_height = 68
            menu_button = False

        if action.tooltip is not None:
            button.setToolTip(action.tooltip)

        if isinstance(action.command, RunTask):
            custom_icon = task_icon(action.command.backend_task)
        elif isinstance(action.command, ReconvergeScf) or (
            isinstance(action.command, ConvergeHostScf)
            and action.command.restart_scf
        ):
            custom_icon = badge_icon(
                QIcon(str(icon_path("calculation-gear.svg"))), "reconverge",
            )
        elif isinstance(action.command, UseForNewCalculation):
            custom_icon = badge_icon(
                QIcon(str(icon_path("calculation-gear.svg"))), "new",
            )
        else:
            custom_icon = QIcon()
        configure_action_card(
            button,
            action.title,
            action.description,
            custom_icon if not custom_icon.isNull() else self._icon(action.icon),
            category=action.category,
            icon_size=icon_size,
            minimum_height=minimum_height,
            menu_button=menu_button,
            subtle=action.category == "neutral",
        )
        if isinstance(button, _RecentActionButton):
            layout = button.layout()
            margins = layout.contentsMargins()
            layout.setContentsMargins(
                margins.left(), margins.top(),
                button.MENU_WIDTH + SPACE_SM, margins.bottom(),
            )
            for group in action.menu:
                icon = self._icon(
                    ActionIcon.BULK_CRYSTAL if group.title == "Structures"
                    else ActionIcon.FILE if group.title == "Inputs"
                    else ActionIcon.RESULT
                )
                button.add_recent_menu(
                    group.title, icon, self._group_menu(group, button),
                )
        if isinstance(action.command, RepeatRecentInput) and action.command.path is None:
            button.setEnabled(False)
        if shortcut:
            button.setShortcut(QKeySequence(shortcut))
            button.setToolTip(
                "\n".join(filter(None, (action.tooltip, f"Shortcut: {shortcut}")))
            )
            if isinstance(button, _ShortcutActionButton):
                button.configure_hint(shortcut, action.title)
        button.clicked.connect(
            lambda _checked=False, command=action.command: self.commandRequested.emit(
                command
            )
        )
        return button

    def _action_menu(self, action: AvailableAction, parent: QWidget) -> QMenu:
        menu = QMenu(parent)
        if len(action.menu) == 1:
            # One kind of recent file needs one menu, not an extra submenu.
            self._populate_menu_items(menu, action.menu[0])
        else:
            for group in action.menu:
                submenu = self._group_menu(group, menu)
                submenu.setTitle(group.title)
                menu.addMenu(submenu)
        return menu

    def _group_menu(self, group: ActionMenuGroup, parent: QWidget) -> QMenu:
        menu = QMenu(parent)
        self._populate_menu_items(menu, group)
        return menu

    def _populate_menu_items(self, menu: QMenu, group: ActionMenuGroup) -> None:
        if group.items:
            for item in group.items:
                menu_action = QAction(item.title, menu)
                if item.tooltip is not None:
                    menu_action.setToolTip(item.tooltip)
                menu_action.triggered.connect(
                    lambda _checked=False, command=item.command: self.commandRequested.emit(
                        command
                    )
                )
                menu.addAction(menu_action)
        else:
            assert group.empty_text is not None
            empty = QAction(group.empty_text, menu)
            empty.setEnabled(False)
            menu.addAction(empty)
        if group.footer is not None:
            menu.addSeparator()
            item = group.footer
            menu_action = QAction(item.title, menu)
            if item.tooltip is not None:
                menu_action.setToolTip(item.tooltip)
            menu_action.triggered.connect(
                lambda _checked=False, command=item.command: self.commandRequested.emit(
                    command
                )
            )
            menu.addAction(menu_action)

    def _icon(self, icon: ActionIcon) -> QIcon:
        standard = {
            ActionIcon.OPEN: QStyle.StandardPixmap.SP_DialogOpenButton,
            ActionIcon.DOWNLOAD: QStyle.StandardPixmap.SP_ArrowDown,
            ActionIcon.FILE: QStyle.StandardPixmap.SP_FileIcon,
            ActionIcon.RESULT: QStyle.StandardPixmap.SP_FileDialogContentsView,
            ActionIcon.VIEW: QStyle.StandardPixmap.SP_FileDialogContentsView,
            ActionIcon.EDIT: QStyle.StandardPixmap.SP_FileDialogDetailedView,
            ActionIcon.SAVE: QStyle.StandardPixmap.SP_DialogSaveButton,
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
            ActionIcon.EMBEDDING: "bulk_crystal.png",
        }
        if icon is ActionIcon.SHELL:
            return QIcon.fromTheme(
                "utilities-terminal",
                self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
            )
        if icon in resource:
            return QIcon(str(icon_path(resource[icon])))
        return self.style().standardIcon(standard[icon])
