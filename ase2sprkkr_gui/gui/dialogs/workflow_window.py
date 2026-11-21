from __future__ import annotations

from threading import Thread
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QPalette, QResizeEvent
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPushButton,
    QScrollArea,
    QStyle,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ase2sprkkr_gui.gui.application.recent_files import (
    RECENT_KINDS,
    RecentFiles,
    RecentFilesSnapshot,
    find_missing_recent_paths,
)
from ase2sprkkr_gui.gui.application.settings import ApplicationSettings
from ase2sprkkr_gui.gui.application.window_geometry import manage_window_geometry
from ase2sprkkr_gui.gui.application.workspace_controller import WorkspaceController
from ase2sprkkr_gui.gui.dialogs.object_view import execute_value_action
from ase2sprkkr_gui.gui.dialogs.settings import edit_settings
from ase2sprkkr_gui.gui.misc.colors import blend
from ase2sprkkr_gui.gui.misc.icons import badge_icon, settings_icon
from ase2sprkkr_gui.gui.misc.resources import icon_path
from ase2sprkkr_gui.gui.flows import calculation as calculation_flow
from ase2sprkkr_gui.gui.flows import custom_calculation as custom_flow
from ase2sprkkr_gui.gui.flows import files as file_flows
from ase2sprkkr_gui.gui.flows import structures as structure_flows
from ase2sprkkr_gui.gui.flows import visualization as visualization_flow
from ase2sprkkr_gui.gui.recent_presentation import RecentLaunchKind, recent_menu_items
from ase2sprkkr_gui.gui.style import (
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    SPACE_XXL,
    action_card_stylesheet,
    heading_font,
    secondary_text_stylesheet,
)
from ase2sprkkr_gui.gui.widgets.centered_icon_buttons import CenteredIconToolButton
from ase2sprkkr_gui.gui.widgets.result_actions import ResultActionsWidget
from ase2sprkkr_gui.gui.widgets.structures.overview import StructureOverviewWidget
from ase2sprkkr_gui.gui.widgets.workflow_actions import WorkflowActionsWidget
from ase2sprkkr_gui.gui.workflow.model import (
    Build2D,
    Build2DKind,
    BuildEmbedding,
    ExplainEmbedding,
    ConvergeHostScf,
    ContinueRecent,
    LoadAllRecentResults,
    RepeatRecentInput,
    CreateStructure,
    CreateStructureKind,
    Load,
    LoadKind,
    RunTask,
    ReconvergeScf,
    CustomTask,
    StartOver,
    UpdateEmptySpheres,
    UseForNewCalculation,
    VisualizeStructure,
    EditStructure,
    SaveStructure,
    LoadHostPotential,
    AttachHostPotential,
    CreateHostPotential,
    WorkflowCommand,
    WorkflowPlan,
)
from ase2sprkkr_gui.gui.workflow.planner import WorkflowPlanner


class _RecentValidationSignals(QObject):
    """Deliver a one-shot filesystem check to the GUI thread."""

    finished = pyqtSignal(object, object)


def _check_recent_files(snapshot: RecentFilesSnapshot, signals: _RecentValidationSignals) -> None:
    signals.finished.emit(snapshot, find_missing_recent_paths(snapshot))


def _navigation_button_stylesheet(palette: QPalette, selector: str) -> str:
    """A muted, compact counterpart to the larger workflow action cards."""
    accent = blend(
        palette.color(QPalette.ColorRole.Button),
        palette.color(QPalette.ColorRole.Mid), .78,
    )
    return (
        action_card_stylesheet(
            palette, accent, selector, accent_width=3,
        )
        + f"{selector} {{ padding: 3px 7px; }}"
        + f"{selector}:disabled {{ color: "
        f"{palette.color(QPalette.ColorRole.PlaceholderText).name()}; }}"
    )


class _RecentFooterButton(CenteredIconToolButton):
    """Recent action with a compact filename suffix and the complete path tooltip."""

    def __init__(self, title: str, parent: QWidget):
        super().__init__(parent)
        self._title = title
        self._recent_path: str | None = None
        self._base_tooltip = ""
        self._display_mode = "full"
        self._short_title = title
        self.setText(title)

    def set_recent_path(self, path: str | None) -> None:
        self._recent_path = path
        self._refresh_label()

    def set_base_tooltip(self, tooltip: str) -> None:
        self._base_tooltip = tooltip
        self._refresh_label()

    def set_short_title(self, title: str) -> None:
        self._short_title = title
        self._refresh_label()

    def set_display_mode(self, mode: str) -> None:
        self._display_mode = mode
        self._refresh_label()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh_label()

    def _refresh_label(self) -> None:
        mode = self._display_mode
        title = self._short_title if mode == "short" else self._title
        # Display only the basename. The complete path remains in the tooltip
        # and in the menu, so dropping the ornamental ellipsis loses nothing.
        label = title
        if self._recent_path and mode != "icon":
            label += "\n" + Path(self._recent_path).name
        tooltip = (
            f"{self._title}\n{self._recent_path}"
            if mode == "icon" and self._recent_path else
            self._title if mode == "icon" else
            f"{self._base_tooltip}\n{self._recent_path}"
            if self._recent_path else self._base_tooltip
        )
        if self.text() != label:
            self.setText(label)
        if self.toolTip() != tooltip:
            self.setToolTip(tooltip)



class _HeaderActionBar(QWidget):
    """Column header which uses the same compact mode as its peers."""

    # Taller, narrower buttons leave the original 93-pixel header unchanged.
    # Two lines of text can fit below the icon without moving column titles.
    FULL_WIDTH = 168
    SHORT_WIDTH = 120
    BUTTON_HEIGHT = 68
    COMPACT_SIZE = BUTTON_HEIGHT  # Square icon-only main button.
    MENU_EXTRA_WIDTH = 22
    VERTICAL_GAP = 12  # Also used by the unchanged Results utility footer.
    BAR_HEIGHT = 93

    layoutChanged = pyqtSignal()

    def __init__(self, parent: QWidget, name: str, *, centered: bool = False):
        super().__init__(parent)
        self.setObjectName(name)
        self._centered = centered
        self.setFixedHeight(self.BAR_HEIGHT)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._buttons: list[QAbstractButton] = []
        self._labels: dict[QAbstractButton, str] = {}
        self._short_labels: dict[QAbstractButton, str] = {}
        self._tooltips: dict[QAbstractButton, str] = {}
        self._styles: dict[QAbstractButton, str] = {}
        self._mode = "full"
        self._mode_applied = False
        layout = QHBoxLayout(self)
        # The middle header shares the text/cards' right inset, so its
        # button row is centered on Calculate rather than on the wider column.
        layout.setContentsMargins(0, 0, SPACE_XL if centered else 0, 0)
        layout.setSpacing(0)
        self._button_row = QHBoxLayout()
        self._button_row.setContentsMargins(0, 0, 0, 0)
        self._button_row.setSpacing(2)  # Toolbar only; content gaps stay unchanged.
        if centered:
            layout.addStretch(1)
        layout.addLayout(self._button_row)
        layout.addStretch(1)

    def register(self, button: QAbstractButton, *, short_title: str) -> None:
        self._buttons.append(button)
        self._labels[button] = button.text()
        self._short_labels[button] = short_title
        self._tooltips[button] = button.toolTip()
        self._styles[button] = button.styleSheet()
        if isinstance(button, _RecentFooterButton):
            button.set_short_title(short_title)
        self.layout().removeWidget(button)
        self._button_row.addWidget(
            button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        button.setIconSize(QSize(26, 26))
        button.setFixedHeight(self.BUTTON_HEIGHT)
        button.setProperty("twoLineUnderIcon", True)
        button.setMinimumWidth(0)
        button.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._mode_applied = False
        self.refresh()

    def set_button_label(
        self, button: QAbstractButton, title: str,
        *, short_title: str | None = None,
    ) -> None:
        self._labels[button] = title
        if short_title is not None:
            self._short_labels[button] = short_title
        button.setAccessibleName(title)
        # Reapply the current presentation even when its width has not changed.
        self._mode_applied = False
        self.refresh()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.BAR_HEIGHT)

    def sizeHint(self) -> QSize:
        return QSize(0, self.BAR_HEIGHT)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.refresh()

    def required_mode(self) -> str:
        visible = sum(not button.isHidden() for button in self._buttons)
        if not visible:
            return "full"
        gaps = (visible - 1) * self._button_row.spacing()
        available = self.width() - self.layout().contentsMargins().right()
        if available >= visible * self.FULL_WIDTH + gaps:
            return "full"
        if available >= visible * self.SHORT_WIDTH + gaps:
            return "short"
        return "icon"

    def refresh(self) -> None:
        self.layoutChanged.emit()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._mode_applied = True
        for button in self._buttons:
            width = (
                self.FULL_WIDTH if mode == "full" else
                self.SHORT_WIDTH if mode == "short" else
                self.COMPACT_SIZE + (
                    self.MENU_EXTRA_WIDTH
                    if isinstance(button, _RecentFooterButton) else 0
                )
            )
            if button.width() != width or button.minimumWidth() != width:
                button.setFixedWidth(width)

            if isinstance(button, _RecentFooterButton):
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly if mode == "icon"
                    else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
                )
                button.set_display_mode(mode)
                style = self._styles[button]
                if mode == "icon":
                    style += "QToolButton::menu-button { width: 22px; }"
                button.setStyleSheet(style)
            elif isinstance(button, QToolButton):
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonIconOnly if mode == "icon"
                    else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
                )
                button.setText(
                    self._short_labels[button] if mode == "short"
                    else self._labels[button]
                )
                button.setToolTip(
                    f"{self._labels[button]}\n{self._tooltips[button]}"
                    if mode == "icon" else self._tooltips[button]
                )
            elif isinstance(button, QPushButton):
                button.setText(
                    "" if mode == "icon" else
                    self._short_labels[button] if mode == "short" else
                    self._labels[button]
                )
                button.setToolTip(
                    f"{self._labels[button]}\n{self._tooltips[button]}"
                    if mode == "icon" else self._tooltips[button]
                )



class WorkflowWindow(QMainWindow):
    """Primary task-oriented Ase2sprkkr application window."""

    projectBrowserRequested = pyqtSignal()

    def __init__(
        self,
        controller: WorkspaceController,
        recent_files: RecentFiles,
        *,
        settings: ApplicationSettings,
        track_launch_monitor: calculation_flow.LaunchMonitorTracker,
        project_repository=None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Ase2sprkkr - Workflow")
        manage_window_geometry(
            self, "workflow", default_size=(1320, 760), default_maximized=True
        )
        self.controller = controller
        self.recent_history = recent_files
        self._displayed_recent_inputs = recent_files.paths("input")
        self.settings = settings
        self._track_launch_monitor = track_launch_monitor
        self.project_repository = project_repository
        self._workflow_planner = WorkflowPlanner(settings=settings)
        self._recent_validation_running = False
        self._recent_validation_signals: _RecentValidationSignals | None = None
        self._navigation_snapshot: RecentFilesSnapshot | None = None
        self.controller.structureChanged.connect(self._on_structure_changed)
        # Results have their own presenter; they do not change workflow
        # availability unless the controller also emits structureChanged.
        self.recent_history.changed.connect(self._refresh_recent_history)
        self.controller.inputParametersChanged.connect(
            lambda _parameters: self._update_navigation(self.recent_history.read_snapshot())
        )
        self._build_ui()
        self._refresh()
        self._validate_recent_files_async()

    @property
    def result_actions_widget(self) -> ResultActionsWidget:
        """Return the result browser owned by this window."""
        return self._result_actions_widget

    @property
    def workflow_plan(self) -> WorkflowPlan:
        """Return the semantic action plan currently rendered by the window."""
        plan = self._actions.plan
        if plan is None:
            raise RuntimeError("Workflow plan has not been rendered yet.")
        return plan

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(SPACE_XXL, 0, SPACE_XL, 0)
        root.setSpacing(SPACE_SM)


        # Fixed navigation is separate from the scrollable guided cards.
        # Keep these controls small and neutral, like the Results controls.
        def navigation_group(parent: QWidget, name: str) -> _HeaderActionBar:
            return _HeaderActionBar(
                parent, name, centered=name == "workflowCalculationNavigation",
            )

        def navigation_button(
            group: _HeaderActionBar,
            label: str,
            icon: QIcon,
            tooltip: str,
            callback: Callable[[], None],
            *,
            short_title: str,
            recent_menu: bool = False,
        ) -> QToolButton:
            button = (
                _RecentFooterButton(label, group)
                if recent_menu else CenteredIconToolButton(group)
            )
            if not recent_menu:
                button.setText(label)
            button.setIcon(icon)
            button.setIconSize(QSize(24, 24))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setFixedHeight(_HeaderActionBar.BUTTON_HEIGHT)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            mid = button.palette().color(QPalette.ColorRole.Mid).name()
            button.setStyleSheet(
                _navigation_button_stylesheet(
                    button.palette(), "QToolButton"
                )
                + f"QToolButton::menu-button {{ width: 28px; border-left: 1px solid {mid}; }}"
            )
            if recent_menu:
                button.set_base_tooltip(tooltip)
                button.setPopupMode(
                    QToolButton.ToolButtonPopupMode.MenuButtonPopup
                )
                button.setMenu(QMenu(button))
            else:
                button.setToolTip(tooltip)
            button.setAccessibleName(label)
            button.clicked.connect(callback)
            group.register(button, short_title=short_title)
            return button

        # Exactly three equal, non-draggable columns. Keep the normal gaps
        # between their content areas, but let each header use its full width.
        columns_row = QHBoxLayout()
        columns_row.setContentsMargins(0, 0, 0, 0)
        columns_row.setSpacing(SPACE_SM)
        root.addLayout(columns_row, 1)
        self._columns_layout = columns_row

        # The first column owns both current-structure information and all
        # structural workflows. Its content scrolls as a single unit.
        structure_column = QWidget(central)
        structure_column.setObjectName("workflowStructureColumn")
        structure_column.setMinimumWidth(300)
        structure_column.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        structure_layout = QVBoxLayout(structure_column)
        structure_layout.setContentsMargins(0, 0, 0, 0)
        structure_layout.setSpacing(SPACE_SM)
        structure_column_navigation = navigation_group(
            structure_column, "workflowStructureNavigation"
        )
        structure_layout.addWidget(structure_column_navigation)

        # Keep the existing right inset for ordinary content, but not for
        # the navigation header: it needs the full width for three actions.
        structure_detail = QWidget(structure_column)
        structure_detail_layout = QVBoxLayout(structure_detail)
        structure_detail_layout.setContentsMargins(0, 0, SPACE_XL, 0)
        self._structure_title = QLabel("Structure", structure_detail)
        self._structure_title.setObjectName("workflowStructureTitle")
        self._structure_title.setFont(
            heading_font(self._structure_title.font(), "dialog")
        )
        self._structure_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        structure_detail_layout.addWidget(self._structure_title)

        self._subtitle = QLabel(structure_detail)
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(secondary_text_stylesheet(self.palette()))
        structure_detail_layout.addWidget(self._subtitle)

        structure_scroll = QScrollArea(structure_detail)
        structure_scroll.setObjectName("workflowStructureActionsScrollArea")
        structure_scroll.setFrameShape(QFrame.Shape.NoFrame)
        structure_scroll.setWidgetResizable(True)
        structure_scroll.setAlignment(Qt.AlignmentFlag.AlignTop)
        structure_body = QWidget(structure_scroll)
        structure_body_layout = QVBoxLayout(structure_body)
        structure_body_layout.setContentsMargins(0, 0, SPACE_SM, 0)
        structure_body_layout.setSpacing(SPACE_XL)
        structure_body_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._structure_overview = StructureOverviewWidget(structure_body)
        self._structure_overview.visualizeRequested.connect(self._visualize_structure)
        structure_body_layout.addWidget(self._structure_overview)
        self._structure_actions = WorkflowActionsWidget(
            structure_body, column="structure",
            excluded_commands=(ContinueRecent, StartOver, VisualizeStructure),
        )
        self._structure_actions.commandRequested.connect(self.execute_workflow_command)
        structure_body_layout.addWidget(self._structure_actions)
        structure_body_layout.addStretch(1)
        structure_scroll.setWidget(structure_body)
        structure_detail_layout.addWidget(structure_scroll, 1)
        structure_layout.addWidget(structure_detail, 1)
        columns_row.addWidget(structure_column, 1)

        # Calculation commands have their own column, independently scrollable
        # from structure actions and from the persistent results sidebar.
        content = QWidget(central)
        content.setObjectName("workflowCalculateColumn")
        content.setMinimumWidth(300)
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(SPACE_SM)
        content_navigation = navigation_group(
            content, "workflowCalculationNavigation"
        )
        content_layout.addWidget(content_navigation)

        content_detail = QWidget(content)
        content_detail_layout = QVBoxLayout(content_detail)
        content_detail_layout.setContentsMargins(0, 0, SPACE_XL, 0)
        title = QLabel("Calculate", content_detail)
        title.setObjectName("workflowCalculateTitle")
        title.setFont(heading_font(title.font(), "dialog"))
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        content_detail_layout.addWidget(title)

        self._calculate_notice = QLabel(content_detail)
        self._calculate_notice.setWordWrap(True)
        self._calculate_notice.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._calculate_notice.setStyleSheet(
            secondary_text_stylesheet(self.palette())
        )
        content_detail_layout.addWidget(self._calculate_notice)

        self._actions = WorkflowActionsWidget(
            content, column="calculate",
            excluded_commands=(CustomTask, RepeatRecentInput),
        )
        self._actions.commandRequested.connect(self.execute_workflow_command)
        for cards in (self._structure_actions, self._actions):
            cards.naturalCardHeightChanged.connect(self._sync_action_card_heights)
        action_scroll = QScrollArea(content_detail)
        action_scroll.setObjectName("workflowActionScrollArea")
        action_scroll.setFrameShape(QFrame.Shape.NoFrame)
        action_scroll.setWidgetResizable(True)
        action_scroll.setAlignment(Qt.AlignmentFlag.AlignTop)
        action_scroll.setWidget(self._actions)
        content_detail_layout.addWidget(action_scroll, 1)
        content_layout.addWidget(content_detail, 1)

        columns_row.addWidget(content, 1)

        # Results share the same borderless column treatment as the actions.
        side = QWidget(central)
        side.setObjectName("workflowResultsColumn")
        side.setMinimumWidth(285)
        side.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(SPACE_SM)
        side_navigation = navigation_group(
            side, "workflowResultsNavigation"
        )
        side_layout.addWidget(side_navigation)

        result_actions_title = QLabel("Results", side)
        result_actions_title.setObjectName("workflowResultsTitle")
        result_actions_title.setFont(
            heading_font(result_actions_title.font(), "dialog")
        )
        result_actions_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        side_layout.addWidget(result_actions_title)

        self._result_actions = QFrame(side)
        self._result_actions.setFrameShape(QFrame.Shape.NoFrame)
        result_actions_layout = QVBoxLayout(self._result_actions)
        result_actions_layout.setContentsMargins(SPACE_SM, SPACE_SM, SPACE_SM, SPACE_SM)
        result_actions_layout.setSpacing(SPACE_XS)
        self._result_actions_widget = ResultActionsWidget(
            lambda value, action: execute_value_action(value, action, self),
            show_values_without_actions=False,
            show_history_button=False,
            empty_text="",  # The Results heading and Load Result button suffice.
            parent=self._result_actions,
        )
        result_actions_layout.addWidget(self._result_actions_widget, 1)
        side_layout.addWidget(self._result_actions, 1)

        columns_row.addWidget(side, 1)

        # Stable commands belong to the headers of their workflow columns.
        # Recent Structures retains its position when Start from Scratch appears.
        self._structure_navigation = structure_column_navigation
        self._recent_structures_button = navigation_button(
            structure_column_navigation,
            "Recent Structures",
            badge_icon(QIcon(str(icon_path("bulk_crystal.png"))), "recent"),
            "Open the latest structure or choose another",
            lambda: self._open_recent("structure"),
            short_title="Recent",
            recent_menu=True,
        )
        self._start_over_button = navigation_button(
            structure_column_navigation,
            "Start from Scratch",
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
            "Clear the current workspace; existing results are kept",
            self._start_over,
            short_title="Start",
        )

        self._repeat_button = navigation_button(
            content_navigation,
            "Repeat Calculation",
            badge_icon(QIcon(str(icon_path("calculation-gear.svg"))), "recent"),
            "Repeat the most recent input or choose another",
            lambda: self._open_recent("input"),
            short_title="Repeat",
            recent_menu=True,
        )
        self._load_input_button = navigation_button(
            content_navigation,
            "Load Input File",
            QIcon.fromTheme(
                "document-open",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            ),
            "Load, edit, save or calculate from an SPR-KKR input file",
            self._load_input_file,
            short_title="Load Input",
        )
        self._custom_button = navigation_button(
            content_navigation,
            "Custom Input File",
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "Choose a registered SPR-KKR task and configure its parameters",
            self._custom_task,
            short_title="Custom Input",
        )

        self._recent_results_button = navigation_button(
            side_navigation,
            "Recent Results",
            badge_icon(QIcon(str(icon_path("result-graph.svg"))), "recent"),
            "Open the latest result or choose another",
            lambda: self._open_recent("output"),
            short_title="Recent",
            recent_menu=True,
        )
        self._result_actions_widget.move_import_controls_to(
            side_navigation.layout()
        )
        for button in (
            self._result_actions_widget.load_result_button,
            self._result_actions_widget.import_directory_button,
        ):
            button.setStyleSheet(
                _navigation_button_stylesheet(button.palette(), "QPushButton")
            )
            side_navigation.register(
                button,
                short_title=(
                    "Load Result"
                    if button is self._result_actions_widget.load_result_button
                    else "Import Directory"
                ),
            )
            side_navigation.set_button_label(
                button,
                "Load Result File"
                if button is self._result_actions_widget.load_result_button
                else "Import All From Directory",
            )

        # Keep the Results-only utility toolbar at its original height and
        # distance from the window edge, without an enclosing ruler.
        results_footer = QFrame(side)
        results_footer.setObjectName("workflowResultsFooter")
        results_footer.setFrameShape(QFrame.Shape.NoFrame)
        results_footer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        footer_stack = QVBoxLayout(results_footer)
        footer_stack.setContentsMargins(
            0, 0, 0, _HeaderActionBar.VERTICAL_GAP
        )
        footer_stack.setSpacing(_HeaderActionBar.VERTICAL_GAP)
        # Preserve the one-pixel layout height previously occupied by the
        # separator; removing the line must not shift the footer controls.
        footer_stack.addSpacing(1)
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(SPACE_XS)
        footer_stack.addLayout(footer_row)

        def footer_button(
            label: str, icon: QIcon, tooltip: str,
            callback: Callable[[], None],
        ) -> QToolButton:
            button = CenteredIconToolButton(results_footer)
            button.setText(label)
            button.setIcon(icon)
            button.setIconSize(QSize(26, 26))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setFixedHeight(68)
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
            )
            button.setStyleSheet(
                _navigation_button_stylesheet(button.palette(), "QToolButton")
            )
            button.setToolTip(tooltip)
            button.setAccessibleName(label)
            button.clicked.connect(callback)
            footer_row.addWidget(button, 1)
            return button

        self._project_browser_button = footer_button(
            "Project Browser",
            QIcon.fromTheme(
                "folder-open",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            ),
            "Browse projects and past calculations",
            lambda: self.projectBrowserRequested.emit(),
        )
        self._settings_button = footer_button(
            "Settings", settings_icon(), "Configure Ase2sprkkr (Ctrl+,)",
            self._open_settings,
        )
        self._settings_button.setShortcut(QKeySequence("Ctrl+,"))
        self._close_button = footer_button(
            "Close",
            QIcon.fromTheme(
                "application-exit",
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton),
            ),
            "Close Ase2sprkkr (Ctrl+Q)", self.close,
        )
        self._close_button.setShortcut(QKeySequence("Ctrl+Q"))
        side_layout.addWidget(
            results_footer, alignment=Qt.AlignmentFlag.AlignBottom
        )
        self._results_footer = results_footer

        # All three headers switch modes together, even when only one column
        # becomes too narrow for its full labels.
        self._header_bars = (
            structure_column_navigation, content_navigation, side_navigation,
        )
        self._structure_navigation = structure_column_navigation
        self._calculate_navigation = content_navigation
        self._syncing_headers = False
        for bar in self._header_bars:
            bar.layoutChanged.connect(self._sync_header_modes)
        self._sync_header_modes()

    def _sync_header_modes(self) -> None:
        if getattr(self, "_syncing_headers", False):
            return
        self._syncing_headers = True
        try:
            modes = ("full", "short", "icon")
            mode = max(
                (bar.required_mode() for bar in self._header_bars),
                key=modes.index,
            )
            for bar in self._header_bars:
                if bar._mode != mode or not bar._mode_applied:
                    bar.set_mode(mode)
        finally:
            self._syncing_headers = False

    def _open_recent(self, kind: str, path: str | None = None) -> None:
        """Use the latest path for the main button, or an explicit menu item."""
        paths = self.recent_history.paths(kind)
        chosen = path if path is not None else (paths[0] if paths else None)
        if chosen is None:
            return
        if kind == "input":
            self.execute_workflow_command(RepeatRecentInput(chosen))
        else:
            self._continue_recent(kind, chosen)

    def _update_navigation(self, snapshot: RecentFilesSnapshot) -> None:
        """Refresh button availability and rebuild menus only for changed history."""
        has_structure = self.controller.atoms is not None
        has_workspace = (
            has_structure
            or self.controller.unresolved_cluster_path is not None
            or self.controller.input_parameters is not None
        )
        self._start_over_button.setVisible(has_workspace)
        self._start_over_button.setEnabled(has_workspace)
        self._structure_navigation.refresh()
        label = "Custom Calculation" if has_structure else "Custom Input File"
        self._calculate_navigation.set_button_label(
            self._custom_button, label,
            short_title="Custom Calculation" if has_structure else "Custom Input",
        )

        if snapshot == self._navigation_snapshot:
            return
        self._navigation_snapshot = snapshot
        for kind, button in (
            ("structure", self._recent_structures_button),
            ("input", self._repeat_button),
            ("output", self._recent_results_button),
        ):
            paths = snapshot.paths(kind)
            button.setEnabled(bool(paths))
            button.set_recent_path(paths[0] if paths else None)
            menu = button.menu()
            menu.clear()
            for item in recent_menu_items(paths):
                action = menu.addAction(item.label)
                action.setToolTip(item.tooltip)
                action.triggered.connect(
                    lambda _checked=False, item_kind=kind, item_path=item.path:
                    self._open_recent(item_kind, item_path)
                )
            if kind == "output" and paths:
                menu.addSeparator()
                menu.addAction("Load all results").triggered.connect(
                    lambda _checked=False: self.execute_workflow_command(
                        LoadAllRecentResults()
                    )
                )

    def _sync_action_card_heights(self) -> None:
        height = max(
            self._structure_actions.natural_card_height,
            self._actions.natural_card_height,
        )
        self._structure_actions.set_uniform_card_height(height)
        self._actions.set_uniform_card_height(height)

    def _refresh_recent_history(self) -> None:
        self._update_navigation(self.recent_history.read_snapshot())
        # Only input-history changes affect the planned action cards in a loaded workspace.
        inputs_changed = self.recent_history.paths("input") != self._displayed_recent_inputs
        if inputs_changed or (
            self.controller.atoms is None
            and self.controller.unresolved_cluster_path is None
        ):
            self._refresh()
        self._validate_recent_files_async()

    def _validate_recent_files_async(self) -> None:
        """Keep the initial menus responsive; inspect paths in one daemon worker."""
        if self._recent_validation_running:
            return
        snapshot = self.recent_history.read_snapshot()
        if not any(snapshot.paths(kind) for kind in RECENT_KINDS):
            return
        signals = _RecentValidationSignals()
        signals.finished.connect(self._recent_files_checked)
        self._recent_validation_signals = signals
        self._recent_validation_running = True
        Thread(
            target=_check_recent_files, args=(snapshot, signals),
            name="recent-files-check", daemon=True,
        ).start()

    def _recent_files_checked(self, snapshot: RecentFilesSnapshot, missing: dict) -> None:
        self._recent_validation_running = False
        self._recent_validation_signals = None
        if self.recent_history.read_snapshot() != snapshot:
            # History changed while the worker was checking a filesystem.
            # Its result is obsolete; validate the latest snapshot instead.
            self._validate_recent_files_async()
            return
        # The history emits one changed signal, replacing the whole menu
        # presentation once, and only when missing files were actually found.
        self.recent_history.remove_known_missing(snapshot, missing)

    def _refresh(self) -> None:
        snapshot = self.recent_history.read_snapshot()
        self._displayed_recent_inputs = snapshot.input
        plan = self._workflow_planner.for_workspace(
            self.controller,
            recent=snapshot,
        )
        atoms = self.controller.atoms
        kind = self.controller.structure_kind()
        self._structure_overview.set_structure(
            atoms, kind=kind, scf_status=self.controller.scf_status(),
        )
        self._structure_overview.setVisible(atoms is not None)
        # Formula, dimensionality and SCF state belong to the structure panel.
        # Keep onboarding and diagnostic messages in the structure column.
        invalid_cluster = (
            kind == "0d" and getattr(atoms, "embedding_host", None) is None
        )
        self._structure_title.setText(
            "Structure" if atoms is not None else "Start with..."
        )
        self._subtitle.setText(plan.subtitle)
        self._subtitle.setVisible(bool(plan.subtitle) and (atoms is None or invalid_cluster))
        self._structure_actions.set_plan(plan)
        self._actions.set_plan(plan)
        self._update_navigation(snapshot)
        if atoms is None:
            self._calculate_notice.setText(
                "First, create a structure or load an existing structure or potential."
            )
        else:
            self._calculate_notice.setText(
                "No guided calculation is available for the current structure."
            )
        self._calculate_notice.setVisible(not self._actions.has_actions)

    def execute_workflow_command(self, command: WorkflowCommand) -> None:
        """Mechanically route one already-approved workflow command."""
        if isinstance(command, RunTask):
            self._prepare_task(command.backend_task)
            return
        if isinstance(command, ReconvergeScf):
            self._prepare_task("scf", restart_scf=True)
            return
        if isinstance(command, CustomTask):
            self._custom_task()
            return
        if isinstance(command, ConvergeHostScf):
            calculation_flow.configure_and_run_host_scf(
                self.controller, self.recent_history, self,
                dataset_default_mode=self.settings.dataset_default_mode,
                restart_host_scf=command.restart_scf,
                track_launch_monitor=self._track_launch_monitor,
                project_repository=self.project_repository,
            )
            return
        if isinstance(command, UpdateEmptySpheres):
            self._update_empty_spheres()
            return
        if isinstance(command, CreateStructure):
            {
                CreateStructureKind.THREE_D: self._create_3d,
                CreateStructureKind.PROTOTYPE: self._create_from_database,
                CreateStructureKind.SHELL: self._create_shell,
                CreateStructureKind.SURFACE: self._create_surface,
                CreateStructureKind.TWO_D: self._create_transition,
            }[command.kind]()
            return
        if isinstance(command, ExplainEmbedding):
            self._explain_embedded_cluster()
            return
        if isinstance(command, BuildEmbedding):
            structure_flows.build_embedding_structure(self.controller, self)
            return
        if isinstance(command, Build2D):
            surface_mode = {
                Build2DKind.SURFACE: True,
                Build2DKind.STRUCTURE: False,
            }[command.kind]
            self._build_2d(surface_mode=surface_mode)
            return
        if isinstance(command, Load):
            {
                LoadKind.ONLINE_STRUCTURE: self._download_structure,
                LoadKind.STRUCTURE: self._load_structure,
                LoadKind.OUTPUT: self._load_output,
            }[command.kind]()
            return
        if isinstance(command, ContinueRecent):
            self._continue_recent(command.kind, command.path)
            return
        if isinstance(command, LoadAllRecentResults):
            file_flows.load_all_recent_outputs(
                self.controller, self.recent_history, self,
            )
            return
        if isinstance(command, RepeatRecentInput):
            if command.path is None:
                return
            custom_flow.load_custom_input(
                self.controller, self.recent_history, self, command.path,
                track_launch_monitor=self._track_launch_monitor,
                project_repository=self.project_repository,
            )
            return
        if isinstance(command, VisualizeStructure):
            self._visualize_structure()
            return
        if isinstance(command, EditStructure):
            structure_flows.edit_structure(
                self.controller, self, recent_files=self.recent_history
            )
            return
        if isinstance(command, SaveStructure):
            self._save_structure()
            return
        if isinstance(command, LoadHostPotential):
            file_flows.load_host_potential(
                self.controller, self.recent_history, self
            )
            return
        if isinstance(command, AttachHostPotential):
            file_flows.attach_host_potential(
                self.controller, self.recent_history, self
            )
            return
        if isinstance(command, CreateHostPotential):
            file_flows.create_host_potential(
                self.controller, self.recent_history, self
            )
            return
        if isinstance(command, UseForNewCalculation):
            self._use_for_new_calculation()
            return
        if isinstance(command, StartOver):
            self._start_over()
            return
        raise TypeError(f"Unsupported workflow command {type(command).__name__}.")

    def _explain_embedded_cluster(self) -> None:
        answer = QMessageBox.question(
            self, "Creating an Embedded Cluster",
            "An embedded cluster needs a periodic host. First create or load "
            "a bulk (3D) or layered (2D) structure; then choose "
            "'Build Embedded Cluster' from the structure actions.\n\n"
            "Show this introductory action again?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.No:
            self.settings.show_embedded_cluster_hint = False
            if self.settings.save():
                self._refresh()
            else:
                self.settings.show_embedded_cluster_hint = True
                QMessageBox.warning(
                    self, "Cannot Save Settings",
                    "Could not save the preference; the introductory action "
                    "will remain visible.",
                )

    def _on_structure_changed(self, _atoms: Any) -> None:
        self._refresh()

    def _create_3d(self) -> None:
        structure_flows.create_structure(self.controller, self)

    def _create_shell(self) -> None:
        structure_flows.create_structure_by_shell(
            self.controller, self, settings=self.settings
        )

    def _create_from_database(self) -> None:
        structure_flows.create_structure_from_database(self.controller, self)

    def _download_structure(self) -> None:
        structure_flows.download_structure(self.controller, self)

    def _create_surface(self) -> None:
        structure_flows.create_2d_from_new_structure(
            self.controller, self.recent_history, self, surface_mode=True
        )

    def _create_transition(self) -> None:
        structure_flows.create_2d_from_new_structure(
            self.controller, self.recent_history, self, surface_mode=False
        )

    def _load_structure(self) -> None:
        file_flows.choose_and_load_structure(
            self.controller, self.recent_history, self
        )

    def _load_output(self) -> None:
        file_flows.choose_and_load_output(
            self.controller, self.recent_history, self
        )

    def _continue_recent(self, kind: RecentLaunchKind, file_path: str) -> None:
        file_flows.continue_recent(
            self.controller, self.recent_history, kind, file_path, self,
        )

    def _build_2d(self, _checked: bool = False, *, surface_mode: bool = False) -> None:
        structure_flows.build_2d_structure(
            self.controller,
            self.recent_history,
            self,
            surface_mode=surface_mode,
        )

    def _prepare_task(self, task: str, *, restart_scf: bool = False) -> None:
        from ase2sprkkr_gui.gui.input_parameters.tasks import is_guided_task
        if not is_guided_task(task):
            from ase2sprkkr import InputParameters
            from ase2sprkkr_gui.gui.input_parameters.dataset import apply_default_dataset

            parameters = InputParameters.for_task(task)
            apply_default_dataset(
                parameters, self.settings.dataset_default_mode, self.controller.atoms,
            )
            custom_flow.edit_custom_parameters(
                self.controller, self.recent_history, self, parameters,
                track_launch_monitor=self._track_launch_monitor,
                project_repository=self.project_repository,
            )
            return
        calculation_flow.configure_and_run_task(
            self.controller,
            self.recent_history,
            self,
            task,
            dataset_default_mode=self.settings.dataset_default_mode,
            restart_scf=restart_scf,
            track_launch_monitor=self._track_launch_monitor,
            project_repository=self.project_repository,
        )

    def _update_empty_spheres(self) -> None:
        structure_flows.update_empty_spheres(self.controller, self)

    def _use_for_new_calculation(self) -> None:
        calculation_flow.use_for_new_calculation(self.controller, self)

    def _start_over(self) -> None:
        answer = QMessageBox.question(
            self,
            "Start Over?",
            "Really start over? The current structure and calculation settings "
            "will be cleared. Existing calculation results will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.reset()

    def _visualize_structure(self) -> None:
        visualization_flow.visualize_structure(self.controller, self.settings, self)

    def _save_structure(self) -> None:
        file_flows.save_structure(self.controller, self.recent_history, self)

    def _open_settings(self, *, preferred_tasks: bool = False) -> None:
        accepted = (
            edit_settings(self.settings, self, initial_tab="Preferred tasks")
            if preferred_tasks else edit_settings(self.settings, self)
        )
        if accepted:
            self._refresh()

    def _custom_task(self) -> None:
        custom_flow.choose_custom_task(
            self.controller, self.recent_history, self,
            dataset_default_mode=self.settings.dataset_default_mode,
            track_launch_monitor=self._track_launch_monitor,
            project_repository=self.project_repository,
        )

    def _load_input_file(self) -> None:
        custom_flow.choose_custom_input(
            self.controller, self.recent_history, self,
            track_launch_monitor=self._track_launch_monitor,
            project_repository=self.project_repository,
        )
